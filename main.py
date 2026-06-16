import math
import os
import random
import json
import time
from dataclasses import dataclass
from pathwise import commonUtils
from pathwise import map_generator
from pathwise import map_visuals
from pathwise import pre_game
from pathwise.traffic_signal_layout import (
    APPROACH_EAST,
    APPROACH_NORTH,
    APPROACH_SOUTH,
    APPROACH_WEST,
    approach_sign_rect,
)
from pathwise import sprites
from pathwise.entity_group import Entity, EntityGroup
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState, key_labels_from_state
from pathwise.session_seed import resolve_session_seed
from map_generation.difficulty import DifficultyProfile
from map_generation.intersection_routing import (
    choose_exit,
    pick_turn_side,
    pivot_center_at_intersection,
    travel_vector,
    turn_side_from_exit,
)
from map_generation.turn_clearance import bezier_point as _bezier_xy
from map_generation.turn_clearance import corridor_bounds as _turn_corridor_bounds
from map_generation.turn_clearance import sample_bezier as _sample_bezier_xy
from map_generation.lane_geometry import lane_center_xy
from map_generation.traffic_schedule import (
    INTERSECTION_SPAWN_PAD,
    MIN_ALONG_GAP,
    RECT_COLLIDE_PAD,
    TrafficSpawn,
    build_intersection_rects,
    edge_spawn_lane_allowed,
    generate_traffic_schedule,
    lane_spawn_allowed,
    PHASE_ONGOING,
    pose_overlaps_intersection_rects,
    spawn_poses_for_event,
)
from analytics.decision_logger import DecisionLogger
from analytics.archetype_scoring import score_session
from analytics.dashboard import build_dashboard_html
from analytics.map_snapshot import serialize_map_layout
from analytics.frame_recorder import FrameRecorder
from analytics.traffic_lights import (
    cycle_durations,
    light_state_at,
    perpendicular_phase_offsets,
    protected_turn_light_at,
)
from analytics.car_diagnostics import car_diagnostics
from analytics.perf_profiler import PerfProfiler, perf_profile_enabled
from pathwise.geom import Rect, collide, clip_rect, contains_rect, rect_overlap_area, rects_overlap

from pathwise.sim_constants import *  # noqa: F403
from pathwise.game_tuning import install_for_round
import pathwise.sim_constants as sim_tuning
from pathwise.car import (
    Car,
    CarSpatialIndex,
    CarSpawnOrigin,
    RespawnRequest,
    set_car_removed_callback,
    set_intersection_zones_shell,
    set_traffic_map_seed,
    _build_lane_buckets,
    _frame_car_list_scratch,
    _frame_car_spatial,
    _frame_draw_sprites_scratch,
    _frame_lane_scratch,
    _frame_nearby_scratch,
    _frame_player_car_scratch,
    _lane_peers_for,
    _resolve_all_shell_overlaps,
)
from pathwise.pedestrian import Pedestrian
from pathwise import traffic_spawn

ENABLE_PERF_PROFILE = perf_profile_enabled()
perf_profiler = PerfProfiler(enabled=ENABLE_PERF_PROFILE)

# Backward-compatible spawn API (tests import from main).
_city_block_rects_from = traffic_spawn._city_block_rects_from
_spawn_car_from_event = traffic_spawn._spawn_car_from_event
_spawn_probe_geometry = traffic_spawn._spawn_probe_geometry
_spawn_probe_pose_valid = traffic_spawn._spawn_probe_pose_valid
_spawn_probe_blocked = traffic_spawn._spawn_probe_blocked
_car_spawn_pose_valid = traffic_spawn._car_spawn_pose_valid
_spawn_forward_lane_clear = traffic_spawn._spawn_forward_lane_clear
_blocks_player_spawn_shell = traffic_spawn._blocks_player_spawn_shell
_process_car_respawns = traffic_spawn._process_car_respawns
_process_traffic_spawns_through_frame = traffic_spawn._process_traffic_spawns_through_frame
_queue_car_respawn = traffic_spawn._queue_car_respawn


def _sync_spawn_state_from_module() -> None:
    """Mirror traffic_spawn module state onto main for legacy callers."""
    global traffic_schedule, traffic_spawn_cursor, traffic_spawn_retry
    global traffic_respawn_pending, traffic_respawn_event_id
    traffic_schedule = traffic_spawn.traffic_schedule
    traffic_spawn_cursor = traffic_spawn.traffic_spawn_cursor
    traffic_spawn_retry = traffic_spawn.traffic_spawn_retry
    traffic_respawn_pending = traffic_spawn.traffic_respawn_pending
    traffic_respawn_event_id = traffic_spawn.traffic_respawn_event_id


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_angle_deg(a: float, b: float, t: float) -> float:
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


# --- Init (display/fonts owned by PathwiseWindow) ---


def player_on_car_red_crosswalk_body(player_body_rect, road_states):
    for state in road_states:
        if collide(state["crosswalk"], player_body_rect) and state["light_state"] == "red":
            return True
    return False


def player_on_car_red_crosswalk(player_rect, road_states):
    return player_on_car_red_crosswalk_body(
        sprites.player_body_hitbox(player_rect), road_states
    )


def player_mostly_on_legal_crosswalk(body_rect, road_states, min_frac=0.45):
    """True when most of the body overlap is on crosswalks where cars have red (legal ped crossing)."""
    a = body_rect.width * body_rect.height
    if a <= 0:
        return False
    on_red = 0
    for state in road_states:
        if state["light_state"] != "red":
            continue
        inter = clip_rect(body_rect, state["crosswalk"])
        on_red += inter.width * inter.height
    on_red = min(on_red, a)
    return on_red >= a * min_frac


def player_hits_any_car(player, cars_group, spatial=None, scratch: list | None = None):
    pb = sprites.player_body_hitbox(player.rect)
    if spatial is not None and scratch is not None:
        for car in spatial.nearby(pb, PLAYER_CAR_QUERY_PAD, scratch):
            if collide(car._collision_shell, pb):
                return True
        return False
    for car in cars_group:
        if collide(car._collision_shell, pb):
            return True
    return False


def _cars_near_player(player_body: Rect, spatial, scratch: list) -> list:
    return spatial.nearby(player_body, PLAYER_CAR_QUERY_PAD, scratch)


def _view_rect_for_camera(camera_offset: tuple[int, int]) -> Rect:
    return Rect(
        camera_offset[0] - FRAME_RECORD_VIEW_PAD,
        camera_offset[1] - FRAME_RECORD_VIEW_PAD,
        WIDTH + FRAME_RECORD_VIEW_PAD * 2,
        HEIGHT + FRAME_RECORD_VIEW_PAD * 2,
    )


def _replay_view_rect_for_camera(camera_offset: tuple[int, int]) -> Rect:
    """Wider than draw view so replay shows cars before they enter the screen."""
    return _view_rect_for_camera(camera_offset).inflate(
        REPLAY_RECORD_EXTRA_PAD, REPLAY_RECORD_EXTRA_PAD
    )


def _cars_in_view(car_list, view_rect: Rect) -> list:
    return [c for c in car_list if c.alive() and collide(view_rect, c.rect)]


def _cars_for_replay(car_list, player_center: tuple[int, int]) -> list:
    """Record the full active fleet for replay (nearest first when capped)."""
    alive = [c for c in car_list if c.alive()]
    if len(alive) <= REPLAY_MAX_CARS:
        return alive
    px, py = player_center
    alive.sort(
        key=lambda car: (car.rect.centerx - px) ** 2 + (car.rect.centery - py) ** 2
    )
    return alive[:REPLAY_MAX_CARS]


def _cap_cars_near_player(
    car_list,
    view_rect: Rect,
    player_center: tuple[int, int],
    max_cars: int,
) -> list:
    """Emergency cap when too many cars share the viewport (draw perf safety)."""
    in_view = _cars_in_view(car_list, view_rect)
    if len(in_view) <= max_cars:
        return in_view
    px, py = player_center
    in_view.sort(
        key=lambda car: (car.rect.centerx - px) ** 2 + (car.rect.centery - py) ** 2
    )
    return in_view[:max_cars]


def cars_should_respect_player(player_on_road, player_on_crosswalk, on_car_red: bool):
    """Yield / stop for player only when they occupy the road or cross legally on red-for-cars."""
    if player_on_crosswalk:
        return on_car_red
    return player_on_road


def player_feet_on_road(player_rect, roads):
    """Lower body footprint must overlap pavement (visual on road, not sidewalk)."""
    feet = Rect(
        int(player_rect.x + player_rect.width * 0.18),
        int(player_rect.centery - player_rect.height * 0.05),
        int(player_rect.width * 0.64),
        int(player_rect.height * 0.42),
    )
    return any(collide(road.rect, feet) for road in roads)


def should_honk_at_player_precomputed(
    feet_on_road: bool,
    mostly_on_legal_crosswalk: bool,
    on_crosswalk: bool,
    on_car_red_crosswalk: bool,
) -> bool:
    """Honk policy using values computed once per frame (avoid O(cars * roads) work)."""
    if not feet_on_road:
        return False
    if mostly_on_legal_crosswalk:
        return False
    if on_crosswalk and on_car_red_crosswalk:
        return False
    return True


def update_light_timers(road_states, elapsed):
    cycle = _LIGHT_GREEN + _LIGHT_YELLOW + _LIGHT_RED
    for state in road_states:
        t = (elapsed + state["phase_offset"]) % cycle
        light = state["light_state"]
        if light == "green":
            state["seconds_to_change"] = _LIGHT_GREEN - t
            state["next_light"] = "yellow"
        elif light == "yellow":
            state["seconds_to_change"] = _LIGHT_GREEN + _LIGHT_YELLOW - t
            state["next_light"] = "red"
        else:
            state["seconds_to_change"] = cycle - t
            state["next_light"] = "green"
        turn_state, turn_secs = protected_turn_light_at(
            elapsed,
            state["phase_offset"],
            _LIGHT_GREEN,
            _LIGHT_YELLOW,
            _LIGHT_RED,
        )
        state["turn_light_state"] = turn_state
        state["turn_seconds_to_change"] = turn_secs
        state["next_turn_light"] = "red" if turn_state == "green" else "green"


def serialize_lights_for_frame(road_states):
    return [
        {
            "s": state["light_state"],
            "ts": state.get("turn_light_state", "red"),
            "in": round(state.get("seconds_to_change", 0), 1),
            "tin": round(state.get("turn_seconds_to_change", 0), 1),
            "next": state.get("next_light", "green"),
            "tnext": state.get("next_turn_light", "green"),
        }
        for state in road_states
    ]


def _load_prior_session():
    path = "logs.json"
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("session") or payload
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _map_seed_for_round(session_seed: int, round_index: int) -> int:
    """One session seed; each round gets a stable derived map seed."""
    return (int(session_seed) + round_index * 9973) & 0x7FFFFFFF


def _effective_light_durations(scale: float):
    """Scale full cycle length; preserve 45/10/45 green/yellow/red ratio."""
    cycle = LIGHT_CYCLE_SECONDS * max(0.88, scale)
    return cycle_durations(cycle)


def _rect_overlap_area(a: Rect, b: Rect) -> int:
    return rect_overlap_area(a, b)


SPAWN_RATE_MULT = 1.0
CAR_SPEED_MULT = 1.0
LIGHT_CYCLE_SCALE = 1.0
_LIGHT_GREEN = LIGHT_GREEN_DURATION
_LIGHT_YELLOW = LIGHT_YELLOW_DURATION
_LIGHT_RED = LIGHT_RED_DURATION
cars = EntityGroup()
player = None
all_sprites = EntityGroup()
start_time = 0.0
crossings = 0
collisions = 0
risk_events = 0
last_risk_time = 0
failure_reason = "none"
round_active = False
app_running = True
current_round_index = 1
current_difficulty_profile = None
base_preset_id = "normal"
session_num_rounds = pre_game.DEFAULT_ROUNDS
session_base_seed = 0
session_seed_source = "random"
session_use_adaptive_map = False
round_results = []
world_bounds = None
road_states = []
road_states_h: list = []
road_states_by_index: list[list] = []
_round_city_block_rects: tuple[Rect, ...] = ()
road_states_v: list = []
intersection_zones = []
intersection_zones_shell: list[Rect] = []
wall_rects = []
frame_recorder = None
decision_logger = None
traffic_schedule: list[TrafficSpawn] = []
traffic_spawn_cursor = 0
traffic_spawn_retry: list[TrafficSpawn] = []
traffic_respawn_pending: list[RespawnRequest] = []
traffic_respawn_event_id = RESPAWN_EVENT_ID_BASE
_ix_rects_cache = None
_ix_rects_cache_frame = -1
traffic_map_seed = 0
round_frame = 0


def _apply_difficulty_globals(profile: DifficultyProfile):
    global CAR_SPEED_MULT, SPAWN_RATE_MULT, LIGHT_CYCLE_SCALE
    global _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED
    CAR_SPEED_MULT = profile.car_speed_mult
    SPAWN_RATE_MULT = profile.spawn_rate_mult
    LIGHT_CYCLE_SCALE = profile.light_cycle_scale
    _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED = _effective_light_durations(LIGHT_CYCLE_SCALE)


def start_round(round_index: int, difficulty_profile: DifficultyProfile, preset_id: str):
    global current_map, ROUND_TIME_LIMIT, cars, player, all_sprites
    global start_time, crossings, collisions, risk_events, last_risk_time, failure_reason
    global round_active, current_round_index, current_difficulty_profile, base_preset_id
    global world_bounds, road_states, road_states_h, road_states_v, road_states_by_index
    global _round_city_block_rects
    global intersection_zones, intersection_zones_shell, wall_rects
    global frame_recorder, decision_logger
    global traffic_schedule, traffic_spawn_cursor, traffic_spawn_retry
    global traffic_respawn_pending, traffic_respawn_event_id
    global _ix_rects_cache, _ix_rects_cache_frame, traffic_map_seed, round_frame
    global session_base_seed, session_use_adaptive_map

    current_round_index = round_index
    current_difficulty_profile = difficulty_profile
    base_preset_id = preset_id
    install_for_round(preset_id, difficulty_profile)
    _apply_difficulty_globals(difficulty_profile)

    set_car_removed_callback(_queue_car_respawn)

    map_seed = _map_seed_for_round(session_base_seed, round_index)
    prior_session = _load_prior_session() if session_use_adaptive_map else None
    map_difficulty = None if session_use_adaptive_map else difficulty_profile

    current_map = map_generator.generate_map(
        seed=map_seed,
        prior_session=prior_session,
        difficulty=map_difficulty,
    )
    ROUND_TIME_LIMIT = current_map.time_limit

    cars = EntityGroup()
    player = Pedestrian(current_map.start_pos)
    all_sprites = EntityGroup(player)
    start_time = time.time()
    crossings = 0
    collisions = 0
    risk_events = 0
    last_risk_time = 0
    failure_reason = "none"

    frame_recorder = FrameRecorder(PEDESTRIAN_SIZE)
    decision_logger = DecisionLogger(
        current_map.start_pos,
        current_map.goal_rect.center,
        current_map.map_id,
        len(current_map.roads),
        frame_recorder=frame_recorder,
        analytics_zones=getattr(current_map, "analytics_zones", None),
    )

    world_bounds = build_world_bounds(current_map.roads, current_map.start_pos, current_map.goal_rect)
    road_states = build_road_states(current_map.roads)
    road_states_h = [s for s in road_states if s["direction"] == "horizontal"]
    road_states_v = [s for s in road_states if s["direction"] == "vertical"]
    road_states_by_index = _build_road_states_by_index(road_states, len(current_map.roads))
    _round_city_block_rects = _city_block_rects_from(
        getattr(current_map, "city_blocks", None)
    )
    intersection_zones = build_intersection_zones(current_map.roads)
    intersection_zones_shell = [
        zone.inflate(INTERSECTION_SHELL_PAD, INTERSECTION_SHELL_PAD)
        for zone in intersection_zones
    ]
    set_intersection_zones_shell(intersection_zones_shell)
    wall_rects = [
        Rect(world_bounds.left - 4000, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        Rect(world_bounds.right, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
        Rect(world_bounds.left, world_bounds.top - 4000, world_bounds.width, 4000),
        Rect(world_bounds.left, world_bounds.bottom, world_bounds.width, 4000),
    ]

    traffic_map_seed = current_map.seed
    set_traffic_map_seed(traffic_map_seed)
    weights = getattr(current_map, "traffic_weights", None)
    traffic_schedule = generate_traffic_schedule(
        traffic_map_seed,
        current_map.roads,
        weights,
        difficulty_profile,
        ROUND_TIME_LIMIT,
    )
    traffic_spawn.reset_spawn_state(traffic_schedule)
    traffic_spawn.bind_spawn_runtime(
        car_speed_mult=CAR_SPEED_MULT,
        city_block_rects=_round_city_block_rects,
        frame_car_spatial=_frame_car_spatial,
        frame_nearby_scratch=_frame_nearby_scratch,
        crosswalk_rects=tuple(s["crosswalk"] for s in road_states),
    )
    traffic_spawn.set_round_frame_getter(lambda: round_frame)
    _sync_spawn_state_from_module()
    _ix_rects_cache = None
    _ix_rects_cache_frame = -1
    round_frame = 0

    car_diagnostics.begin_round(
        current_round_index,
        session_seed=session_base_seed,
        map_seed=getattr(current_map, "seed", None),
        traffic_map_seed=traffic_map_seed,
    )

    round_active = True

    if ENABLE_PERF_PROFILE:
        perf_profiler.begin_round(
            round_index,
            map_id=str(getattr(current_map, "map_id", map_seed)),
            map_seed=map_seed,
            preset=preset_id,
            roads=len(current_map.roads),
            time_limit_s=ROUND_TIME_LIMIT,
        )

    current_map.bake(
        city_blocks=getattr(current_map, "city_blocks", None),
        decorations=getattr(current_map, "decorations", None),
        world_bounds=world_bounds,
        map_id=str(getattr(current_map, "map_id", map_seed)),
        road_states=road_states,
    )


def build_world_bounds(roads, start_pos, goal_rect):
    min_left = min([r.rect.left for r in roads] + [start_pos[0] - 80, goal_rect.left]) - 120
    max_right = max([r.rect.right for r in roads] + [start_pos[0] + 80, goal_rect.right]) + 120
    min_top = min([r.rect.top for r in roads] + [start_pos[1] - 80, goal_rect.top]) - 120
    max_bottom = max([r.rect.bottom for r in roads] + [start_pos[1] + 80, goal_rect.bottom]) + 120
    return Rect(min_left, min_top, max_right - min_left, max_bottom - min_top)


def build_road_states(roads):
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
    cycle = _LIGHT_GREEN + _LIGHT_YELLOW + _LIGHT_RED
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
                0.0, _LIGHT_GREEN, _LIGHT_YELLOW
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
            phase_offset = (_LIGHT_GREEN + _LIGHT_YELLOW) % cycle
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


def _road_states_for_car(car, fallback_states: list) -> list:
    if car.road_index is None:
        return fallback_states
    if car.road_index < 0 or car.road_index >= len(road_states_by_index):
        return fallback_states
    tagged = road_states_by_index[car.road_index]
    return tagged if tagged else fallback_states


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


def get_light_state(elapsed_seconds):
    return light_state_at(elapsed_seconds, _LIGHT_GREEN, _LIGHT_YELLOW, _LIGHT_RED)


def get_player_light_state(player_rect, states):
    body = sprites.player_body_hitbox(player_rect)
    for state in states:
        if collide(state["crosswalk"], body):
            return state["light_state"]
    return "none"


def get_pressed_keys(key_state: KeyState):
    return key_labels_from_state(key_state)


def _perf_counter_snapshot(
    *,
    car_list: list,
    replay_cars: list,
    draw_sprites: list,
) -> dict[str, int | float]:
    spatial = _frame_car_spatial
    bucket_entries = sum(len(b) for b in spatial._cells.values())
    replay_frames = len(frame_recorder.frames) if frame_recorder else 0
    decisions = len(decision_logger.decisions) if decision_logger else 0
    heat_samples = len(decision_logger.heat_samples) if decision_logger else 0
    return {
        "cars_alive": sum(1 for c in car_list if c.alive()),
        "cars_in_group": len(cars),
        "draw_sprites": len(draw_sprites),
        "record_cars": len(replay_cars),
        "cars_in_view": len(replay_cars),
        "replay_frames": replay_frames,
        "decisions": decisions,
        "heat_samples": heat_samples,
        "spawn_retry_queue": len(traffic_spawn_retry),
        "spawn_cursor": traffic_spawn_cursor,
        "spawn_schedule_len": len(traffic_schedule),
        "spatial_cells": len(spatial._cells),
        "spatial_bucket_entries": bucket_entries,
        "road_states": len(road_states),
    }


def end_round(collided, timed_out=False) -> str:
    global crossings, collisions, round_active, risk_events, failure_reason, round_results
    if not round_active:
        return failure_reason if failure_reason != "none" else "collision"
    car_diagnostics.end_round()
    end_time = time.time()
    duration = round(end_time - start_time, 2)
    if collided:
        collisions += 1
        failure_reason = "collision"
        outcome = "collision"
    elif timed_out:
        failure_reason = "timeout"
        outcome = "timeout"
    else:
        failure_reason = "goal_reached"
        outcome = "success"

    camera_offset = (
        player.rect.centerx - WIDTH // 2,
        player.rect.centery - HEIGHT // 2,
    )
    end_cars = _cars_for_replay(
        [c for c in cars.sprites() if c.alive()],
        player.rect.center,
    )
    frame_recorder.capture_end(
        duration, player.rect, end_cars, road_states, game_time=duration
    )

    session = decision_logger.finalize(
        outcome=outcome,
        duration=duration,
        crossings=crossings,
        collisions=collisions,
        risk_events=risk_events,
        failure_reason=failure_reason,
    )
    session["map_layout"] = serialize_map_layout(current_map, road_states, world_bounds)
    session["map_seed"] = getattr(current_map, "seed", None)
    session["session_seed"] = session_base_seed
    session["time_limit"] = ROUND_TIME_LIMIT
    session["difficulty"] = getattr(current_map, "difficulty", None)
    session["round_index"] = current_round_index
    session["rounds_total"] = session_num_rounds
    session["base_preset"] = base_preset_id
    session["analytics_zones"] = getattr(current_map, "analytics_zones", [])
    session["path_estimate_s"] = getattr(current_map, "path_estimate_s", None)
    session["generation_meta"] = getattr(current_map, "generation_meta", None)
    session["car_archetypes"] = sprites.serialize_archetypes_for_log()
    archetypes = score_session(session)

    round_results.append(
        {
            "round": current_round_index,
            "outcome": outcome,
            "duration_s": duration,
            "crossings": crossings,
            "collisions": collisions,
            "risk_events": risk_events,
            "session": session,
            "archetypes": archetypes,
        }
    )
    round_active = False
    print(f"Round {current_round_index} complete:", outcome, f"({duration}s)")
    if ENABLE_PERF_PROFILE:
        report_path = perf_profiler.end_round(outcome, duration)
        print(f"Perf log: {perf_profiler.jsonl_path}")
        if report_path:
            print(f"Perf report: {report_path}")
        print("Share perf_profile.jsonl + perf_report.html for lag diagnosis.")
    return outcome


def save_session_log():
    if not round_results:
        return None
    last = round_results[-1]
    log = {
        "time": last["duration_s"],
        "crossings": last["crossings"],
        "collisions": last["collisions"],
        "risks_taken": last["risk_events"],
        "failure_reason": last["session"].get("failure_reason"),
        "outcome": last["outcome"],
        "min_crossings": len(last["session"].get("map_layout", {}).get("roads", [])) or 0,
        "avg_time_per_crossing": last["duration_s"] / max(1, last["crossings"]),
        "session": last["session"],
        "archetypes": last["archetypes"],
        "num_rounds": session_num_rounds,
        "session_seed": session_base_seed,
        "seed_source": session_seed_source,
        "pathwise_seed_env": os.environ.get("PATHWISE_SEED"),
        "adaptive_map": session_use_adaptive_map,
        "base_difficulty_preset": base_preset_id,
        "rounds": round_results,
    }
    with open("logs.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    return build_dashboard_html("logs.json")


def record_risk(reason, cooldown=None, **context):
    global risk_events, last_risk_time
    local_cooldown = RISK_COOLDOWN_SECONDS if cooldown is None else cooldown
    if (time.time() - last_risk_time) > local_cooldown:
        risk_events += 1
        last_risk_time = time.time()
        decision_logger.note_risk(reason, **context)


def is_car_approaching_player(car, player_rect):
    body = sprites.player_body_hitbox(player_rect)
    if car.vertical:
        dx = abs(car.rect.centerx - body.centerx)
        if dx > 48:
            return False
        ahead = (body.centery - car.rect.centery) * car.direction
        return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35
    dy = abs(car.rect.centery - body.centery)
    if dy > 48:
        return False
    ahead = (body.centerx - car.rect.centerx) * car.direction
    return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35

def update_round_frame(keys: KeyState, *, before_shell_separation=None):
    """Advance simulation one frame; returns draw kwargs when the round is still active."""
    global round_frame, crossings, risk_events, last_risk_time
    if not round_active:
        return None
    elapsed = time.time() - start_time
    time_left = max(0, ROUND_TIME_LIMIT - elapsed)

    previous_pos = player.rect.topleft

    with perf_profiler.section("lights_and_crossings"):
        for state in road_states:
            state["light_state"] = get_light_state(elapsed + state["phase_offset"])
            state["player_waiting"] = False
            road_rect = state["road_rect"]
            crosswalk = state["crosswalk"]
            wait_zone = crosswalk.inflate(80, 80)
            if collide(wait_zone, player.rect) and not collide(road_rect, player.rect):
                state["player_waiting"] = True
        update_light_timers(road_states, elapsed)

        for road_index, road in enumerate(current_map.roads):
            approach_zone = road.rect.inflate(120, 120)
            if not road.crossed and collide(approach_zone, player.rect):
                decision_logger.note_road_approach(road_index)

            if collide(road.rect, player.rect) and not road.crossed:
                if road.direction == "vertical":
                    if player.rect.top < road.rect.top:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )
                elif road.direction == "horizontal":
                    if player.rect.left > road.rect.left:
                        crossings += 1
                        road.crossed = True
                        decision_logger.note_road_crossed(
                            road_index, get_player_light_state(player.rect, road_states)
                        )

    with perf_profiler.section("traffic_spawns"):
        _process_traffic_spawns_through_frame(
            round_frame,
            current_map.roads,
            cars,
            all_sprites,
            intersection_zones,
            player.rect,
            getattr(current_map, "city_blocks", None),
            world_bounds,
        )
        _sync_spawn_state_from_module()
    round_frame += 1
    traffic_spawn.set_round_frame_getter(lambda: round_frame)

    with perf_profiler.section("player_update"):
        player.update(keys)
        if not contains_rect(world_bounds, player.rect):
            player.rect.topleft = previous_pos

    with perf_profiler.section("player_context"):
        player_body = sprites.player_body_hitbox(player.rect)
        player_on_crosswalk = any(
            collide(state["crosswalk"], player_body) for state in road_states
        )
        player_on_road = any(
            collide(road.rect, player_body) for road in current_map.roads
        )
        player_feet_road = player_feet_on_road(player.rect, current_map.roads)
        player_mostly_legal = player_mostly_on_legal_crosswalk(player_body, road_states)
        player_on_car_red = player_on_car_red_crosswalk_body(player_body, road_states)
        ped_legal_crossing = player_on_crosswalk and player_on_car_red
        respect_player = cars_should_respect_player(
            player_on_road, player_on_crosswalk, player_on_car_red
        )
        honk_allowed = should_honk_at_player_precomputed(
            player_feet_road,
            player_mostly_legal,
            player_on_crosswalk,
            player_on_car_red,
        )
        player_body_block = player_body.inflate(4, 4)

    camera_offset = (
        player.rect.centerx - WIDTH // 2,
        player.rect.centery - HEIGHT // 2,
    )
    view_rect = _view_rect_for_camera(camera_offset)
    replay_view = _replay_view_rect_for_camera(camera_offset)
    sim_view = view_rect.inflate(SIM_UPDATE_VIEW_PAD, SIM_UPDATE_VIEW_PAD)

    car_list = cars.sprites_into(_frame_car_list_scratch)
    with perf_profiler.section("cars_spatial"):
        _frame_car_spatial.rebuild(car_list)
        lane_buckets = _build_lane_buckets(car_list)
    move_scratch = _frame_nearby_scratch
    lane_scratch = _frame_lane_scratch
    with perf_profiler.section("cars_update"):
        for car in car_list:
            if not car.alive():
                continue
            in_intersection = bool(intersection_zones) and car._rect_in_intersection(
                car.rect, intersection_zones
            )
            in_active_turn = (
                car._turn_phase in ("to_hub", "turning", "settling")
                or car.turn_signal != 0
            )
            if (
                not in_intersection
                and not in_active_turn
                and car._turn_phase == "none"
                and car.turn_signal == 0
                and car.current_speed >= 0.4
                and not car._approaching_or_in_intersection(intersection_zones)
            ):
                _lane_peers_for(car, lane_buckets, lane_scratch)
                car.straight_cruise_update(
                    _road_states_for_car(
                        car, road_states_v if car.vertical else road_states_h
                    ),
                    world_bounds,
                    lane_scratch,
                    round_frame,
                    current_map.roads,
                    intersection_zones,
                    player_body,
                )
                _frame_car_spatial.relocate_car(car)
                continue
            if (
                not in_intersection
                and not in_active_turn
                and not collide(sim_view, car._collision_shell)
            ):
                stride = sim_tuning.OFFSCREEN_FAR_STRIDE
                if (round_frame + car.spawn_id) % stride != 0:
                    car._spawn_age += 1
                    signed = car.current_speed * car.direction
                    if signed != 0:
                        if car.vertical:
                            car.rect.y += int(signed)
                        else:
                            car.rect.x += int(signed)
                    car._sync_collision_shell()
                    _frame_car_spatial.relocate_car(car)
                    continue
            _lane_peers_for(car, lane_buckets, lane_scratch)
            peer_pad = 72 if car._turn_phase == "none" and car.turn_signal == 0 else IX_QUERY_PAD
            if car._turn_phase in ("to_hub", "turning", "settling") or car.turn_signal != 0:
                peer_pad += TURN_PEER_QUERY_PAD
            move_peers = _frame_car_spatial.nearby(
                car._collision_shell, peer_pad, move_scratch
            )
            car._frame_move_peers = move_peers
            car.update(
                _road_states_for_car(
                    car, road_states_v if car.vertical else road_states_h
                ),
                world_bounds,
                intersection_zones,
                player_body,
                current_map.roads,
                lane_scratch,
                move_peers,
                round_frame,
                player_on_road,
                player_on_crosswalk,
                player_feet_road,
                ped_legal_crossing,
                respect_player,
                honk_allowed,
                player_body_block,
                elapsed,
            )
            _frame_car_spatial.relocate_car(car)

    with perf_profiler.section("car_shell_separation"):
        if before_shell_separation is not None:
            before_shell_separation(car_list)
        if (
            round_frame % sim_tuning.SHELL_SEP_EVERY_N_FRAMES == 0
            or len(car_list) <= sim_tuning.SHELL_SEP_FLEET_THRESHOLD
        ):
            _resolve_all_shell_overlaps(car_list)
            if any(
                c.alive() and c._turn_phase in ("turning", "settling")
                for c in car_list
            ):
                _resolve_all_shell_overlaps(car_list)

    with perf_profiler.section("car_diagnostics"):
        if ENABLE_CAR_DIAGNOSTICS:
            player_center = player_body.center
            for car in car_list:
                if not car.alive():
                    continue
                car_diagnostics.observe(
                    car,
                    game_time=elapsed,
                    round_frame=round_frame,
                    intersection_zones=intersection_zones,
                    move_peers=car._frame_move_peers or (),
                    player_center=player_center,
                )

    with perf_profiler.section("risk_checks"):
        near_player_cars = _cars_near_player(
            player_body, _frame_car_spatial, _frame_player_car_scratch
        )
        replay_cars = _cars_for_replay(car_list, player_body.center)
        draw_cars = replay_cars
        if len(draw_cars) > MAX_DRAW_RECORD_CARS:
            draw_cars = _cap_cars_near_player(
                car_list,
                view_rect,
                player_body.center,
                MAX_DRAW_RECORD_CARS,
            )
        draw_sprites = _frame_draw_sprites_scratch
        draw_sprites.clear()
        draw_sprites.append(player)
        draw_sprites.extend(draw_cars)

        for car in cars:
            if car.honk_risk_pending:
                honk_reason = car.honk_reason or "honk"
                local_cooldown = 0.85
                if (time.time() - last_risk_time) > local_cooldown:
                    risk_events += 1
                    last_risk_time = time.time()
                decision_logger._record(
                    "car_honk",
                    reason=honk_reason,
                    risk=f"car_honk_{honk_reason}",
                )
                car.honk_risk_pending = False
        nearby_fast_cars = [
            car
            for car in near_player_cars
            if collide(car._collision_shell.inflate(170, 170), player_body)
            and car.current_speed > car.base_speed * 0.65
        ]
        approaching_cars = [
            car
            for car in near_player_cars
            if is_car_approaching_player(car, player.rect)
        ]

        if player_on_road and not player_on_crosswalk and nearby_fast_cars:
            record_risk("fast_traffic_on_road")
        if player_on_crosswalk and approaching_cars:
            crosswalk_red = player_on_car_red
            dangerous_cars = [
                car
                for car in approaching_cars
                if car.current_speed > car.base_speed * 0.25
            ]

            if not crosswalk_red or dangerous_cars:
                record_risk(
                    "crosswalk_vehicle_conflict",
                    on_crosswalk=True,
                    light=get_player_light_state(player.rect, road_states),
                )
            if any(
                collide(
                    car._collision_shell.inflate(TOO_CLOSE_DISTANCE, TOO_CLOSE_DISTANCE),
                    player_body,
                )
                for car in near_player_cars
            ):
                record_risk("vehicle_too_close", cooldown=0.7)
            if any(
                collide(
                    car._collision_shell.inflate(NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE),
                    player_body,
                )
                and car.current_speed > car.base_speed * 0.75
                for car in near_player_cars
            ):
                record_risk("near_miss")

    with perf_profiler.section("decision_logger"):
        decision_logger.update(
            player_body.center,
            get_pressed_keys(keys),
            player_on_crosswalk,
            player_on_road,
            get_player_light_state(player.rect, road_states),
            False,
        )

    with perf_profiler.section("frame_recorder"):
        if not frame_recorder.frames:
            frame_recorder.capture_start(
                elapsed, player.rect, replay_cars, road_states, game_time=elapsed
            )
        else:
            frame_recorder.capture(
                elapsed, player.rect, replay_cars, road_states, game_time=elapsed
            )

    with perf_profiler.section("round_end_checks"):
        if player_hits_any_car(
            player, cars, spatial=_frame_car_spatial, scratch=_frame_player_car_scratch
        ):
            end_round(True, timed_out=False)
        elif collide(player.rect, current_map.goal_rect):
            end_round(False, timed_out=False)

        if time_left <= 0 and round_active:
            end_round(False, timed_out=True)

    if not round_active:
        return None

    esc = (
        getattr(current_difficulty_profile, "round_escalation", 0.0)
        if current_difficulty_profile
        else 0.0
    )
    hud_lines = [
        f"Round {current_round_index}/{session_num_rounds} · intensity {esc * 100:.0f}%",
        f"Time left: {time_left:05.1f}s",
        f"Crossings: {crossings}/{len(current_map.roads)} · "
        f"traffic {sum(1 for c in car_list if c.alive())} "
        f"({max(0, len(draw_sprites) - 1)} on screen)",
        f"Risky moves: {risk_events}",
    ]
    if ENABLE_PERF_PROFILE:
        hud_lines.append(f"Perf log: {perf_profiler.jsonl_path}")
    perf_profiler.finish_update(
        round_frame=round_frame,
        elapsed_s=elapsed,
        counters=_perf_counter_snapshot(
            car_list=car_list,
            replay_cars=replay_cars,
            draw_sprites=draw_sprites,
        ),
    )
    return {
        "camera_offset": camera_offset,
        "view_rect": view_rect,
        "record_cars": draw_cars,
        "draw_sprites": draw_sprites,
        "elapsed": elapsed,
        "hud_lines": hud_lines,
    }


def draw_round_frame(window_height: int, draw_state: dict) -> None:
    from pathwise.game_draw import draw_round_scene

    draw_round_scene(
        window_height,
        current_map=current_map,
        player=player,
        world_bounds=world_bounds,
        road_states=road_states,
        wall_rects=wall_rects,
        draw_sprites=draw_state["draw_sprites"],
        record_cars=draw_state["record_cars"],
        camera_offset=draw_state["camera_offset"],
        view_rect=draw_state["view_rect"],
        elapsed=draw_state["elapsed"],
        hud_lines=draw_state["hud_lines"],
        light_green_duration=_LIGHT_GREEN,
        draw_traffic_timer_bar=TRAFFIC_DRAW_TIMER_BAR,
    )


def main():
    from pathwise.pathwise_window import PathwiseWindow

    PathwiseWindow().run()


if __name__ == "__main__":
    main()
