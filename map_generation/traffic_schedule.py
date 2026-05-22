"""Deterministic traffic spawn schedule from map seed and difficulty."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import commonUtils
import sprites
from map_generation.difficulty import DifficultyProfile
from map_generation.lane_geometry import lane_center_xy, lateral_axis_value

CAR_WIDTH = commonUtils.CAR_WIDTH
CAR_HEIGHT = commonUtils.CAR_HEIGHT
ARCHETYPE_COUNT = sprites.ARCHETYPE_COUNT
FPS = 60
ROAD_MARGIN = 36
MIN_ALONG_GAP = 22
FILL_FRACTION = 0.58
# Global 2x traffic vs original schedule (hard preset adds +50% via difficulty profile)
TRAFFIC_SCHEDULE_MULT = 2.0
# Round-start surge (phase "opening"): deterministic edge queue, staggered in time
INITIAL_FILL_FRACTION = 0.52
INITIAL_MAX_PER_DIR = 3
INITIAL_STAGGER_FRAMES = 3
OPENING_WARMUP_FRAMES = 120
MAX_LANE_ACTIVE_OPENING = 6
EDGE_CLEARANCE = 20
EDGE_QUEUE_SPACING = CAR_WIDTH + MIN_ALONG_GAP + 14
MAX_LANE_ACTIVE = 4
INTERSECTION_SPAWN_PAD = 28
MIN_CLEAR_GAP_FRAC = 0.10
RECT_COLLIDE_PAD = 8


PHASE_OPENING = "opening"
PHASE_ONGOING = "ongoing"


@dataclass(frozen=True)
class TrafficSpawn:
    frame: int
    road_index: int
    along_frac: float
    direction: int
    archetype_index: int
    event_id: int
    phase: str = PHASE_ONGOING


def _traffic_rng(map_seed: int, profile: DifficultyProfile, stream: int = 0) -> random.Random:
    """Separate streams keep opening vs ongoing RNG independent but seed-stable."""
    key = (
        int(map_seed)
        ^ (int(profile.spawn_rate_mult * 10000) << 7)
        ^ (int(profile.traffic_density * 10000) << 15)
        ^ (int(profile.level * 1_000_000) << 3)
        ^ (int(profile.round_escalation * 100_000))
        ^ (int(stream) * 0x9E37_79B9)
        ^ 0x7A4B_1C30
    ) & 0xFFFFFFFF
    return random.Random(key)


def _clamp_lateral_on_road(road, x: int, y: int) -> tuple[int, int]:
    """Keep the lateral axis inside the asphalt strip (avoids sidewalk overlap)."""
    pad = 4
    if road.direction == "vertical":
        y = max(road.rect.top + pad, min(y, road.rect.bottom - CAR_HEIGHT - pad))
    else:
        x = max(road.rect.left + pad, min(x, road.rect.right - CAR_WIDTH - pad))
    return x, y


def _along_coord(road, along_frac: float) -> int:
    frac = max(0.0, min(1.0, along_frac))
    if road.direction == "vertical":
        span = road.rect.width - ROAD_MARGIN * 2
        if span <= CAR_WIDTH + 20:
            return road.rect.centerx - CAR_WIDTH // 2
        return road.rect.left + ROAD_MARGIN + int(span * frac)
    span = road.rect.height - ROAD_MARGIN * 2
    if span <= CAR_HEIGHT + 20:
        return road.rect.centery - CAR_HEIGHT // 2
    return road.rect.top + ROAD_MARGIN + int(span * frac)


def car_pose_for_spawn(road, along_frac: float, direction: int) -> tuple[int, int, int, bool]:
    """Return x, y, signed speed sign (±1), vertical flag (speed magnitude applied by caller)."""
    direction = 1 if direction >= 0 else -1
    if road.direction == "vertical":
        x = _along_coord(road, along_frac)
        y = lateral_axis_value(road, direction) - CAR_HEIGHT // 2
        x, y = _clamp_lateral_on_road(road, x, y)
        return x, y, direction, False
    x = lateral_axis_value(road, direction) - CAR_WIDTH // 2
    y = _along_coord(road, along_frac)
    x, y = _clamp_lateral_on_road(road, x, y)
    return x, y, direction, True


def entry_along_frac(direction: int) -> float:
    """Nominal along-road fraction for this travel direction (used in schedule metadata)."""
    return 0.12 if direction >= 0 else 0.88


def car_pose_edge_entry(
    road, direction: int, queue_index: float = 0.0
) -> tuple[int, int, int, bool]:
    """
    Spawn just off the road so cars drive in (avoids intersection gridlock).
    queue_index stacks multiple same-direction spawns along the entry axis.
    """
    direction = 1 if direction >= 0 else -1
    q = int(queue_index * EDGE_QUEUE_SPACING)
    if road.direction == "vertical":
        y = lateral_axis_value(road, direction) - CAR_HEIGHT // 2
        if direction > 0:
            x = road.rect.left - CAR_WIDTH - EDGE_CLEARANCE - q
        else:
            x = road.rect.right + EDGE_CLEARANCE + q
        x, y = _clamp_lateral_on_road(road, x, y)
        return x, y, direction, False
    x = lateral_axis_value(road, direction) - CAR_WIDTH // 2
    if direction > 0:
        y = road.rect.top - CAR_HEIGHT - EDGE_CLEARANCE - q
    else:
        y = road.rect.bottom + EDGE_CLEARANCE + q
    x, y = _clamp_lateral_on_road(road, x, y)
    return x, y, direction, True


def count_lane_cars(cars, road, direction: int) -> int:
    """Live cars on this road traveling this way (prevents endless edge queues)."""
    direction = 1 if direction >= 0 else -1
    vertical = road.direction == "horizontal"
    zone = road.rect.inflate(48, 48)
    return sum(
        1
        for car in cars
        if car.vertical == vertical
        and car.direction == direction
        and zone.colliderect(car.rect)
    )


def lane_spawn_allowed(cars, road, direction: int, phase: str = PHASE_ONGOING) -> bool:
    cap = MAX_LANE_ACTIVE_OPENING if phase == PHASE_OPENING else MAX_LANE_ACTIVE
    return count_lane_cars(cars, road, direction) < cap


def edge_spawn_lane_allowed(
    cars,
    road,
    direction: int,
    world_rect,
    max_queue: int = 2,
) -> bool:
    """Ongoing edge spawns: only limit cars queued near the map entry, not whole-lane count."""
    if world_rect is None:
        return lane_spawn_allowed(cars, road, direction, PHASE_ONGOING)
    direction = 1 if direction >= 0 else -1
    vertical = road.direction == "horizontal"
    tcx, tcy = lane_center_xy(road, direction)
    depth = 340
    lateral = max(road.rect.width, road.rect.height) // 2 + 48
    queued = 0
    for car in cars:
        if car.vertical != vertical or car.direction != direction:
            continue
        if vertical:
            if abs(car.rect.centerx - tcx) > lateral:
                continue
            if direction > 0:
                if car.rect.bottom > world_rect.top + depth:
                    continue
            elif car.rect.top < world_rect.bottom - depth:
                continue
        else:
            if abs(car.rect.centery - tcy) > lateral:
                continue
            if direction > 0:
                if car.rect.right > world_rect.left + depth:
                    continue
            elif car.rect.left < world_rect.right - depth:
                continue
        queued += 1
    return queued < max_queue


def _largest_clear_gap(
    forbidden: list[tuple[float, float]],
) -> tuple[float, float] | None:
    if not forbidden:
        return 0.04, 0.96
    gaps: list[tuple[float, float]] = []
    prev = 0.0
    for f0, f1 in forbidden:
        if f0 - prev >= MIN_CLEAR_GAP_FRAC:
            gaps.append((prev, f0))
        prev = f1
    if 1.0 - prev >= MIN_CLEAR_GAP_FRAC:
        gaps.append((prev, 1.0))
    if not gaps:
        return None
    return max(gaps, key=lambda g: g[1] - g[0])


def _approach_pose_from_frac(
    road, frac: float, direction: int, queue_index: float = 0.0
) -> tuple[int, int, int, bool]:
    """Place car one vehicle length before `frac`, driving into the road (not in the box)."""
    x, y, d, vertical = car_pose_for_spawn(road, frac, direction)
    q = int(queue_index * EDGE_QUEUE_SPACING)
    if not vertical:
        if d > 0:
            x = x - CAR_WIDTH - EDGE_CLEARANCE - q
        else:
            x = x + CAR_WIDTH + EDGE_CLEARANCE + q
    else:
        if d > 0:
            y = y - CAR_HEIGHT - EDGE_CLEARANCE - q
        else:
            y = y + CAR_HEIGHT + EDGE_CLEARANCE + q
    x, y = _clamp_lateral_on_road(road, x, y)
    return x, y, d, vertical


def spawn_poses_from_world_edge(
    road,
    direction: int,
    world_rect,
    queue_slots: int = 6,
) -> list[tuple[int, int, int, bool]]:
    """Ongoing traffic: enter from outside the map boundary, drive inward."""
    direction = 1 if direction >= 0 else -1
    vertical = road.direction == "horizontal"
    tcx, tcy = lane_center_xy(road, direction)
    poses: list[tuple[int, int, int, bool]] = []
    for k in range(queue_slots):
        q = int(k * EDGE_QUEUE_SPACING)
        if not vertical:
            y = tcy
            if direction > 0:
                x = world_rect.left - CAR_WIDTH - EDGE_CLEARANCE - q
            else:
                x = world_rect.right + EDGE_CLEARANCE + q
        else:
            x = tcx
            if direction > 0:
                y = world_rect.top - CAR_HEIGHT - EDGE_CLEARANCE - q
            else:
                y = world_rect.bottom + EDGE_CLEARANCE + q
        x, y = _clamp_lateral_on_road(road, x, y)
        poses.append((x, y, direction, vertical))
    return poses


def spawn_poses_for_event(
    road,
    event: TrafficSpawn,
    intersection_rects: list[tuple[int, int, int, int]] | None = None,
    world_rect=None,
) -> list[tuple[int, int, int, bool]]:
    """
    Opening: spawn on open road inside the map.
    Ongoing: spawn outside the map edge and drive inward.
    """
    if event.phase == PHASE_ONGOING and world_rect is not None:
        return spawn_poses_from_world_edge(road, event.direction, world_rect)
    intersection_rects = intersection_rects or []
    direction = 1 if event.direction >= 0 else -1
    forbidden = _intersection_frac_ranges(road, intersection_rects)
    gap = _largest_clear_gap(forbidden)
    poses: list[tuple[int, int, int, bool]] = []
    if gap is not None:
        g0, g1 = gap
        span = g1 - g0
        for k in range(6):
            t = k / max(1, 5)
            if direction > 0:
                frac = g0 + 0.06 + t * max(0.0, span - 0.14)
            else:
                frac = g1 - 0.06 - t * max(0.0, span - 0.14)
            frac = max(g0 + 0.03, min(g1 - 0.03, frac))
            if _frac_in_ranges(frac, forbidden):
                continue
            poses.append(_approach_pose_from_frac(road, frac, direction, queue_index=float(k)))
    if not poses:
        for k in range(6):
            poses.append(car_pose_edge_entry(road, direction, queue_index=float(k)))
    return poses


def _candidate_rect_from_pose(x: int, y: int, vertical: bool) -> tuple[int, int, int, int]:
    if vertical:
        return (x, y, CAR_HEIGHT, CAR_WIDTH)
    return (x, y, CAR_WIDTH, CAR_HEIGHT)


def _candidate_rect(road, along_frac: float, direction: int) -> tuple[int, int, int, int]:
    x, y, _, vertical = car_pose_for_spawn(road, along_frac, direction)
    return _candidate_rect_from_pose(x, y, vertical)


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    pad = RECT_COLLIDE_PAD
    return (
        ax - pad < bx + bw
        and ax + aw + pad > bx
        and ay - pad < by + bh
        and ay + ah + pad > by
    )


def _along_metrics(road) -> tuple[int, int]:
    if road.direction == "vertical":
        return max(0, road.rect.width - ROAD_MARGIN * 2), CAR_WIDTH
    return max(0, road.rect.height - ROAD_MARGIN * 2), CAR_HEIGHT


def _max_cars_per_direction(road) -> int:
    span, car_len = _along_metrics(road)
    if span < car_len + MIN_ALONG_GAP:
        return 1
    return max(1, int(span // (car_len + MIN_ALONG_GAP)))


def _target_per_direction(road, density: float, *, initial: bool = False) -> int:
    cap = _max_cars_per_direction(road)
    frac = INITIAL_FILL_FRACTION if initial else FILL_FRACTION
    target = max(1, int(cap * frac * (0.88 + density * 0.18)))
    if initial:
        return min(target, INITIAL_MAX_PER_DIR)
    return target


def _build_intersection_rects(roads) -> list[tuple[int, int, int, int]]:
    rects: list[tuple[int, int, int, int]] = []
    vertical = [r for r in roads if r.direction == "vertical"]
    horizontal = [r for r in roads if r.direction == "horizontal"]
    for vr in vertical:
        for hr in horizontal:
            x = max(vr.rect.left, hr.rect.left)
            y = max(vr.rect.top, hr.rect.top)
            w = min(vr.rect.right, hr.rect.right) - x
            h = min(vr.rect.bottom, hr.rect.bottom) - y
            if w > 0 and h > 0:
                rects.append((x, y, w, h))
    return rects


def _spawn_rect_overlaps_intersection(
    road,
    along_frac: float,
    direction: int,
    intersection_rects: list[tuple[int, int, int, int]],
) -> bool:
    if not intersection_rects:
        return False
    x, y, w, h = _candidate_rect(road, along_frac, direction)
    pad = INTERSECTION_SPAWN_PAD
    for ix, iy, iw, ih in intersection_rects:
        if (
            x - pad < ix + iw
            and x + w + pad > ix
            and y - pad < iy + ih
            and y + h + pad > iy
        ):
            return True
    return False


def _intersection_frac_ranges(
    road, intersection_rects: list[tuple[int, int, int, int]]
) -> list[tuple[float, float]]:
    """Along-road fraction ranges to avoid (intersection boxes + car length margin)."""
    span, car_len = _along_metrics(road)
    if span <= 0:
        return []
    margin_px = car_len + MIN_ALONG_GAP + INTERSECTION_SPAWN_PAD
    ranges: list[tuple[float, float]] = []
    for ix, iy, iw, ih in intersection_rects:
        if road.direction == "vertical":
            z0 = ix - road.rect.left - ROAD_MARGIN
            z1 = ix + iw - road.rect.left - ROAD_MARGIN
        else:
            z0 = iy - road.rect.top - ROAD_MARGIN
            z1 = iy + ih - road.rect.top - ROAD_MARGIN
        f0 = max(0.0, (z0 - margin_px) / span)
        f1 = min(1.0, (z1 + margin_px) / span)
        if f1 > f0:
            ranges.append((f0, f1))
    ranges.sort()
    merged: list[tuple[float, float]] = []
    for f0, f1 in ranges:
        if merged and f0 <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], f1))
        else:
            merged.append((f0, f1))
    return merged


def _frac_in_ranges(frac: float, ranges: list[tuple[float, float]]) -> bool:
    return any(f0 <= frac <= f1 for f0, f1 in ranges)


def _safe_initial_fracs(road, forbidden: list[tuple[float, float]], slot_count: int) -> list[float]:
    candidates: list[float] = []
    for slot_i in range(1, slot_count + 1):
        candidates.append(slot_i / (slot_count + 1))
    for f in (0.10, 0.22, 0.78, 0.90):
        candidates.append(f)
    safe = [f for f in candidates if not _frac_in_ranges(f, forbidden)]
    return safe


def _same_lane_along_conflict(road, direction: int, frac_a: float, frac_b: float) -> bool:
    _, car_len = _along_metrics(road)
    return abs(_along_coord(road, frac_a) - _along_coord(road, frac_b)) < car_len + MIN_ALONG_GAP


def _lane_placements_conflict(
    road,
    direction: int,
    frac: float,
    lane_fracs: list[tuple[int, float]],
) -> bool:
    for other_dir, other_frac in lane_fracs:
        if other_dir != direction:
            continue
        if _same_lane_along_conflict(road, direction, frac, other_frac):
            return True
    return False


def _frac_clear_at_spawn(
    road,
    road_index: int,
    direction: int,
    frac: float,
    lane_fracs: dict[int, list[tuple[int, float]]],
    occupied_rects: list[tuple[int, int, int, int]],
    intersection_rects: list[tuple[int, int, int, int]] | None = None,
    forbidden_fracs: list[tuple[float, float]] | None = None,
) -> bool:
    if forbidden_fracs and _frac_in_ranges(frac, forbidden_fracs):
        return False
    if intersection_rects and _spawn_rect_overlaps_intersection(
        road, frac, direction, intersection_rects
    ):
        return False
    if _lane_placements_conflict(road, direction, frac, lane_fracs.get(road_index, [])):
        return False
    rect = _candidate_rect(road, frac, direction)
    return not any(_rects_overlap(rect, other) for other in occupied_rects)


def _alternate_fracs(base_frac: float, event_id: int, count: int = 12) -> list[float]:
    fracs = [base_frac]
    for k in range(1, count):
        offset = ((event_id * 37 + k * 19) % 200) / 200.0 * 0.28 - 0.14
        fracs.append(max(0.03, min(0.97, base_frac + offset)))
    return fracs


def _road_centrality_boost(roads) -> list[float]:
    if not roads:
        return []
    cx = sum(r.rect.centerx for r in roads) / len(roads)
    cy = sum(r.rect.centery for r in roads) / len(roads)
    dists = [math.hypot(r.rect.centerx - cx, r.rect.centery - cy) for r in roads]
    max_d = max(dists) or 1.0
    return [1.0 + 0.6 * (1.0 - d / max_d) for d in dists]


def _intersection_along_fracs(roads) -> list[tuple[int, float]]:
    vertical = [(i, r) for i, r in enumerate(roads) if r.direction == "vertical"]
    horizontal = [(i, r) for i, r in enumerate(roads) if r.direction == "horizontal"]
    anchors: list[tuple[int, float]] = []
    for vi, vr in vertical:
        for hi, hr in horizontal:
            zone = vr.rect.clip(hr.rect)
            if zone.width <= 0 or zone.height <= 0:
                continue
            v_span = max(1, vr.rect.width - ROAD_MARGIN * 2)
            h_span = max(1, hr.rect.height - ROAD_MARGIN * 2)
            v_frac = (zone.centerx - vr.rect.left - ROAD_MARGIN) / v_span
            h_frac = (zone.centery - hr.rect.top - ROAD_MARGIN) / h_span
            anchors.append((vi, max(0.06, min(0.94, v_frac))))
            anchors.append((hi, max(0.06, min(0.94, h_frac))))
    return anchors


def _weight(roads, traffic_weights, road_index: int) -> float:
    if traffic_weights and road_index < len(traffic_weights):
        return traffic_weights[road_index]
    road = roads[road_index]
    return float(getattr(road, "traffic_weight", 1.0))


def _try_place_initial_edge(
    events: list[TrafficSpawn],
    event_id: int,
    road_index: int,
    road,
    direction: int,
    queue_index: float,
    rng: random.Random,
    lane_fracs: dict[int, list[tuple[int, float]]],
    occupied_rects: list[tuple[int, int, int, int]],
    initial_spawn_index: int,
    intersection_rects: list[tuple[int, int, int, int]],
) -> int:
    forbidden = _intersection_frac_ranges(road, intersection_rects)
    gap = _largest_clear_gap(forbidden)
    if gap is None:
        return event_id
    g0, g1 = gap
    span = g1 - g0
    if direction > 0:
        frac = g0 + min(0.22, span * 0.35) + queue_index * 0.04
    else:
        frac = g1 - min(0.22, span * 0.35) - queue_index * 0.04
    frac = max(g0 + 0.04, min(g1 - 0.04, frac))
    if _frac_in_ranges(frac, forbidden):
        return event_id
    x, y, _, vertical = _approach_pose_from_frac(road, frac, direction, queue_index=0.0)
    rect = _candidate_rect_from_pose(x, y, vertical)
    if _spawn_rect_overlaps_intersection(road, frac, direction, intersection_rects):
        return event_id
    if any(_rects_overlap(rect, other) for other in occupied_rects):
        return event_id
    arch = sprites.pick_random_archetype_index(rng)
    frame = min(OPENING_WARMUP_FRAMES, initial_spawn_index * INITIAL_STAGGER_FRAMES)
    events.append(
        TrafficSpawn(
            frame=frame,
            road_index=road_index,
            along_frac=round(frac, 4),
            direction=direction,
            archetype_index=arch,
            event_id=event_id,
            phase=PHASE_OPENING,
        )
    )
    lane_fracs.setdefault(road_index, []).append((direction, frac))
    occupied_rects.append(rect)
    return event_id + 1


def _fill_road_initial(
    events: list[TrafficSpawn],
    event_id: int,
    road_index: int,
    road,
    rng: random.Random,
    density: float,
    lane_fracs: dict[int, list[tuple[int, float]]],
    occupied_rects: list[tuple[int, int, int, int]],
    initial_spawn_index: int,
    intersection_rects: list[tuple[int, int, int, int]],
) -> tuple[int, int]:
    per_dir = _target_per_direction(road, density, initial=True)

    for direction in (1, -1):
        placed = sum(
            1 for d, _ in lane_fracs.get(road_index, []) if d == direction
        )
        queue_slot = 0.0
        while placed < per_dir:
            next_id = _try_place_initial_edge(
                events,
                event_id,
                road_index,
                road,
                direction,
                queue_slot,
                rng,
                lane_fracs,
                occupied_rects,
                initial_spawn_index,
                intersection_rects,
            )
            if next_id == event_id:
                break
            event_id = next_id
            initial_spawn_index += 1
            placed += 1
            queue_slot += 1.0

    return event_id, initial_spawn_index


build_intersection_rects = _build_intersection_rects


def _generate_opening_surge(
    map_seed: int,
    roads,
    traffic_weights: list[float] | None,
    profile: DifficultyProfile,
) -> list[TrafficSpawn]:
    """Deterministic round-start burst: same seed => identical opening cars."""
    if not roads:
        return []

    rng = _traffic_rng(map_seed, profile, stream=1)
    density = profile.traffic_density * profile.spawn_rate_mult * TRAFFIC_SCHEDULE_MULT
    density *= 1.0 + profile.round_escalation * 0.4 + profile.level * 0.12

    events: list[TrafficSpawn] = []
    event_id = 0
    initial_spawn_index = 0
    lane_fracs: dict[int, list[tuple[int, float]]] = {}
    occupied_rects: list[tuple[int, int, int, int]] = []
    intersection_rects = _build_intersection_rects(roads)
    for ri, road in enumerate(roads):
        w = _weight(roads, traffic_weights, ri)
        road_density = density * (0.92 + 0.14 * w)
        event_id, initial_spawn_index = _fill_road_initial(
            events,
            event_id,
            ri,
            road,
            rng,
            road_density,
            lane_fracs,
            occupied_rects,
            initial_spawn_index,
            intersection_rects,
        )
    return events


def _generate_ongoing_spawns(
    map_seed: int,
    roads,
    traffic_weights: list[float] | None,
    profile: DifficultyProfile,
    time_limit_s: int,
    fps: int,
    start_frame: int,
    event_id_start: int,
) -> list[TrafficSpawn]:
    """Deterministic mid-round spawns after the opening surge window."""
    if not roads:
        return []

    rng = _traffic_rng(map_seed, profile, stream=2)
    num_roads = len(roads)
    density = profile.traffic_density * profile.spawn_rate_mult * TRAFFIC_SCHEDULE_MULT
    density *= 1.0 + profile.round_escalation * 0.4 + profile.level * 0.12

    max_active = min(500, 110 + num_roads * 34)
    duration_frames = max(fps * 30, int(time_limit_s * fps) + fps)

    events: list[TrafficSpawn] = []
    event_id = event_id_start
    interval = max(5, int(22 / max(0.45, density * (0.75 + num_roads * 0.02))))
    max_events = min(
        max_active * 3,
        int(max_active + duration_frames / interval * 1.15),
    )
    frame = start_frame
    road_cursor = 0
    while frame < duration_frames and len(events) < max_events:
        ri = road_cursor % num_roads
        road_cursor += 1
        w = _weight(roads, traffic_weights, ri)
        if rng.random() < min(0.98, 0.62 + 0.18 * w + density * 0.12):
            direction = rng.choice([1, -1])
            arch = sprites.pick_random_archetype_index(rng)
            events.append(
                TrafficSpawn(
                    frame=frame,
                    road_index=ri,
                    along_frac=entry_along_frac(direction),
                    direction=direction,
                    archetype_index=arch,
                    event_id=event_id,
                    phase=PHASE_ONGOING,
                )
            )
            event_id += 1
        frame += interval + rng.randint(0, 3)
    return events


def generate_traffic_schedule(
    map_seed: int,
    roads,
    traffic_weights: list[float] | None,
    profile: DifficultyProfile,
    time_limit_s: int,
    fps: int = FPS,
) -> list[TrafficSpawn]:
    """
    Fully procedural spawn timeline: same map_seed + profile => identical cars.
    Phase A (opening): surge at frame 0..OPENING_WARMUP_FRAMES.
    Phase B (ongoing): steady deterministic spawns for the rest of the round.
    """
    opening = _generate_opening_surge(map_seed, roads, traffic_weights, profile)
    opening_end = max((e.frame for e in opening), default=0)
    num_roads = len(roads)
    density = profile.traffic_density * profile.spawn_rate_mult * TRAFFIC_SCHEDULE_MULT
    density *= 1.0 + profile.round_escalation * 0.4 + profile.level * 0.12
    interval = max(5, int(22 / max(0.45, density * (0.75 + num_roads * 0.02))))
    next_event_id = max((e.event_id for e in opening), default=-1) + 1
    ongoing_start = opening_end + 2
    ongoing = _generate_ongoing_spawns(
        map_seed,
        roads,
        traffic_weights,
        profile,
        time_limit_s,
        fps,
        ongoing_start,
        next_event_id,
    )
    events = opening + ongoing
    events.sort(key=lambda e: (e.frame, e.road_index, e.event_id))
    return events


def spawn_along_candidates(event: TrafficSpawn) -> list[float]:
    """Legacy along fractions; runtime spawn uses spawn_poses_for_event instead."""
    direction = 1 if event.direction >= 0 else -1
    return _alternate_fracs(entry_along_frac(direction), event.event_id)
