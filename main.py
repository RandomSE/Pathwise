"""Pathwise game entry point: thin orchestration over pathwise modules."""

from __future__ import annotations

import os
import time

from analytics.car_diagnostics import car_diagnostics
from analytics.perf_profiler import PerfProfiler, perf_profile_enabled
from map_generation.traffic_schedule import TrafficSpawn
from pathwise import pre_game
from pathwise import traffic_spawn
from pathwise.car import (
    Car,
    CarSpatialIndex,
    CarSpawnOrigin,
    RespawnRequest,
    _build_lane_buckets,
    _frame_car_list_scratch,
    _frame_car_spatial,
    _frame_draw_sprites_scratch,
    _frame_lane_scratch,
    _frame_nearby_scratch,
    _frame_player_car_scratch,
    _lane_peers_for,
    _fleet_has_shell_overlap,
    _resolve_all_shell_overlaps,
)
from pathwise.entity_group import EntityGroup
from pathwise.geom import Rect
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
from pathwise.pedestrian import Pedestrian
from pathwise.sim_constants import *  # noqa: F403
from pathwise.sim_constants import LIGHT_GREEN_DURATION, LIGHT_YELLOW_DURATION, LIGHT_RED_DURATION
from analytics.dashboard import build_dashboard_html

ENABLE_PERF_PROFILE = perf_profile_enabled()
perf_profiler = PerfProfiler(enabled=ENABLE_PERF_PROFILE)

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
reasonable_risk_events = 0
risky_risk_events = 0
last_risk_time = 0
legal_crossing_commit_active = False
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
session_modifiers = None
session_audience = "candidate"
session_candidate_label = None
session_recruiter_seed_code = None
session_started_at_utc = None
rain_slip_tracker = None
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
player_prev_center = (0, 0)

current_map = None
ROUND_TIME_LIMIT = 0.0

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


def _game_state():
    import sys
    return sys.modules[__name__]


def _sync_spawn_state_from_module() -> None:
    sync_spawn_state_from_runtime()


from pathwise.crosswalk_rules import (  # noqa: E402
    car_is_traffic_threat,
    car_shares_crossing_plane,
    cars_on_crossing_plane,
    cars_should_respect_player,
    crosswalk_crossing_is_legal,
    is_car_approaching_player,
    player_conflicting_car_vertical,
    player_crossing_cars_have_red,
    player_dominant_crosswalk_state,
    player_feet_on_road,
    player_hits_any_car,
    player_mostly_on_legal_crosswalk,
    player_on_car_red_crosswalk,
    player_on_car_red_crosswalk_body,
    road_midline_crossed,
    should_honk_at_player_precomputed,
    update_legal_crossing_commit,
)
from pathwise.car_viewport import (  # noqa: E402
    _cap_cars_near_player,
    _cars_for_replay,
    _cars_in_view,
    _cars_near_player,
    _replay_view_rect_for_camera,
    _view_rect_for_camera,
)
from pathwise.road_states import (  # noqa: E402
    _build_road_states_by_index,
    _car_approach_label,
    _oriented_road_states_for_car,
    _road_states_for_car,
    build_intersection_zones,
    build_road_states,
    get_light_state,
    get_player_light_state,
    lane_center_for_road,
    serialize_lights_for_frame,
    update_light_timers,
)
from pathwise.round_session import (  # noqa: E402
    _effective_light_durations,
    _load_prior_session,
    _map_seed_for_round,
    _perf_counter_snapshot,
    build_world_bounds,
    end_round,
    finalize_round_result,
    record_risk,
    save_session_log,
    start_round,
    sync_spawn_state_from_runtime,
)
from pathwise.round_frame import draw_round_frame, update_round_frame  # noqa: E402


def get_pressed_keys(key_state: KeyState):
    from pathwise.input_keys import key_labels_from_state

    return key_labels_from_state(key_state)


def main():
    from pathwise.pathwise_window import PathwiseWindow

    PathwiseWindow().run()


if __name__ == "__main__":
    main()
