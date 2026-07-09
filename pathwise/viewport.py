"""Simulation viewport and display scaling for window aspect ratios."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from pathwise import commonUtils
from pathwise.geom import Rect
from pathwise.game_tuning import DEFAULT_TUNING

_FRAME_RECORD_VIEW_PAD = DEFAULT_TUNING.FRAME_RECORD_VIEW_PAD
_LETTERBOX_COLOR = (236, 244, 252)
SIM_BASE_WIDTH = commonUtils.WIDTH
SIM_BASE_HEIGHT = commonUtils.HEIGHT


def sim_size_for_window(window_width: int, window_height: int) -> tuple[int, int]:
    """Match sim aspect to the window; keep 600px vertical design resolution."""
    win_w = max(1, window_width)
    win_h = max(1, window_height)
    sim_h = SIM_BASE_HEIGHT
    sim_w = max(SIM_BASE_WIDTH, int(round(sim_h * win_w / win_h)))
    return sim_w, sim_h


def _resolve_window_size() -> tuple[int | None, int | None]:
    try:
        import arcade

        window = arcade.get_window()
        return int(window.width), int(window.height)
    except RuntimeError:
        return None, None


def sim_viewport_size(
    window_width: int | None = None,
    window_height: int | None = None,
) -> tuple[int, int]:
    if window_width is None or window_height is None:
        resolved_w, resolved_h = _resolve_window_size()
        if resolved_w is not None and resolved_h is not None:
            window_width, window_height = resolved_w, resolved_h
        else:
            return SIM_BASE_WIDTH, SIM_BASE_HEIGHT
    return sim_size_for_window(window_width, window_height)


def normalize_viewport_size(
    viewport_w: int | None = None, viewport_h: int | None = None
) -> tuple[int, int]:
    return sim_viewport_size(viewport_w, viewport_h)


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
    """Maps aspect-matched sim surface onto the full physical window."""

    window_width: int
    window_height: int
    sim_width: int
    sim_height: int
    scale_x: float
    scale_y: float
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
        win_w = max(1, window_width)
        win_h = max(1, window_height)
        if sim_width is not None and sim_height is not None:
            sw, sh = sim_width, sim_height
        else:
            sw, sh = sim_size_for_window(win_w, win_h)
        return cls(
            window_width=win_w,
            window_height=win_h,
            sim_width=sw,
            sim_height=sh,
            scale_x=win_w / sw,
            scale_y=win_h / sh,
            dest_left=0.0,
            dest_bottom=0.0,
            dest_width=float(win_w),
            dest_height=float(win_h),
        )

    @property
    def scale(self) -> float:
        return (self.scale_x + self.scale_y) / 2.0

    @property
    def display_match_scale(self) -> float:
        """Sim-to-screen scale so one sim unit maps to one screen pixel."""
        if (
            abs(self.scale_x - 1.0) < 1e-3
            and abs(self.scale_y - 1.0) < 1e-3
        ):
            return 1.0
        return max(self.scale_x, self.scale_y)

    def map_arcade_point(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.dest_left + x * self.scale_x,
            self.dest_bottom + y * self.scale_y,
        )

    def map_arcade_lbwh(
        self, left: float, bottom: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        return (
            self.dest_left + left * self.scale_x,
            self.dest_bottom + bottom * self.scale_y,
            width * self.scale_x,
            height * self.scale_y,
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
            abs(self.scale_x - 1.0) > 1e-6
            or abs(self.scale_y - 1.0) > 1e-6
            or self.dest_left > 1e-6
            or self.dest_bottom > 1e-6
        )

    def dest_pixel_size(self) -> tuple[int, int]:
        return (
            max(1, int(round(self.dest_width))),
            max(1, int(round(self.dest_height))),
        )

    def snapped_dest_rect(self) -> tuple[int, int, int, int]:
        width, height = self.dest_pixel_size()
        return (
            int(round(self.dest_left)),
            int(round(self.dest_bottom)),
            width,
            height,
        )


@contextmanager
def gameplay_draw_surface(layout: DisplayLayout):
    """Full-window sim draw; supersampled FBO + GPU upscale when scaled."""
    import arcade

    from pathwise.gameplay_framebuffer import shared_gameplay_surface
    from pathwise.projection_cache import screen_projection, sim_projection

    try:
        window = arcade.get_window()
    except RuntimeError:
        yield
        return

    surface = shared_gameplay_surface()
    saved_viewport = window.viewport
    saved_projection = window.projection
    ww, wh = layout.window_width, layout.window_height
    dest_covers_window = (
        layout.dest_left < 1
        and layout.dest_bottom < 1
        and abs(layout.dest_width - ww) < 2
        and abs(layout.dest_height - wh) < 2
    )

    if surface.needs_offscreen(layout):
        window.viewport = (0, 0, ww, wh)
        window.projection = screen_projection(ww, wh)
        if not dest_covers_window:
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
    window.projection = screen_projection(ww, wh)
    if not dest_covers_window:
        arcade.draw_lbwh_rectangle_filled(0, 0, ww, wh, layout.letterbox_color)
    dest_w = max(1, int(round(layout.dest_width)))
    dest_h = max(1, int(round(layout.dest_height)))
    window.viewport = (
        int(round(layout.dest_left)),
        int(round(layout.dest_bottom)),
        dest_w,
        dest_h,
    )
    window.projection = sim_projection(layout.sim_width, layout.sim_height)
    try:
        yield
    finally:
        window.viewport = saved_viewport
        window.projection = saved_projection
