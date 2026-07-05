"""Dynamic map overlays and HUD (Arcade draw, sim coordinates)."""

from __future__ import annotations

import arcade

from . import map_visuals
from . import sprites
from .traffic_signal_layout import bulb_positions as _signal_bulb_positions
from .entity_draw_batch import EntityDrawBatch
from .geom import Rect, rects_overlap
from .pathwise_render import (
    draw_sim_circle_filled_world,
    draw_sim_rect_filled,
    draw_sim_rect_outline,
    sim_point_to_arcade,
)
from .viewport import DisplayLayout, gameplay_draw_surface

_entity_batch = EntityDrawBatch()

_HUD_MARGIN_X = 10
_HUD_MARGIN_TOP = 10
_HUD_LINE_STEP = 24
_HUD_FONT_SIZE = 18


def _pooled_text(
    pool: list[arcade.Text],
    index: int,
    *,
    anchor_x: str,
    anchor_y: str,
    font_size: int,
    default_color,
) -> arcade.Text:
    while len(pool) <= index:
        pool.append(
            arcade.Text(
                "",
                0,
                0,
                default_color,
                font_size,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
            )
        )
    return pool[index]


_hud_texts: list[arcade.Text] = []
_traffic_timer_texts: list[arcade.Text] = []

_SIGNAL_HOUSING_FILL = (25, 25, 25)
_SIGNAL_HOUSING_OUTLINE = (100, 100, 105)
_OFF_BULB_COLORS = ((120, 35, 35), (120, 100, 30), (35, 100, 35))
_ON_BULB_COLORS = ((220, 30, 30), (235, 185, 40), (40, 200, 40))


def _bulb_positions_world(
    housing: Rect, direction: str, approach: str
) -> list[tuple[int, int]]:
    return _signal_bulb_positions(housing, direction, approach)


def _crosswalk_key(crosswalk: Rect) -> tuple[int, int, int, int]:
    return (crosswalk.x, crosswalk.y, crosswalk.w, crosswalk.h)


def _visible_traffic_light_states(
    road_states: list,
    view_rect: Rect,
    *,
    cull_pad: int = 80,
) -> list:
    """Return every road_state whose signal housing overlaps the view."""
    visible: list = []
    seen_crosswalk: set[tuple[int, int, int, int]] = set()
    for state in road_states:
        crosswalk = state["crosswalk"]
        key = _crosswalk_key(crosswalk)
        if key in seen_crosswalk:
            continue
        approach = state.get("approach", "west")
        housing = map_visuals.traffic_housing_rect(
            crosswalk, state["direction"], approach
        )
        if not rects_overlap(view_rect, housing.inflate(cull_pad, cull_pad)):
            continue
        seen_crosswalk.add(key)
        visible.append((state, housing, approach))
    return visible


def draw_traffic_light_overlays(
    sim_height: int,
    road_states: list,
    camera_offset: tuple[int, int],
    light_green_duration: float,
    view_rect: Rect,
    *,
    draw_timer_bar: bool = True,
) -> None:
    cam_x, cam_y = camera_offset
    timer_index = 0

    for state, housing, approach in _visible_traffic_light_states(road_states, view_rect):
        draw_sim_rect_filled(
            housing, camera_offset, sim_height, _SIGNAL_HOUSING_FILL
        )
        draw_sim_rect_outline(
            housing,
            camera_offset,
            sim_height,
            _SIGNAL_HOUSING_OUTLINE,
            border_width=2,
        )

        red_on = state["light_state"] == "red"
        yellow_on = state["light_state"] == "yellow"
        green_on = state["light_state"] == "green"
        bulb_colors = [
            _ON_BULB_COLORS[0] if red_on else _OFF_BULB_COLORS[0],
            _ON_BULB_COLORS[1] if yellow_on else _OFF_BULB_COLORS[1],
            _ON_BULB_COLORS[2] if green_on else _OFF_BULB_COLORS[2],
        ]
        for pos, color in zip(
            _bulb_positions_world(housing, state["direction"], approach), bulb_colors
        ):
            draw_sim_circle_filled_world(
                pos[0], pos[1], camera_offset, sim_height, 6, color
            )

        if not draw_timer_bar:
            continue

        remaining = max(0.0, state.get("seconds_to_change", 0))
        next_name = state.get("next_light", "green")
        timer_label = f"{remaining:.1f}s"
        timer_color = (30, 30, 30)
        if next_name == "red":
            timer_color = (160, 40, 40)
        elif next_name == "yellow":
            timer_color = (170, 130, 30)
        elif next_name == "green":
            timer_color = (35, 120, 55)

        if state["direction"] == "vertical":
            timer_x, timer_y = sim_point_to_arcade(
                housing.centerx - cam_x, housing.bottom + 4 - cam_y, sim_height
            )
            anchor_x, anchor_y = "center", "bottom"
        else:
            timer_x, timer_y = sim_point_to_arcade(
                housing.right + 6 - cam_x, housing.centery - cam_y, sim_height
            )
            anchor_x, anchor_y = "left", "center"

        if state["direction"] == "vertical":
            bar_rect = Rect(housing.left, housing.bottom + 2, housing.width, 4)
        else:
            bar_rect = Rect(housing.right + 2, housing.top, 4, housing.height)
        draw_sim_rect_filled(bar_rect, camera_offset, sim_height, (200, 200, 200))
        fill_frac = min(1.0, remaining / max(light_green_duration, 0.1))
        fill = bar_rect.copy()
        if state["direction"] == "vertical":
            fill.width = max(1, int(bar_rect.width * fill_frac))
        else:
            fill.height = max(1, int(bar_rect.height * fill_frac))
        fill_color = (70, 110, 155)
        draw_sim_rect_filled(fill, camera_offset, sim_height, fill_color)
        timer_text = _pooled_text(
            _traffic_timer_texts,
            timer_index,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            font_size=14,
            default_color=timer_color,
        )
        timer_text.text = timer_label
        timer_text.x = timer_x
        timer_text.y = timer_y
        timer_text.color = timer_color
        timer_text.draw()
        timer_index += 1


def draw_round_scene(
    window_width: int,
    window_height: int,
    *,
    current_map,
    player,
    world_bounds,
    road_states,
    wall_rects,
    draw_sprites,
    record_cars,
    camera_offset,
    view_rect,
    elapsed: float,
    hud_lines: list[str],
    light_green_duration: float,
    draw_traffic_timer_bar: bool = True,
    display_layout: DisplayLayout | None = None,
) -> None:
    layout = display_layout or DisplayLayout.fit_window(window_width, window_height)
    sim_height = layout.sim_height
    sim_width = layout.sim_width

    with gameplay_draw_surface(layout):
        arcade.draw_lbwh_rectangle_filled(
            0, 0, sim_width, sim_height, map_visuals.GRASS_BASE
        )

        city_blocks = getattr(current_map, "city_blocks", None)
        decorations = getattr(current_map, "decorations", None)
        current_map.draw(
            sim_height,
            camera_offset,
            player,
            city_blocks=city_blocks,
            world_bounds=world_bounds,
            decorations=decorations,
            view_rect=view_rect,
        )

        draw_traffic_light_overlays(
            sim_height,
            road_states,
            camera_offset,
            light_green_duration,
            view_rect,
            draw_timer_bar=draw_traffic_timer_bar,
        )

        cam_x, cam_y = camera_offset
        for wall in wall_rects:
            if not rects_overlap(view_rect, wall):
                continue
            draw_sim_rect_filled(wall, camera_offset, sim_height, (40, 40, 40))

        _entity_batch.draw_entities(draw_sprites, camera_offset, sim_height)

        for entity in draw_sprites:
            honk_fn = getattr(entity, "is_honking", None)
            if honk_fn and honk_fn(elapsed):
                sprites.draw_honk_bubble(sim_height, entity.rect, (cam_x, cam_y))

        for idx, line in enumerate(hud_lines):
            hud_text = _pooled_text(
                _hud_texts,
                idx,
                anchor_x="left",
                anchor_y="top",
                font_size=_HUD_FONT_SIZE,
                default_color=(20, 20, 20),
            )
            hud_text.text = line
            hud_text.x = _HUD_MARGIN_X
            hud_text.y = sim_height - _HUD_MARGIN_TOP - idx * _HUD_LINE_STEP
            hud_text.draw()
