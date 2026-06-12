"""Simulation (top-left y-down) to Arcade (y-up) coordinate helpers."""

from __future__ import annotations

from .geom import Rect


def sim_y_to_arcade(sim_y: float, window_height: int) -> float:
    return window_height - sim_y


def sim_point_to_arcade(sim_x: float, sim_y: float, window_height: int) -> tuple[float, float]:
    return sim_x, sim_y_to_arcade(sim_y, window_height)


def sim_rect_to_arcade_lbwh(
    sim_left: float, sim_top: float, width: float, height: float, window_height: int
) -> tuple[float, float, float, float]:
    """Return left, bottom, width, height for arcade.draw_lbwh_rectangle_*."""
    bottom = sim_y_to_arcade(sim_top + height, window_height)
    return sim_left, bottom, width, height


def sim_rect_center_to_arcade(
    rect: Rect, camera_offset: tuple[int, int], window_height: int
) -> tuple[float, float]:
    sx = rect.centerx - camera_offset[0]
    sy = rect.centery - camera_offset[1]
    return sim_point_to_arcade(sx, sy, window_height)


def draw_sim_rect_filled(
    rect: Rect, camera_offset: tuple[int, int], window_height: int, color
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, window_height
    )
    arcade.draw_lbwh_rectangle_filled(left, bottom, w, h, color)


def draw_sim_rect_outline(
    rect: Rect,
    camera_offset: tuple[int, int],
    window_height: int,
    color,
    border_width: int = 1,
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, window_height
    )
    arcade.draw_lbwh_rectangle_outline(left, bottom, w, h, color, border_width)


def draw_sim_texture_rect(
    rect: Rect,
    texture,
    camera_offset: tuple[int, int],
    window_height: int,
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, window_height
    )
    arcade.draw_texture_rect(texture, arcade.LBWH(left, bottom, w, h))


def draw_sprite_asset(
    asset,
    rect: Rect,
    camera_offset: tuple[int, int],
    window_height: int,
) -> None:
    draw_sim_texture_rect(
        rect,
        asset.texture,
        camera_offset,
        window_height,
    )


def draw_sim_circle_filled(
    sim_x: float, sim_y: float, window_height: int, radius: float, color
) -> None:
    """Draw at viewport sim coordinates (already camera-shifted)."""
    import arcade

    ax, ay = sim_point_to_arcade(sim_x, sim_y, window_height)
    arcade.draw_circle_filled(ax, ay, radius, color)


def draw_sim_circle_filled_world(
    world_x: float,
    world_y: float,
    camera_offset: tuple[int, int],
    window_height: int,
    radius: float,
    color,
) -> None:
    """Draw at world sim coordinates (camera applied here)."""
    draw_sim_circle_filled(
        world_x - camera_offset[0],
        world_y - camera_offset[1],
        window_height,
        radius,
        color,
    )
