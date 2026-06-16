"""One-shot helper to extract Car / spawn modules from main.py."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
lines = MAIN.read_text(encoding="utf-8").splitlines()

SIM_CONSTANTS_HEADER = '''"""Shared simulation tuning constants for Pathwise."""

from __future__ import annotations

import os

from analytics.perf_profiler import perf_profile_enabled
from analytics.traffic_lights import cycle_durations
from map_generation.traffic_schedule import INTERSECTION_SPAWN_PAD, MIN_ALONG_GAP, RECT_COLLIDE_PAD
from pathwise import commonUtils

utils = commonUtils
WIDTH, HEIGHT = utils.WIDTH, utils.HEIGHT
ROAD_Y = utils.ROAD_Y
ROAD_HEIGHT = utils.ROAD_HEIGHT
CAR_WIDTH, CAR_HEIGHT = utils.CAR_WIDTH, utils.CAR_HEIGHT
PEDESTRIAN_SIZE = utils.PEDESTRIAN_SIZE
PEDESTRIAN_SPEED = utils.PEDESTRIAN_SPEED
CAR_SPEED = utils.CAR_SPEED
SIM_FPS = 60.0
'''

# main.py lines 72-180 (1-based) after SIM_FPS duplicate
sim_body = "\n".join(lines[71:180]) + "\n"
(ROOT / "pathwise" / "sim_constants.py").write_text(
    SIM_CONSTANTS_HEADER + sim_body, encoding="utf-8"
)

CAR_HEADER = '''"""Vehicle entity, spatial index, and lane-peer helpers."""

from __future__ import annotations

import math

from dataclasses import dataclass

from map_generation.intersection_routing import (
    choose_exit,
    pick_turn_side,
    pivot_center_at_intersection,
    travel_vector,
    turn_side_from_exit,
)
from map_generation.lane_geometry import lane_center_xy
from map_generation.turn_clearance import bezier_point as _bezier_xy
from map_generation.turn_clearance import corridor_bounds as _turn_corridor_bounds
from map_generation.turn_clearance import sample_bezier as _sample_bezier_xy
from map_generation.traffic_schedule import MIN_ALONG_GAP, RECT_COLLIDE_PAD
from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect, collide, clip_rect, contains_rect, rect_overlap_area, rects_overlap
from pathwise.sim_constants import *  # noqa: F403

_car_removed_callback = None


def set_car_removed_callback(callback) -> None:
    global _car_removed_callback
    _car_removed_callback = callback


def _notify_car_removed(car: "Car") -> None:
    if _car_removed_callback is not None:
        _car_removed_callback(car)


'''

# Car block: lines 370-3133 (1-based) -> index 369:3133
car_body = "\n".join(lines[369:3133])
car_body = car_body.replace("_queue_car_respawn(self)", "_notify_car_removed(self)")
(ROOT / "pathwise" / "car.py").write_text(CAR_HEADER + car_body + "\n", encoding="utf-8")

PED_HEADER = '''"""Pedestrian entity."""

from __future__ import annotations

from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP
from pathwise.sim_constants import PEDESTRIAN_SIZE, PEDESTRIAN_SPEED

'''

ped_body = "\n".join(lines[3134:3154])
(ROOT / "pathwise" / "pedestrian.py").write_text(PED_HEADER + ped_body + "\n", encoding="utf-8")

SPAWN_HEADER = '''"""Traffic spawn pipeline and car respawn queue."""

from __future__ import annotations

import random

from map_generation.traffic_schedule import (
    PHASE_ONGOING,
    TrafficSpawn,
    build_intersection_rects,
    edge_spawn_lane_allowed,
    lane_spawn_allowed,
    pose_overlaps_intersection_rects,
    spawn_poses_for_event,
)
from pathwise import sprites
from pathwise.car import Car, CarSpatialIndex, CarSpawnOrigin, RespawnRequest
from pathwise.geom import Rect, rect_overlap_area, rects_overlap
from pathwise.sim_constants import *  # noqa: F403

# Round-scoped globals wired by main.start_round
CAR_SPEED_MULT = 1.0
_round_city_block_rects: tuple[Rect, ...] = ()
traffic_respawn_pending: list[RespawnRequest] = []
traffic_respawn_event_id = RESPAWN_EVENT_ID_BASE
traffic_spawn_cursor = 0
traffic_spawn_retry: list[TrafficSpawn] = []
traffic_schedule: list[TrafficSpawn] = []
_ix_rects_cache = None
_ix_rects_cache_frame = -1
_frame_car_spatial: CarSpatialIndex | None = None
_frame_nearby_scratch: list = []
_round_frame_getter = lambda: 0


def set_round_frame_getter(getter) -> None:
    global _round_frame_getter
    _round_frame_getter = getter


def bind_spawn_runtime(
    *,
    car_speed_mult: float,
    city_block_rects: tuple[Rect, ...],
    frame_car_spatial: CarSpatialIndex,
    frame_nearby_scratch: list,
) -> None:
    global CAR_SPEED_MULT, _round_city_block_rects
    global _frame_car_spatial, _frame_nearby_scratch
    CAR_SPEED_MULT = car_speed_mult
    _round_city_block_rects = city_block_rects
    _frame_car_spatial = frame_car_spatial
    _frame_nearby_scratch = frame_nearby_scratch


def reset_spawn_state(
    schedule: list[TrafficSpawn],
    *,
    respawn_event_id: int = RESPAWN_EVENT_ID_BASE,
) -> None:
    global traffic_schedule, traffic_spawn_cursor, traffic_spawn_retry
    global traffic_respawn_pending, traffic_respawn_event_id
    global _ix_rects_cache, _ix_rects_cache_frame
    traffic_schedule = schedule
    traffic_spawn_cursor = 0
    traffic_spawn_retry = []
    traffic_respawn_pending = []
    traffic_respawn_event_id = respawn_event_id
    _ix_rects_cache = None
    _ix_rects_cache_frame = -1


'''

spawn_body = "\n".join(lines[3175:3670])
spawn_body = spawn_body.replace("round_frame + RESPAWN_DELAY_FRAMES", "_round_frame_getter() + RESPAWN_DELAY_FRAMES")
(ROOT / "pathwise" / "traffic_spawn.py").write_text(
    SPAWN_HEADER + spawn_body + "\n", encoding="utf-8"
)

# Register respawn callback at end of traffic_spawn
append = '''

set_car_removed_callback(_queue_car_respawn)
'''
(ROOT / "pathwise" / "traffic_spawn.py").write_text(
    (ROOT / "pathwise" / "traffic_spawn.py").read_text(encoding="utf-8") + append,
    encoding="utf-8",
)

print("Extracted sim_constants, car, pedestrian, traffic_spawn")
