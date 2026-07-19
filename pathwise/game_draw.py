"""Dynamic map overlays and HUD (Arcade draw, sim coordinates)."""

from __future__ import annotations

from dataclasses import dataclass

import arcade

from . import map_visuals
from . import sprites
from .entity_draw_batch import EntityDrawBatch
from .geom import Rect, rects_overlap
from .pathwise_render import draw_sim_rect_filled, sim_point_to_arcade
from .modifiers.weather_visuals import draw_weather_overlay
from .traffic_light_batch import shared_traffic_light_batch
from .viewport import DisplayLayout, gameplay_draw_surface

_entity_batch = EntityDrawBatch()

_HUD_MARGIN_X = 10
_HUD_MARGIN_TOP = 10
_HUD_LINE_STEP = 24
_HUD_FONT_SIZE = 18
_TIMER_FONT_SIZE = 14

_hud_texts: list[arcade.Text] = []
_traffic_timer_texts: list[arcade.Text] = []


@dataclass(frozen=True)
class TrafficTimerLabel:
    """Screen-space timer text drawn after the FBO blit."""

    x: float
    y: float
    text: str
    color: tuple[int, int, int]
    anchor_x: str
    anchor_y: str


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


def _timer_color_for_next(next_name: str) -> tuple[int, int, int]:
    if next_name == "red":
        return (160, 40, 40)
    if next_name == "yellow":
        return (170, 130, 30)
    if next_name == "green":
        return (35, 120, 55)
    return (30, 30, 30)


def draw_traffic_light_overlays(
    sim_height: int,
    road_states: list,
    camera_offset: tuple[int, int],
    light_green_duration: float,
    view_rect: Rect,
    *,
    draw_timer_bar: bool = True,
    layout: DisplayLayout | None = None,
) -> list[TrafficTimerLabel]:
    """Draw dynamic bulbs + timer bars in sim space; return timer labels for screen HUD."""
    from pathwise.modifiers import highway, lawless

    if not lawless.signals_enabled() or not highway.signals_enabled():
        return []

    cam_x, cam_y = camera_offset
    timer_labels: list[TrafficTimerLabel] = []
    visible = _visible_traffic_light_states(road_states, view_rect)

    shared_traffic_light_batch().draw_bulbs(
        road_states,
        camera_offset,
        sim_height,
        view_rect,
        housing_for_state=map_visuals.traffic_housing_rect,
        visible_states=visible,
    )

    for state, housing, _approach in visible:
        if not draw_timer_bar:
            continue

        remaining = max(0.0, state.get("seconds_to_change", 0))
        next_name = state.get("next_light", "green")
        timer_label = f"{remaining:.1f}s"
        timer_color = _timer_color_for_next(next_name)

        if state["direction"] == "vertical":
            timer_x, timer_y = sim_point_to_arcade(
                housing.centerx - cam_x, housing.bottom + 4 - cam_y, sim_height
            )
            anchor_x, anchor_y = "center", "bottom"
            bar_rect = Rect(housing.left, housing.bottom + 2, housing.width, 4)
        else:
            timer_x, timer_y = sim_point_to_arcade(
                housing.right + 6 - cam_x, housing.centery - cam_y, sim_height
            )
            anchor_x, anchor_y = "left", "center"
            bar_rect = Rect(housing.right + 2, housing.top, 4, housing.height)

        draw_sim_rect_filled(bar_rect, camera_offset, sim_height, (200, 200, 200))
        fill_frac = min(1.0, remaining / max(light_green_duration, 0.1))
        fill = bar_rect.copy()
        if state["direction"] == "vertical":
            fill.width = max(1, int(bar_rect.width * fill_frac))
        else:
            fill.height = max(1, int(bar_rect.height * fill_frac))
        draw_sim_rect_filled(fill, camera_offset, sim_height, (70, 110, 155))

        if layout is not None:
            screen_x, screen_y = layout.map_arcade_point(timer_x, timer_y)
            timer_labels.append(
                TrafficTimerLabel(
                    screen_x,
                    screen_y,
                    timer_label,
                    timer_color,
                    anchor_x,
                    anchor_y,
                )
            )
        else:
            arcade.draw_text(
                timer_label,
                timer_x,
                timer_y,
                timer_color,
                _TIMER_FONT_SIZE,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
            )

    return timer_labels


def _draw_hud_sim_space(sim_height: int, hud_lines: list[str]) -> None:
    for idx, line in enumerate(hud_lines):
        arcade.draw_text(
            line,
            _HUD_MARGIN_X,
            sim_height - _HUD_MARGIN_TOP - idx * _HUD_LINE_STEP,
            (20, 20, 20),
            _HUD_FONT_SIZE,
            anchor_x="left",
            anchor_y="top",
        )


_screen_projection_key: tuple[int, int] | None = None


def _ensure_screen_projection(layout: DisplayLayout) -> None:
    global _screen_projection_key
    window = arcade.get_window()
    window.use()
    ww, wh = layout.window_width, layout.window_height
    key = (ww, wh)
    if _screen_projection_key != key:
        window.viewport = (0, 0, ww, wh)
        from pathwise.projection_cache import screen_projection

        window.projection = screen_projection(ww, wh)
        _screen_projection_key = key
    else:
        window.viewport = (0, 0, ww, wh)


def _draw_hud_screen_space(layout: DisplayLayout, hud_lines: list[str]) -> None:
    anchor_x, anchor_y = layout.hud_anchor_top_left(_HUD_MARGIN_X, _HUD_MARGIN_TOP)
    font_size = layout.map_font_size(_HUD_FONT_SIZE)
    line_step = layout.map_line_width(_HUD_LINE_STEP)
    for idx, line in enumerate(hud_lines):
        hud_text = _pooled_text(
            _hud_texts,
            idx,
            anchor_x="left",
            anchor_y="top",
            font_size=font_size,
            default_color=(20, 20, 20),
        )
        hud_text.text = line
        hud_text.x = anchor_x
        hud_text.y = anchor_y - idx * line_step
        hud_text.font_size = font_size
        hud_text.draw()


def _draw_traffic_timers_screen_space(labels: list[TrafficTimerLabel]) -> None:
    for idx, label in enumerate(labels):
        timer_text = _pooled_text(
            _traffic_timer_texts,
            idx,
            anchor_x=label.anchor_x,
            anchor_y=label.anchor_y,
            font_size=_TIMER_FONT_SIZE,
            default_color=label.color,
        )
        timer_text.text = label.text
        timer_text.x = label.x
        timer_text.y = label.y
        timer_text.color = label.color
        timer_text.draw()


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
    draw_weather: bool = False,
) -> None:
    layout = display_layout or DisplayLayout.fit_window(window_width, window_height)
    sim_height = layout.sim_height
    sim_width = layout.sim_width

    timer_labels: list[TrafficTimerLabel] = []
    baked_layer = getattr(current_map, "baked_layer", None)
    skip_grass = baked_layer is not None and getattr(baked_layer, "tiles", None)

    with gameplay_draw_surface(layout):
        if not skip_grass:
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

        timer_labels = draw_traffic_light_overlays(
            sim_height,
            road_states,
            camera_offset,
            light_green_duration,
            view_rect,
            draw_timer_bar=draw_traffic_timer_bar,
            layout=layout if layout.uses_gpu_viewport else None,
        )

        cam_x, cam_y = camera_offset
        for wall in wall_rects:
            if rects_overlap(view_rect, wall):
                draw_sim_rect_filled(wall, camera_offset, sim_height, (40, 40, 40))

        _entity_batch.draw_entities(draw_sprites, camera_offset, sim_height)

        for entity in draw_sprites:
            honk_fn = getattr(entity, "is_honking", None)
            if honk_fn and honk_fn(elapsed):
                sprites.draw_honk_bubble(sim_height, entity.rect, (cam_x, cam_y))

        slip_fn = getattr(player, "is_slip_stunned", None)
        if slip_fn and slip_fn(elapsed):
            sprites.draw_slip_trip_message(sim_height, player.rect, (cam_x, cam_y))

        from pathwise.modifiers import time_pressure as _time_pressure

        bonus_text = _time_pressure.active_bonus_popup_text(elapsed)
        if bonus_text:
            sprites.draw_time_bonus_popup(
                sim_height, player.rect, (cam_x, cam_y), bonus_text
            )

        if draw_weather:
            draw_weather_overlay(
                sim_width=sim_width,
                sim_height=sim_height,
                view_rect=view_rect,
                camera_offset=camera_offset,
                elapsed=elapsed,
            )

        if not layout.uses_gpu_viewport:
            _draw_hud_sim_space(sim_height, hud_lines)

    if layout.uses_gpu_viewport:
        _ensure_screen_projection(layout)
        _draw_hud_screen_space(layout, hud_lines)
        _draw_traffic_timers_screen_space(timer_labels)
