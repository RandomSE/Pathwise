"""Fixed-resolution offscreen gameplay surface and GPU compositing."""

from __future__ import annotations

import array
import math
import os
from contextlib import contextmanager

from arcade.gl import BufferDescription

from .projection_cache import sim_projection
from .viewport import DisplayLayout

_BLIT_UVS = array.array("f", [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1])

# Legacy 1600x900 cap kept so tests can assert HD is no longer that size.
FIXED_FBO_WIDTH = 1600
FIXED_FBO_HEIGHT = 900
_MAX_INTEGER_SIM_SCALE = 3
_MAX_ENV_RENDER_SCALE = 3.0


def _env_render_scale_override() -> float | None:
    raw = os.environ.get("PATHWISE_RENDER_SCALE", "").strip()
    if not raw:
        return None
    try:
        return max(1.0, min(_MAX_ENV_RENDER_SCALE, float(raw)))
    except ValueError:
        return None


def upscale_filter_mode() -> str:
    raw = os.environ.get("PATHWISE_UPSCALE_FILTER", "auto").strip().lower()
    if raw in ("smooth", "linear"):
        return "smooth"
    if raw in ("sharp", "nearest"):
        return "sharp"
    return "auto"


def integer_sim_render_scale(layout: DisplayLayout) -> int:
    """Integer sim-to-FBO scale used by PATHWISE_RENDER_SCALE."""
    override = _env_render_scale_override()
    if override is not None:
        return max(1, min(_MAX_INTEGER_SIM_SCALE, int(round(override))))
    dw, dh = layout.dest_pixel_size()
    sx = dw / max(1, layout.sim_width)
    sy = dh / max(1, layout.sim_height)
    return max(1, min(_MAX_INTEGER_SIM_SCALE, int(round(min(sx, sy)))))


def fixed_fbo_pixel_size(layout: DisplayLayout) -> tuple[int, int]:
    """Dest-native FBO so present is 1:1. A 0.9 LINEAR blit of 2x sim races bands down the screen."""
    if not layout.uses_gpu_viewport:
        return layout.sim_width, layout.sim_height
    if _env_render_scale_override() is not None:
        k = integer_sim_render_scale(layout)
        return layout.sim_width * k, layout.sim_height * k
    return layout.dest_pixel_size()


def present_uses_nearest(layout: DisplayLayout) -> bool:
    """NEAREST only when present is 1:1 or an integer multiple; else LINEAR."""
    mode = upscale_filter_mode()
    if mode == "sharp":
        return True
    if mode == "smooth":
        return False
    fw, fh = fixed_fbo_pixel_size(layout)
    dw, dh = layout.dest_pixel_size()
    if (fw, fh) == (dw, dh):
        return True
    return dw % fw == 0 and dh % fh == 0 and fw > 0 and fh > 0


def fixed_fbo_render_multiplier(layout: DisplayLayout) -> float:
    """Sim-to-FBO scale used for sprite baking (stable, not adaptive)."""
    if not layout.uses_gpu_viewport:
        return 1.0
    fw, fh = fixed_fbo_pixel_size(layout)
    return max(fw / layout.sim_width, fh / layout.sim_height)


def fixed_sprite_bake_multiplier(layout: DisplayLayout) -> int:
    """Bake sprites to match the fixed FBO scale (stable, not full display res)."""
    if not layout.uses_gpu_viewport:
        return 1
    mult = fixed_fbo_render_multiplier(layout)
    if mult < 1.15:
        return 1
    return max(1, min(2, int(math.ceil(mult))))


def prewarm_draw_gpu_assets(layout: DisplayLayout) -> None:
    """Register recurring draw textures with the GL atlas before FBO rendering."""
    if not layout.uses_gpu_viewport:
        return
    from pathwise.traffic_light_batch import shared_traffic_light_batch

    batch = shared_traffic_light_batch()
    for on in (False, True):
        for index in range(3):
            batch._texture(on, index)


def render_supersample(layout: DisplayLayout) -> int:
    """Backward-compatible int scale helper used in tests."""
    return max(1, int(round(fixed_fbo_render_multiplier(layout))))


def _texture_filter(ctx, layout: DisplayLayout | None = None):
    if layout is not None:
        nearest = present_uses_nearest(layout)
    else:
        nearest = upscale_filter_mode() == "sharp"
    if nearest:
        return ctx.NEAREST, ctx.NEAREST
    return ctx.LINEAR, ctx.LINEAR


def _ndc_lbwh(
    left: float, bottom: float, width: float, height: float, win_w: int, win_h: int
) -> array.array:
    x0 = 2 * left / win_w - 1
    x1 = 2 * (left + width) / win_w - 1
    y0 = 2 * bottom / win_h - 1
    y1 = 2 * (bottom + height) / win_h - 1
    return array.array("f", [x0, y0, x1, y0, x1, y1, x0, y0, x1, y1, x0, y1])


class GameplaySurface:
    """Reusable FBO + filtered GPU blit for scaled fullscreen play."""

    def __init__(self) -> None:
        self._fbo = None
        self._tex = None
        self._fbo_size = (0, 0)
        self._blit_geo = None
        self._blit_vert_buf = None
        self._blit_uv_buf = None
        self._blit_key: tuple[int, int, int, int, int, int] | None = None

    def needs_offscreen(self, layout: DisplayLayout) -> bool:
        return layout.uses_gpu_viewport

    def fbo_pixel_size(self, layout: DisplayLayout) -> tuple[int, int]:
        return fixed_fbo_pixel_size(layout)

    def _ensure_fbo(self, ctx, width: int, height: int, layout: DisplayLayout | None = None) -> None:
        if (width, height) == self._fbo_size and self._fbo is not None:
            self._tex.filter = _texture_filter(ctx, layout)
            return
        self._fbo_size = (width, height)
        self._tex = ctx.texture((width, height))
        self._tex.filter = _texture_filter(ctx, layout)
        self._fbo = ctx.framebuffer(color_attachments=[self._tex])
        self._blit_geo = None
        self._blit_key = None

    def _ensure_blit_geometry(
        self,
        ctx,
        left: int,
        bottom: int,
        width: int,
        height: int,
        win_w: int,
        win_h: int,
    ) -> None:
        key = (left, bottom, width, height, win_w, win_h)
        if self._blit_geo is not None and self._blit_key == key:
            return
        self._blit_key = key
        verts = _ndc_lbwh(left, bottom, width, height, win_w, win_h)
        if self._blit_vert_buf is None:
            self._blit_vert_buf = ctx.buffer(reserve=verts.itemsize * len(verts))
            self._blit_uv_buf = ctx.buffer(data=_BLIT_UVS)
        self._blit_vert_buf.write(verts.tobytes())
        self._blit_geo = ctx.geometry(
            [
                BufferDescription(self._blit_vert_buf, "2f", ["in_vert"]),
                BufferDescription(self._blit_uv_buf, "2f", ["in_uv"]),
            ]
        )

    def blit_to_window(self, window, layout: DisplayLayout) -> None:
        if self._fbo is None or self._tex is None:
            return
        ctx = window.ctx
        ww, wh = layout.window_width, layout.window_height
        left, bottom, width, height = layout.snapped_dest_rect()
        self._ensure_blit_geometry(ctx, left, bottom, width, height, ww, wh)
        if self._blit_geo is None:
            return
        self._tex.filter = _texture_filter(ctx, layout)
        window.use()
        window.viewport = (0, 0, ww, wh)
        self._tex.use(0)
        prog = ctx.utility_textured_quad_program
        prog["texture0"] = 0
        self._blit_geo.render(prog)

    @contextmanager
    def draw_target(self, window, layout: DisplayLayout):
        """Render sim scene into FBO; caller composites after the block."""
        ctx = window.ctx
        fw, fh = self.fbo_pixel_size(layout)
        self._ensure_fbo(ctx, fw, fh, layout)
        saved_viewport = window.viewport
        saved_projection = window.projection
        with self._fbo.activate():
            window.clear()
            window.viewport = (0, 0, fw, fh)
            window.projection = sim_projection(layout.sim_width, layout.sim_height)
            try:
                yield
            finally:
                window.viewport = saved_viewport
                window.projection = saved_projection


_shared_surface: GameplaySurface | None = None


def shared_gameplay_surface() -> GameplaySurface:
    global _shared_surface
    if _shared_surface is None:
        _shared_surface = GameplaySurface()
    return _shared_surface


def reset_shared_gameplay_surface() -> None:
    """Test hook: drop cached GL resources between headless runs."""
    global _shared_surface
    from .projection_cache import reset_projection_cache

    _shared_surface = None
    reset_projection_cache()
