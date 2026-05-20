"""Left-hand traffic turn vectors and exit-road selection at intersections."""

from __future__ import annotations

import math
import random

from map_generation.lane_geometry import lane_center_xy


def travel_vector(vertical: bool, direction: int) -> tuple[int, int]:
    direction = 1 if direction >= 0 else -1
    if not vertical:
        return (direction, 0)
    return (0, direction)


def left_vector(vertical: bool, direction: int) -> tuple[int, int]:
    """Screen coords (y down): left side of travel."""
    fx, fy = travel_vector(vertical, direction)
    return (fy, -fx)


def drive_from_vector(vx: int, vy: int) -> tuple[bool, int]:
    if vx != 0:
        return False, 1 if vx > 0 else -1
    return True, 1 if vy > 0 else -1


def turn_vector(vertical: bool, direction: int, turn_side: int) -> tuple[int, int]:
    if turn_side < 0:
        return left_vector(vertical, direction)
    if turn_side > 0:
        lv = left_vector(vertical, direction)
        return (-lv[0], -lv[1])
    return travel_vector(vertical, direction)


def exit_options(
    roads,
    zone,
    entry_vertical: bool,
    entry_direction: int,
    turn_side: int,
) -> list[tuple[int, int, bool]]:
    """(road_index, direction_sign, vertical) for each valid exit matching turn_side."""
    tvx, tvy = turn_vector(entry_vertical, entry_direction, turn_side)
    out: list[tuple[int, int, bool]] = []
    seen: set[tuple[int, int, bool]] = set()
    for idx, road in enumerate(roads):
        if not zone.colliderect(road.rect):
            continue
        for d in (1, -1):
            vertical = road.direction == "horizontal"
            vx, vy = travel_vector(vertical, d)
            if (vx, vy) != (tvx, tvy):
                continue
            key = (idx, d, vertical)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def pick_turn_side(rng: random.Random, turn_chance: float = 0.38) -> int:
    """0 = straight, -1 = left, 1 = right (left-hand rules)."""
    if rng.random() >= turn_chance:
        return 0
    return -1 if rng.random() < 0.5 else 1


def choose_exit(
    roads,
    zone,
    entry_vertical: bool,
    entry_direction: int,
    turn_side: int,
    car_center: tuple[int, int],
    entry_road_index: int | None,
) -> tuple[int, int, bool] | None:
    opts = exit_options(roads, zone, entry_vertical, entry_direction, turn_side)
    if not opts:
        return None
    cx, cy = car_center
    if turn_side == 0:
        best = None
        best_score = -1e9
        fx, fy = travel_vector(entry_vertical, entry_direction)
        for idx, d, vertical in opts:
            if entry_road_index is not None and idx == entry_road_index:
                score = 50.0
            else:
                lx, ly = lane_center_xy(roads[idx], d)
                score = (lx - cx) * fx + (ly - cy) * fy
            if score > best_score:
                best_score = score
                best = (idx, d, vertical)
        return best
    best = None
    best_dist = 1e9
    for idx, d, vertical in opts:
        lx, ly = lane_center_xy(roads[idx], d)
        dist = math.hypot(lx - cx, ly - cy)
        if dist < best_dist:
            best_dist = dist
            best = (idx, d, vertical)
    return best


def turn_target_point(roads, road_index: int, direction: int, vertical: bool) -> tuple[int, int]:
    return lane_center_xy(roads[road_index], direction)


def pivot_center_at_intersection(
    roads,
    zone,
    road_index: int,
    direction: int,
    vertical: bool,
) -> tuple[int, int]:
    """Lane-aligned center in the box, nudged slightly along the exit arm."""
    road = roads[road_index]
    px, py = lane_center_xy(road, direction)
    fx, fy = travel_vector(vertical, direction)
    px += fx * 18
    py += fy * 18
    if road.direction == "vertical":
        py = max(road.rect.top + 14, min(py, road.rect.bottom - 14))
        px = max(road.rect.left + 14, min(px, road.rect.right - 14))
    else:
        px = max(road.rect.left + 14, min(px, road.rect.right - 14))
        py = max(road.rect.top + 14, min(py, road.rect.bottom - 14))
    return int(px), int(py)
