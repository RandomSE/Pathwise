"""Procedural map orchestration: noise layout, validation, difficulty, analytics."""

from __future__ import annotations

import random

from pathwise.geom import Rect
from pathwise.map import MapBase, Road, make_rectangle, BASE_SIZE, ROAD_THICKNESS, ROAD_GAP
from pathwise import commonUtils

from map_generation.analytics import build_analytics_zones
from map_generation.constraints import (
    road_positions_valid,
    roads_fully_connected,
    traffic_density_balanced,
)
from map_generation.difficulty import DifficultyProfile, adaptive_difficulty
from map_generation.noise import fbm, simplex2
from map_generation.pathfinding import Cell, astar_route_estimate, bfs_solvable
from map_generation.safety import expected_wait_for_safe_crossing
from map_generation.spawn_placement import (
    pick_spawn_and_goal,
    placement_meets_distance,
    spawn_rng_for_attempt,
)
from pathwise.map_visuals import generate_city_blocks, generate_map_decorations

VERTICAL = commonUtils.VERTICAL
HORIZONTAL = commonUtils.HORIZONTAL

ORIGIN = 100
STRIDE = ROAD_THICKNESS + ROAD_GAP
MIN_ROAD_GAP = ROAD_THICKNESS + 36
MIN_SEGMENT_LEN = ROAD_THICKNESS + 48
MAX_GENERATION_ATTEMPTS = 128
JITTER_MAX = 28


def _effective_stride(difficulty: DifficultyProfile) -> float:
    return STRIDE * difficulty.stride_scale


def _effective_jitter(difficulty: DifficultyProfile) -> int:
    return int(JITTER_MAX * min(1.35, 0.85 + difficulty.stride_scale * 0.25))


def _spawn_clear(x: int, y: int, roads: list[Road], pad: int = 22) -> bool:
    probe = Rect(x - 12, y - 12, 24, 24)
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
    if total >= 8:
        n_h = max(3, min(total - 3, n_h))
        n_v = total - n_h
    return n_h, n_v


def _segment_span(
    index: int,
    count: int,
    inner_edges: list[int],
    world_start: int,
    world_end: int,
) -> tuple[int, int]:
    """
    Span between parallel roads, extended through each intersection strip so
    perpendicular segments still colliderect (required for connectivity checks).
    """
    if count == 0:
        return world_start, world_end
    if index == 0:
        return world_start, inner_edges[0] + ROAD_THICKNESS
    if index == count:
        return inner_edges[-1], world_end
    return inner_edges[index - 1], inner_edges[index] + ROAD_THICKNESS


def _build_segmented_roads(
    h_ys: list[int],
    v_xs: list[int],
    world_left: int,
    world_top: int,
    world_right: int,
    world_bottom: int,
) -> list[Road]:
    """
    Roads only between intersections (city blocks in between), not infinite cross-city spans.
    """
    roads: list[Road] = []
    for y in h_ys:
        for col in range(len(v_xs) + 1):
            left, right = _segment_span(col, len(v_xs), v_xs, world_left, world_right)
            width = right - left
            if width >= MIN_SEGMENT_LEN:
                roads.append(
                    Road(make_rectangle(left, y, width, ROAD_THICKNESS), VERTICAL)
                )
    for x in v_xs:
        for row in range(len(h_ys) + 1):
            top, bottom = _segment_span(row, len(h_ys), h_ys, world_top, world_bottom)
            height = bottom - top
            if height >= MIN_SEGMENT_LEN:
                roads.append(
                    Road(make_rectangle(x, top, ROAD_THICKNESS, height), HORIZONTAL)
                )
    return roads


def _jittered_axis_positions(
    count: int,
    seed: int,
    axis: str,
    stride: float,
    min_gap: int,
    jitter_max: int,
) -> list[int]:
    positions = []
    stride_i = int(round(stride))
    for i in range(count):
        jitter = int((simplex2(i * 0.9 + (1 if axis == "x" else 0), seed * 0.03, seed) - 0.5) * 2 * jitter_max)
        base = ORIGIN + (i + 1) * stride_i + jitter
        if positions and base <= positions[-1] + min_gap:
            base = positions[-1] + min_gap
        positions.append(base)
    return positions


def _traffic_weights(roads: list[Road], seed: int, difficulty: DifficultyProfile) -> list[float]:
    weights = []
    for idx, road in enumerate(roads):
        n = fbm(road.rect.centerx * 0.004, road.rect.centery * 0.004, seed + idx * 11)
        w = 0.35 + n * 0.9 + difficulty.traffic_density * 0.35
        weights.append(round(w, 3))
    return weights


def _compute_time_limit(travel_s: float, margin: float) -> int:
    """Round timer from sprint-route estimate with preset safety margin.

    Replaces the older (target_play_time / manhattan / min_time_limit_for_route)
    blend: timer is ceil(travel_s * route_time_margin), floored at 28s.
    travel_s already includes moderate-safe crossing waits from A*.
    """
    import math

    return max(28, int(math.ceil(travel_s * margin)))


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
    eff_stride = _effective_stride(difficulty)
    min_gap = int(MIN_ROAD_GAP * difficulty.stride_scale)
    jitter_max = _effective_jitter(difficulty)

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        n_h, n_v = _noise_partition(target_crossings, difficulty, rng, seed + attempt)
        h_ys = _jittered_axis_positions(n_h, seed + attempt * 3, "y", eff_stride, min_gap, jitter_max)
        v_xs = _jittered_axis_positions(n_v, seed + attempt * 5 + 1, "x", eff_stride, min_gap, jitter_max)

        if not road_positions_valid(h_ys, v_xs, min_gap):
            continue

        grid_extent = max(n_v, n_h) + 1
        margin = int(60 + 40 * difficulty.stride_scale)
        pad = int(180 + 80 * difficulty.stride_scale)
        world_left = ORIGIN - margin
        world_top = ORIGIN - margin
        world_right = ORIGIN + int(grid_extent * eff_stride) + pad
        world_bottom = ORIGIN + int(grid_extent * eff_stride) + pad
        span_w = world_right - world_left
        span_h = world_bottom - world_top

        roads = _build_segmented_roads(
            h_ys, v_xs, world_left, world_top, world_right, world_bottom
        )
        if not roads:
            continue

        if not roads_fully_connected(roads):
            continue

        traffic_weights = _traffic_weights(roads, seed + attempt, difficulty)
        if not traffic_density_balanced(traffic_weights):
            continue

        for road, weight in zip(roads, traffic_weights):
            road.traffic_weight = weight

        spawn_rng = spawn_rng_for_attempt(seed, attempt)
        placement = pick_spawn_and_goal(
            spawn_rng, n_v, n_h, difficulty.unpredictability
        )
        if not placement_meets_distance(placement, n_v, n_h):
            continue

        start_col = placement.start_cell.col
        start_row = placement.start_cell.row
        goal_col = placement.goal_cell.col
        goal_row = placement.goal_cell.row

        start_cell = placement.start_cell
        goal_cell = placement.goal_cell
        if not bfs_solvable(start_cell, goal_cell, n_v, n_h):
            continue

        crossing_wait = expected_wait_for_safe_crossing(difficulty.light_cycle_scale)
        route_estimate = astar_route_estimate(
            start_cell, goal_cell, n_v, n_h, crossing_wait, eff_stride
        )
        if route_estimate is None:
            continue
        travel_s, route_crossings = route_estimate
        time_limit = _compute_time_limit(travel_s, difficulty.route_time_margin)

        sx = _block_center_x(start_col, v_xs, ORIGIN, world_right)
        sy = _block_center_y(start_row, h_ys, ORIGIN, world_bottom)
        gx = _block_center_x(goal_col, v_xs, ORIGIN, world_right)
        gy = _block_center_y(goal_row, h_ys, ORIGIN, world_bottom)

        goal_rect = Rect(gx - BASE_SIZE // 2, gy - BASE_SIZE // 2, BASE_SIZE, BASE_SIZE)
        if not _spawn_clear(sx, sy, roads) or not _spawn_clear(gx, gy, roads):
            continue
        if any(goal_rect.colliderect(r.rect.inflate(4, 4)) for r in roads):
            continue

        analytics_zones = build_analytics_zones(roads, h_ys, v_xs, (sx, sy), goal_rect)
        city_blocks = generate_city_blocks(
            h_ys, v_xs, world_left, world_top, world_right, world_bottom, seed + attempt
        )
        decorations = generate_map_decorations(city_blocks, seed + attempt)

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
            "city_blocks": city_blocks,
            "decorations": decorations,
            "path_estimate_s": round(travel_s, 2),
            "route_crossings": route_crossings,
            "generation": {
                "attempt": attempt,
                "noise_jitter": jitter_max,
                "stride_px": round(eff_stride, 1),
                "solver": "astar+bfs",
                "safe_crossing_model": "light_cycle",
                **placement.metadata,
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
        self.route_crossings = layout.get("route_crossings", 0)
        self.light_cycle_scale = layout["difficulty"]["light_cycle_scale"]
        self.generation_meta = layout["generation"]
        self.city_blocks = layout.get("city_blocks", [])
        self.decorations = layout.get("decorations", [])
        self.world_bounds_hint = None

        super().__init__(layout["roads"], layout["start_pos"], layout["goal_rect"])


def generate_map(seed=None, prior_session=None, difficulty=None) -> ProceduralMap:
    return ProceduralMap(seed, prior_session, difficulty)
