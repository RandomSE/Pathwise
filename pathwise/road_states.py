"""Traffic-light road states: build, update, and car routing."""

from __future__ import annotations

from analytics.traffic_lights import (
    arm_light_state_at,
    perpendicular_phase_offsets,
    seconds_to_change_arm,
)
from map_generation.lane_geometry import lane_center_xy
from pathwise import map_visuals
from pathwise import sprites
from pathwise.geom import Rect, clip_rect, collide
from pathwise.sim_constants import (
    CROSSWALK_THICKNESS,
    INTERSECTION_GAP_MIN,
    RED_SIGNAL_BRAKE_DIST,
)
from pathwise.traffic_signal_layout import (
    APPROACH_EAST,
    APPROACH_NORTH,
    APPROACH_SOUTH,
    APPROACH_WEST,
    approach_sign_rect,
)



def _game():
    import main
    return main

def update_light_timers(road_states, elapsed):
    m = _game()
    from pathwise.modifiers import highway, lawless

    if not lawless.signals_enabled() or not highway.signals_enabled():
        for state in road_states:
            state["light_state"] = "off"
            state["seconds_to_change"] = 0.0
            state["next_light"] = "off"
            state["turn_light_state"] = "off"
            state["turn_seconds_to_change"] = 0.0
            state["next_turn_light"] = "off"
        return

    for state in road_states:
        arm_vertical = state["direction"] == "vertical"
        light, secs, nxt = seconds_to_change_arm(
            elapsed,
            state["phase_offset"],
            arm_vertical=arm_vertical,
            green_s=m._LIGHT_GREEN,
            yellow_s=m._LIGHT_YELLOW,
        )
        state["light_state"] = light
        state["seconds_to_change"] = secs
        state["next_light"] = nxt
        state["turn_light_state"] = "red"
        state["turn_seconds_to_change"] = secs
        state["next_turn_light"] = nxt


def serialize_lights_for_frame(road_states):
    from pathwise.modifiers import highway, lawless

    enabled = lawless.signals_enabled() and highway.signals_enabled()
    return [
        {
            "s": state["light_state"],
            "ts": state.get("turn_light_state", "red"),
            "in": round(state.get("seconds_to_change", 0), 1),
            "tin": round(state.get("turn_seconds_to_change", 0), 1),
            "next": state.get("next_light", "green"),
            "tnext": state.get("next_turn_light", "green"),
            "enabled": enabled,
        }
        for state in road_states
    ]


def build_road_states(roads):
    from pathwise.modifiers import highway

    if not highway.crosswalks_enabled():
        return []

    m = _game()
    road_id_to_index = {id(road): idx for idx, road in enumerate(roads)}

    def add_state(
        collector, road, direction, crosswalk, sign_rect, phase_offset, approach
    ):
        collector.append(
            {
                "road_rect": road.rect,
                "approach_rect": road.rect.inflate(180, 180),
                "direction": direction,
                "approach": approach,
                "crosswalk": crosswalk,
                "stop_axis": crosswalk.centerx if direction == "vertical" else crosswalk.centery,
                "sign_rect": sign_rect,
                "phase_offset": phase_offset,
                "road_index": road_id_to_index[id(road)],
                "light_state": "green",
                "turn_light_state": "red",
                "turn_seconds_to_change": 0.0,
                "next_turn_light": "green",
                "player_waiting": False,
                "stop_active": True,
            }
        )

    road_states = []
    cycle = m._LIGHT_GREEN + m._LIGHT_YELLOW + m._LIGHT_RED
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    intersection_by_road = {id(road): [] for road in roads}

    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            intersection_rect = clip_rect(v_road.rect, h_road.rect)
            if intersection_rect.width <= 0 or intersection_rect.height <= 0:
                continue
            intersection_by_road[id(v_road)].append(intersection_rect)
            intersection_by_road[id(h_road)].append(intersection_rect)

            # Keep all vertical approaches globally aligned and all horizontal
            # approaches aligned to the opposite phase for deterministic flow.
            v_phase, h_phase = perpendicular_phase_offsets(
                0.0, m._LIGHT_GREEN, m._LIGHT_YELLOW
            )

            # Crossing across the horizontal road (left and right approaches).
            left_space = intersection_rect.left - v_road.rect.left
            right_space = v_road.rect.right - intersection_rect.right
            left_thickness = min(CROSSWALK_THICKNESS, max(0, left_space - INTERSECTION_GAP_MIN - 2))
            right_thickness = min(CROSSWALK_THICKNESS, max(0, right_space - INTERSECTION_GAP_MIN - 2))
            if left_thickness >= 4:
                left_x = intersection_rect.left - INTERSECTION_GAP_MIN - left_thickness
                left_crosswalk = Rect(left_x, v_road.rect.top, left_thickness, v_road.rect.height)
                left_housing = map_visuals.traffic_housing_rect(
                    left_crosswalk, "vertical", APPROACH_WEST
                )
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    left_crosswalk,
                    approach_sign_rect(left_housing, "vertical", APPROACH_WEST),
                    v_phase,
                    APPROACH_WEST,
                )
            if right_thickness >= 4:
                right_x = intersection_rect.right + INTERSECTION_GAP_MIN
                right_crosswalk = Rect(right_x, v_road.rect.top, right_thickness, v_road.rect.height)
                right_housing = map_visuals.traffic_housing_rect(
                    right_crosswalk, "vertical", APPROACH_EAST
                )
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    right_crosswalk,
                    approach_sign_rect(right_housing, "vertical", APPROACH_EAST),
                    v_phase,
                    APPROACH_EAST,
                )

            # Crossing across the vertical road (top and bottom approaches).
            top_space = intersection_rect.top - h_road.rect.top
            bottom_space = h_road.rect.bottom - intersection_rect.bottom
            top_thickness = min(CROSSWALK_THICKNESS, max(0, top_space - INTERSECTION_GAP_MIN - 2))
            bottom_thickness = min(CROSSWALK_THICKNESS, max(0, bottom_space - INTERSECTION_GAP_MIN - 2))
            if top_thickness >= 4:
                top_y = intersection_rect.top - INTERSECTION_GAP_MIN - top_thickness
                top_crosswalk = Rect(h_road.rect.left, top_y, h_road.rect.width, top_thickness)
                top_housing = map_visuals.traffic_housing_rect(
                    top_crosswalk, "horizontal", APPROACH_NORTH
                )
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    top_crosswalk,
                    approach_sign_rect(top_housing, "horizontal", APPROACH_NORTH),
                    h_phase,
                    APPROACH_NORTH,
                )
            if bottom_thickness >= 4:
                bottom_y = intersection_rect.bottom + INTERSECTION_GAP_MIN
                bottom_crosswalk = Rect(h_road.rect.left, bottom_y, h_road.rect.width, bottom_thickness)
                bottom_housing = map_visuals.traffic_housing_rect(
                    bottom_crosswalk, "horizontal", APPROACH_SOUTH
                )
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    bottom_crosswalk,
                    approach_sign_rect(bottom_housing, "horizontal", APPROACH_SOUTH),
                    h_phase,
                    APPROACH_SOUTH,
                )

    # Roads without intersections get one center crossing.
    for idx, road in enumerate(roads):
        if intersection_by_road[id(road)]:
            continue
        if road.direction == "vertical":
            phase_offset = 0.0
        else:
            phase_offset = (m._LIGHT_GREEN + m._LIGHT_YELLOW) % cycle
        if road.direction == "vertical":
            crosswalk = Rect(road.rect.centerx - CROSSWALK_THICKNESS // 2, road.rect.top, CROSSWALK_THICKNESS, road.rect.height)
            approach = APPROACH_WEST
            housing = map_visuals.traffic_housing_rect(crosswalk, "vertical", approach)
            sign_rect = approach_sign_rect(housing, "vertical", approach)
        else:
            crosswalk = Rect(road.rect.left, road.rect.centery - CROSSWALK_THICKNESS // 2, road.rect.width, CROSSWALK_THICKNESS)
            approach = APPROACH_NORTH
            housing = map_visuals.traffic_housing_rect(crosswalk, "horizontal", approach)
            sign_rect = approach_sign_rect(housing, "horizontal", approach)
        add_state(
            road_states, road, road.direction, crosswalk, sign_rect, phase_offset, approach
        )

    return road_states


def _build_road_states_by_index(road_states: list, road_count: int) -> list[list]:
    grouped = [[] for _ in range(road_count)]
    for state in road_states:
        road_index = state.get("road_index")
        if road_index is None or road_index < 0 or road_index >= road_count:
            continue
        grouped[road_index].append(state)
    return grouped


def _car_approach_label(car) -> str:
    vertical = bool(getattr(car, "vertical", False))
    direction = int(getattr(car, "direction", 1))
    if vertical:
        return APPROACH_NORTH if direction > 0 else APPROACH_SOUTH
    return APPROACH_WEST if direction > 0 else APPROACH_EAST


def _oriented_road_states_for_car(car) -> list:
    m = _game()
    return m.road_states_h if car.vertical else m.road_states_v


def _road_states_for_car(car, fallback_states: list) -> list:
    m = _game()
    oriented = fallback_states
    if car.road_index is None:
        return oriented
    if car.road_index < 0 or car.road_index >= len(m.road_states_by_index):
        return oriented
    tagged = m.road_states_by_index[car.road_index]
    if not tagged:
        return oriented
    if not hasattr(car, "_in_crossing_lane"):
        return tagged
    approach_label = _car_approach_label(car)
    orient = "horizontal" if getattr(car, "vertical", False) else "vertical"
    extra: list = []
    seen = {id(state) for state in tagged}
    brake = RED_SIGNAL_BRAKE_DIST * 2
    for state in oriented:
        if id(state) in seen:
            continue
        if state.get("direction") != orient or state.get("approach") != approach_label:
            continue
        crosswalk = state["crosswalk"]
        if not car._in_crossing_lane(crosswalk):
            continue
        stop_axis = car._signal_stop_axis(crosswalk)
        if abs(car._distance_to_signal_stop(stop_axis)) > brake:
            continue
        seen.add(id(state))
        extra.append(state)
    if extra:
        return tagged + extra
    return tagged


def build_intersection_zones(roads):
    zones = []
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            zone = clip_rect(v_road.rect, h_road.rect)
            if zone.width > 0 and zone.height > 0:
                zones.append(zone)
    return zones


def lane_center_for_road(road, direction, vertical):
    cx, cy = lane_center_xy(road, direction)
    if road.direction == "vertical":
        return cy
    return cx


def get_light_state(elapsed_seconds, direction: str = "vertical", phase_offset: float = 0.0):
    m = _game()
    return arm_light_state_at(
        elapsed_seconds,
        phase_offset,
        arm_vertical=(direction == "vertical"),
        green_s=m._LIGHT_GREEN,
        yellow_s=m._LIGHT_YELLOW,
    )


def get_player_light_state(player_rect, states):
    body = sprites.player_body_hitbox(player_rect)
    for state in states:
        if collide(state["crosswalk"], body):
            return state["light_state"]
    return "none"
