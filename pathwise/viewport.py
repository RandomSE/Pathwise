"""Simulation viewport (fixed design resolution) and display scaling."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from pathwise import commonUtils
from pathwise.geom import Rect
from pathwise.game_tuning import DEFAULT_TUNING

_FRAME_RECORD_VIEW_PAD = DEFAULT_TUNING.FRAME_RECORD_VIEW_PAD
_LETTERBOX_COLOR = (236, 244, 252)


def sim_viewport_size() -> tuple[int, int]:
    return commonUtils.WIDTH, commonUtils.HEIGHT


def normalize_viewport_size(
    viewport_w: int | None = None, viewport_h: int | None = None
) -> tuple[int, int]:
    """Simulation always uses the design resolution regardless of window size."""
    _ = viewport_w, viewport_h
    return sim_viewport_size()


def camera_offset_for(
    player_center_x: int,
    player_center_y: int,
    viewport_w: int,
    viewport_h: int,
) -> tuple[int, int]:
    return (
        player_center_x - viewport_w // 2,
        player_center_y - viewport_h // 2,
    )


def view_rect_for_camera(
    camera_offset: tuple[int, int],
    viewport_w: int,
    viewport_h: int,
    *,
    pad: int = _FRAME_RECORD_VIEW_PAD,
) -> Rect:
    return Rect(
        camera_offset[0] - pad,
        camera_offset[1] - pad,
        viewport_w + pad * 2,
        viewport_h + pad * 2,
    )


@dataclass(frozen=True)
class DisplayLayout:
    """Maps fixed sim surface (800x600) onto the physical window with uniform scale."""

    window_width: int
    window_height: int
    sim_width: int
    sim_height: int
    scale: float
    dest_left: float
    dest_bottom: float
    dest_width: float
    dest_height: float

    @classmethod
    def fit_window(
        cls,
        window_width: int,
        window_height: int,
        *,
        sim_width: int | None = None,
        sim_height: int | None = None,
    ) -> DisplayLayout:
        sw, sh = sim_viewport_size()
        if sim_width is not None:
            sw = sim_width
        if sim_height is not None:
            sh = sim_height
        win_w = max(1, window_width)
        win_h = max(1, window_height)
        scale = min(win_w / sw, win_h / sh)
        dest_width = sw * scale
        dest_height = sh * scale
        return cls(
            window_width=win_w,
            window_height=win_h,
            sim_width=sw,
            sim_height=sh,
            scale=scale,
            dest_left=(win_w - dest_width) / 2,
            dest_bottom=(win_h - dest_height) / 2,
            dest_width=dest_width,
            dest_height=dest_height,
        )

    def map_arcade_point(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.dest_left + x * self.scale,
            self.dest_bottom + y * self.scale,
        )

    def map_arcade_lbwh(
        self, left: float, bottom: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        return (
            self.dest_left + left * self.scale,
            self.dest_bottom + bottom * self.scale,
            width * self.scale,
            height * self.scale,
        )

    def map_line_width(self, width: float) -> float:
        return max(1.0, width * self.scale)

    def map_radius(self, radius: float) -> float:
        return radius * self.scale

    def map_font_size(self, size: int) -> int:
        return max(10, int(round(size * self.scale)))

    def hud_anchor_top_left(self, margin_x: float = 10, margin_y: float = 10) -> tuple[float, float]:
        return (
            self.dest_left + margin_x,
            self.dest_bottom + self.dest_height - margin_y,
        )

    @property
    def letterbox_color(self) -> tuple[int, int, int]:
        return _LETTERBOX_COLOR

    @property
    def uses_gpu_viewport(self) -> bool:
        return (
            abs(self.scale - 1.0) > 1e-6
            or abs(self.dest_left) > 1e-6
            or abs(self.dest_bottom) > 1e-6
        )


@contextmanager
def gameplay_draw_surface(layout: DisplayLayout):
    """Letterbox + sim draw; supersampled FBO + linear upscale when scaled."""
    import arcade
    from pyglet.math import Mat4

    from pathwise.gameplay_framebuffer import shared_gameplay_surface

    try:
        window = arcade.get_window()
    except RuntimeError:
        yield
        return

    surface = shared_gameplay_surface()
    saved_viewport = window.viewport
    saved_projection = window.projection
    ww, wh = layout.window_width, layout.window_height

    if surface.needs_offscreen(layout):
        window.viewport = (0, 0, ww, wh)
        window.projection = Mat4.orthogonal_projection(0, ww, 0, wh, -8192, 8192)
        arcade.draw_lbwh_rectangle_filled(0, 0, ww, wh, layout.letterbox_color)
        with surface.draw_target(window, layout):
            try:
                yield
            finally:
                pass
        surface.blit_to_window(window, layout)
        window.viewport = saved_viewport
        window.projection = saved_projection
        return

    window.viewport = (0, 0, ww, wh)
    window.projection = Mat4.orthogonal_projection(0, ww, 0, wh, -8192, 8192)
    arcade.draw_lbwh_rectangle_filled(0, 0, ww, wh, layout.letterbox_color)
    dest_w = max(1, int(round(layout.dest_width)))
    dest_h = max(1, int(round(layout.dest_height)))
    window.viewport = (
        int(round(layout.dest_left)),
        int(round(layout.dest_bottom)),
        dest_w,
        dest_h,
    )
    window.projection = Mat4.orthogonal_projection(
        0, layout.sim_width, 0, layout.sim_height, -8192, 8192
    )
    try:
        yield
    finally:
        window.viewport = saved_viewport
        window.projection = saved_projection
