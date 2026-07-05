"""Supersampled offscreen gameplay surface and GPU compositing."""

from __future__ import annotations

import array
import os
from contextlib import contextmanager

from arcade.gl import BufferDescription

from .viewport import DisplayLayout

_BLIT_UVS = array.array("f", [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1])


def render_supersample(layout: DisplayLayout) -> int:
    """Internal render multiplier (1–3) for antialiased upscaling."""
    override = os.environ.get("PATHWISE_RENDER_SCALE", "").strip()
    if override:
        try:
            return max(1, min(3, int(float(override))))
        except ValueError:
            pass
    if layout.scale <= 1.01:
        return 1
    if layout.scale >= 2.0:
        return 2
    return 2


def _ndc_lbwh(
    left: float, bottom: float, width: float, height: float, win_w: int, win_h: int
) -> array.array:
    x0 = 2 * left / win_w - 1
    x1 = 2 * (left + width) / win_w - 1
    y0 = 2 * bottom / win_h - 1
    y1 = 2 * (bottom + height) / win_h - 1
    return array.array("f", [x0, y0, x1, y0, x1, y1, x0, y0, x1, y1, x0, y1])


class GameplaySurface:
    """Reusable FBO + linear-filter blit for scaled fullscreen play."""

    def __init__(self) -> None:
        self._fbo = None
        self._tex = None
        self._fbo_size = (0, 0)
        self._blit_geo = None
        self._blit_vert_buf = None
        self._blit_uv_buf = None
        self._blit_key: tuple[float, float, float, float, int, int] | None = None

    def needs_offscreen(self, layout: DisplayLayout) -> bool:
        return layout.uses_gpu_viewport

    def fbo_pixel_size(self, layout: DisplayLayout) -> tuple[int, int]:
        ss = render_supersample(layout)
        return (
            max(1, int(round(layout.sim_width * ss))),
            max(1, int(round(layout.sim_height * ss))),
        )

    def _ensure_fbo(self, ctx, width: int, height: int) -> None:
        if (width, height) == self._fbo_size and self._fbo is not None:
            return
        self._fbo_size = (width, height)
        self._tex = ctx.texture((width, height))
        self._tex.filter = (ctx.LINEAR, ctx.LINEAR)
        self._fbo = ctx.framebuffer(color_attachments=[self._tex])
        self._blit_geo = None
        self._blit_key = None

    def _ensure_blit_geometry(
        self,
        ctx,
        left: float,
        bottom: float,
        width: float,
        height: float,
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
        self._ensure_blit_geometry(
            ctx,
            layout.dest_left,
            layout.dest_bottom,
            layout.dest_width,
            layout.dest_height,
            ww,
            wh,
        )
        if self._blit_geo is None:
            return
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
        self._ensure_fbo(ctx, fw, fh)
        saved_viewport = window.viewport
        saved_projection = window.projection
        with self._fbo.activate():
            window.clear()
            window.viewport = (0, 0, fw, fh)
            from pyglet.math import Mat4

            window.projection = Mat4.orthogonal_projection(
                0, layout.sim_width, 0, layout.sim_height, -8192, 8192
            )
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
    """Test hook — drop cached GL resources between headless runs."""
    global _shared_surface
    _shared_surface = None
