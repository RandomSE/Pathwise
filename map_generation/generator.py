"""Procedural map orchestration: noise layout, validation, difficulty, analytics."""

from __future__ import annotations

import random

import pygame

from map import MapBase, Road, make_rectangle, BASE_SIZE, ROAD_THICKNESS, ROAD_GAP
import commonUtils

from map_generation.analytics import build_analytics_zones
from map_generation.constraints import (
    road_positions_valid,
    roads_fully_connected,
    traffic_density_balanced,
)
from map_generation.difficulty import DifficultyProfile, adaptive_difficulty
from map_generation.noise import fbm, simplex2
from map_generation.pathfinding import Cell, astar_travel_time, bfs_solvable
from map_generation.safety import expected_wait_for_safe_crossing, min_time_limit_for_route

VERTICAL = commonUtils.VERTICAL
HORIZONTAL = commonUtils.HORIZONTAL

ORIGIN = 100
STRIDE = ROAD_THICKNESS + ROAD_GAP
MIN_ROAD_GAP = ROAD_THICKNESS + 24
MAX_GENERATION_ATTEMPTS = 64
JITTER_MAX = 28


def _spawn_clear(x: int, y: int, roads: list[Road], pad: int = 22) -> bool:
    probe = pygame.Rect(x - 12, y - 12, 24, 24)
    for road in roads:
        if probe.colliderect(road.rect.inflate(pad, pad)):
            return False
    return True


def _block_center_x(col: int, v_xs: list[int], origin: int, world_right: int) -> int:
    if not v_xs:
        return (origin + world_right) // 2
    if col <= 0:
        left, right = origin, v_xs[0]
    elif col >= len(v_xs):
        left, right = v_xs[-1] + ROAD_THICKNESS, world_right
    else:
        left, right = v_xs[col - 1] + ROAD_THICKNESS, v_xs[col]
    return (left + right) // 2


def _block_center_y(row: int, h_ys: list[int], origin: int, world_bottom: int) -> int:
    if not h_ys:
        return (origin + world_bottom) // 2
    if row <= 0:
        top, bottom = origin, h_ys[0]
    elif row >= len(h_ys):
        top, bottom = h_ys[-1] + ROAD_THICKNESS, world_bottom
    else:
        top, bottom = h_ys[row - 1] + ROAD_THICKNESS, h_ys[row]
    return (top + bottom) // 2


def _noise_partition(total: int, difficulty: DifficultyProfile, rng: random.Random, seed: int) -> tuple[int, int]:
    bias = fbm(0.4, 0.2, seed)
    n_h = max(1, min(total - 1, round(total * (0.35 + 0.35 * bias))))
    n_v = total - n_h
    if total >= 4 and (n_h < 2 or n_v < 2):
        n_h = max(2, min(total - 2, n_h + 1))
        n_v = total - n_h
    return n_h, n_v


def _jittered_axis_positions(count: int, seed: int, axis: str) -> list[int]:
    positions = []
    for i in range(count):
        jitter = int((simplex2(i * 0.9 + (1 if axis == "x" else 0), seed * 0.03, seed) - 0.5) * 2 * JITTER_MAX)
        base = ORIGIN + (i + 1) * STRIDE + jitter
        if positions and base <= positions[-1] + MIN_ROAD_GAP:
            base = positions[-1] + MIN_ROAD_GAP
        positions.append(base)
    return positions


def _traffic_weights(roads: list[Road], seed: int, difficulty: DifficultyProfile) -> list[float]:
    weights = []
    for idx, road in enumerate(roads):
        n = fbm(road.rect.centerx * 0.004, road.rect.centery * 0.004, seed + idx * 11)
        w = 0.35 + n * 0.9 + difficulty.traffic_density * 0.35
        weights.append(round(w, 3))
    return weights


def generate_map_layout(
    seed=None,
    prior_session: dict | None = None,
    difficulty: DifficultyProfile | None = None,
) -> dict:
    rng = random.Random(seed)
    seed = rng.randint(0, 2**31 - 1) if seed is None else int(seed)
    rng = random.Random(seed)

    if difficulty is None:
        difficulty = adaptive_difficulty(prior_session)

    target_crossings = rng.randint(difficulty.min_crossings, difficulty.max_crossings)

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        n_h, n_v = _noise_partition(target_crossings, difficulty, rng, seed + attempt)
        h_ys = _jittered_axis_positions(n_h, seed + attempt * 3, "y")
        v_xs = _jittered_axis_positions(n_v, seed + attempt * 5 + 1, "x")

        if not road_positions_valid(h_ys, v_xs, MIN_ROAD_GAP):
            continue

        grid_extent = max(n_v, n_h) + 1
        world_left = ORIGIN - 60
        world_top = ORIGIN - 60
        world_right = ORIGIN + grid_extent * STRIDE + 220
        world_bottom = ORIGIN + grid_extent * STRIDE + 220
        span_w = world_right - world_left
        span_h = world_bottom - world_top

        roads: list[Road] = []
        for y in h_ys:
            roads.append(Road(make_rectangle(world_left, y, span_w, ROAD_THICKNESS), VERTICAL))
        for x in v_xs:
            roads.append(Road(make_rectangle(x, world_top, ROAD_THICKNESS, span_h), HORIZONTAL))

        if not roads_fully_connected(roads):
            continue

        traffic_weights = _traffic_weights(roads, seed + attempt, difficulty)
        if not traffic_density_balanced(traffic_weights):
            continue

        for road, weight in zip(roads, traffic_weights):
            road.traffic_weight = weight

        start_col, start_row = 0, n_h
        goal_col, goal_row = n_v, 0
        if rng.random() < 0.3 + difficulty.unpredictability * 0.25 and n_v >= 2 and n_h >= 2:
            goal_col = rng.randint(max(1, n_v // 2), n_v)
            goal_row = rng.randint(0, max(0, n_h // 2))

        start_cell = Cell(start_col, start_row)
        goal_cell = Cell(goal_col, goal_row)
        if not bfs_solvable(start_cell, goal_cell, n_v, n_h):
            continue

        crossing_wait = expected_wait_for_safe_crossing(difficulty.light_cycle_scale)
        travel_s = astar_travel_time(start_cell, goal_cell, n_v, n_h, crossing_wait)
        if travel_s is None:
            continue

        manhattan = abs(goal_col - start_col) + abs(goal_row - start_row)
        safe_limit = min_time_limit_for_route(
            travel_s,
            manhattan,
            difficulty.light_cycle_scale,
            safety_margin=1.08,
        )
        baseline = 18 + target_crossings * 4
        time_limit = max(baseline, min(safe_limit, baseline + 14))

        sx = _block_center_x(start_col, v_xs, ORIGIN, world_right)
        sy = _block_center_y(start_row, h_ys, ORIGIN, world_bottom)
        gx = _block_center_x(goal_col, v_xs, ORIGIN, world_right)
        gy = _block_center_y(goal_row, h_ys, ORIGIN, world_bottom)

        goal_rect = pygame.Rect(gx - BASE_SIZE // 2, gy - BASE_SIZE // 2, BASE_SIZE, BASE_SIZE)
        if not _spawn_clear(sx, sy, roads) or not _spawn_clear(gx, gy, roads):
            continue
        if any(goal_rect.colliderect(r.rect.inflate(4, 4)) for r in roads):
            continue

        analytics_zones = build_analytics_zones(roads, h_ys, v_xs, (sx, sy), goal_rect)

        return {
            "seed": seed,
            "target_crossings": target_crossings,
            "time_limit": time_limit,
            "roads": roads,
            "start_pos": (sx, sy),
            "goal_rect": goal_rect,
            "n_h": n_h,
            "n_v": n_v,
            "difficulty": difficulty.to_dict(),
            "analytics_zones": analytics_zones,
            "traffic_weights": traffic_weights,
            "path_estimate_s": round(travel_s, 2),
            "generation": {
                "attempt": attempt,
                "noise_jitter": JITTER_MAX,
                "solver": "astar+bfs",
                "safe_crossing_model": "light_cycle",
            },
        }

    raise RuntimeError("Failed to generate a valid procedural map")


class ProceduralMap(MapBase):
    def __init__(self, seed=None, prior_session=None, difficulty=None):
        profile = difficulty
        if profile is not None and not isinstance(profile, DifficultyProfile):
            profile = DifficultyProfile.from_level(float(profile))
        layout = generate_map_layout(seed, prior_session, profile)

        self.seed = layout["seed"]
        self.target_crossings = layout["target_crossings"]
        self.time_limit = layout["time_limit"]
        self.map_id = f"procedural_{self.seed}"
        self.n_h = layout["n_h"]
        self.n_v = layout["n_v"]
        self.difficulty = layout["difficulty"]
        self.analytics_zones = layout["analytics_zones"]
        self.traffic_weights = layout["traffic_weights"]
        self.path_estimate_s = layout["path_estimate_s"]
        self.light_cycle_scale = layout["difficulty"]["light_cycle_scale"]
        self.generation_meta = layout["generation"]

        super().__init__(layout["roads"], layout["start_pos"], layout["goal_rect"])


def generate_map(seed=None, prior_session=None, difficulty=None) -> ProceduralMap:
    return ProceduralMap(seed, prior_session, difficulty)
