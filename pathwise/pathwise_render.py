"""Simulation (top-left y-down) to Arcade (y-up) coordinate helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .geom import Rect

if TYPE_CHECKING:
    from .viewport import DisplayLayout


def sim_y_to_arcade(sim_y: float, sim_height: int) -> float:
    return sim_height - sim_y


def sim_point_to_arcade(
    sim_x: float,
    sim_y: float,
    sim_height: int,
    layout: DisplayLayout | None = None,
) -> tuple[float, float]:
    ax, ay = sim_x, sim_y_to_arcade(sim_y, sim_height)
    if layout is None:
        return ax, ay
    return layout.map_arcade_point(ax, ay)


def sim_rect_to_arcade_lbwh(
    sim_left: float,
    sim_top: float,
    width: float,
    height: float,
    sim_height: int,
    layout: DisplayLayout | None = None,
) -> tuple[float, float, float, float]:
    """Return left, bottom, width, height for arcade.draw_lbwh_rectangle_*."""
    bottom = sim_y_to_arcade(sim_top + height, sim_height)
    lbwh = sim_left, bottom, width, height
    if layout is None:
        return lbwh
    return layout.map_arcade_lbwh(*lbwh)


def sim_rect_center_to_arcade(
    rect: Rect,
    camera_offset: tuple[int, int],
    sim_height: int,
    layout: DisplayLayout | None = None,
) -> tuple[float, float]:
    sx = rect.centerx - camera_offset[0]
    sy = rect.centery - camera_offset[1]
    return sim_point_to_arcade(sx, sy, sim_height, layout)


def draw_sim_rect_filled(
    rect: Rect,
    camera_offset: tuple[int, int],
    sim_height: int,
    color,
    layout: DisplayLayout | None = None,
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, sim_height, layout
    )
    arcade.draw_lbwh_rectangle_filled(left, bottom, w, h, color)


def draw_sim_rect_outline(
    rect: Rect,
    camera_offset: tuple[int, int],
    sim_height: int,
    color,
    border_width: int = 1,
    layout: DisplayLayout | None = None,
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, sim_height, layout
    )
    line_w = layout.map_line_width(border_width) if layout else border_width
    arcade.draw_lbwh_rectangle_outline(left, bottom, w, h, color, line_w)


def draw_sim_texture_rect(
    rect: Rect,
    texture,
    camera_offset: tuple[int, int],
    sim_height: int,
    layout: DisplayLayout | None = None,
) -> None:
    import arcade

    shifted = rect.move(-camera_offset[0], -camera_offset[1])
    left, bottom, w, h = sim_rect_to_arcade_lbwh(
        shifted.left, shifted.top, shifted.width, shifted.height, sim_height, layout
    )
    arcade.draw_texture_rect(texture, arcade.LBWH(left, bottom, w, h))


def draw_sprite_asset(
    asset,
    rect: Rect,
    camera_offset: tuple[int, int],
    sim_height: int,
    layout: DisplayLayout | None = None,
) -> None:
    draw_sim_texture_rect(
        rect,
        asset.texture,
        camera_offset,
        sim_height,
        layout,
    )


def draw_sim_circle_filled(
    sim_x: float,
    sim_y: float,
    sim_height: int,
    radius: float,
    color,
    layout: DisplayLayout | None = None,
) -> None:
    """Draw at viewport sim coordinates (already camera-shifted)."""
    import arcade

    ax, ay = sim_point_to_arcade(sim_x, sim_y, sim_height, layout)
    r = layout.map_radius(radius) if layout else radius
    arcade.draw_circle_filled(ax, ay, r, color)


def draw_sim_circle_filled_world(
    world_x: float,
    world_y: float,
    camera_offset: tuple[int, int],
    sim_height: int,
    radius: float,
    color,
    layout: DisplayLayout | None = None,
) -> None:
    """Draw at world sim coordinates (camera applied here)."""
    draw_sim_circle_filled(
        world_x - camera_offset[0],
        world_y - camera_offset[1],
        sim_height,
        radius,
        color,
        layout,
    )
