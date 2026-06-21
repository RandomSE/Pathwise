"""Traffic spawn pipeline and car respawn queue."""

from __future__ import annotations

import random

from map_generation.traffic_schedule import (
    MIN_ALONG_GAP,
    PHASE_ONGOING,
    RECT_COLLIDE_PAD,
    TrafficSpawn,
    build_intersection_rects,
    edge_spawn_lane_allowed,
    lane_spawn_allowed,
    pose_overlaps_intersection_rects,
    spawn_poses_for_event,
)
from pathwise import sprites
from pathwise.car import (
    Car,
    CarSpatialIndex,
    CarSpawnOrigin,
    RespawnRequest,
    set_car_removed_callback,
)
from pathwise.geom import Rect, rect_overlap_area, rects_overlap
from pathwise.sim_constants import *  # noqa: F403

_SPAWN_ALONG_MIN_GAP = CAR_WIDTH * 2 + MIN_ALONG_GAP + 20

# Round-scoped globals wired by main.start_round
CAR_SPEED_MULT = 1.0
_round_city_block_rects: tuple[Rect, ...] = ()
_round_crosswalk_rects: tuple[Rect, ...] = ()
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
    crosswalk_rects: tuple[Rect, ...] = (),
) -> None:
    global CAR_SPEED_MULT, _round_city_block_rects, _round_crosswalk_rects
    global _frame_car_spatial, _frame_nearby_scratch
    CAR_SPEED_MULT = car_speed_mult
    _round_city_block_rects = city_block_rects
    _round_crosswalk_rects = crosswalk_rects
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


def _rect_overlap_area(a: Rect, b: Rect) -> int:
    return rect_overlap_area(a, b)


def _city_block_rects_from(city_blocks) -> tuple[Rect, ...]:
    if not city_blocks:
        return ()
    return tuple(
        Rect(int(block["x"]), int(block["y"]), int(block["w"]), int(block["h"]))
        for block in city_blocks
    )


def _spawn_probe_geometry(x: int, y: int, vertical: bool) -> tuple[Rect, Rect]:
    if vertical:
        w, h = CAR_HEIGHT, CAR_WIDTH
    else:
        w, h = CAR_WIDTH, CAR_HEIGHT
    rect = Rect(x, y, w, h)
    return rect, sprites.car_collision_rect(rect, vertical)


def _blocks_player_spawn_shell(shell: Rect, player_rect) -> bool:
    if player_rect is None:
        return False
    pb = sprites.player_body_hitbox(player_rect)
    zone = player_rect.inflate(PLAYER_SPAWN_PAD, PLAYER_SPAWN_PAD)
    return rects_overlap(shell, pb) or rects_overlap(shell, zone)


def _blocks_player_spawn(candidate: Car, player_rect) -> bool:
    return _blocks_player_spawn_shell(candidate._collision_shell, player_rect)


def _car_matches_travel(road, vertical: bool) -> bool:
    return (road.direction == "vertical" and not vertical) or (
        road.direction == "horizontal" and vertical
    )


def _spawn_probe_pose_valid(
    shell: Rect,
    rect: Rect,
    vertical: bool,
    roads,
    *,
    road_index: int | None = None,
    block_rects: tuple[Rect, ...] | None = None,
) -> bool:
    """Reject spawns mostly on sidewalks / blocks or barely on the lane."""
    area = max(1, shell.width * shell.height)
    if block_rects:
        block_limit = area * SPAWN_MAX_BLOCK_FRAC
        for br in block_rects:
            if _rect_overlap_area(shell, br) > block_limit:
                return False

    road_list: list
    if road_index is not None and 0 <= road_index < len(roads):
        road_list = [roads[road_index]]
    else:
        road_list = [r for r in roads if _car_matches_travel(r, vertical)]

    on_road = 0
    for road in road_list:
        if not _car_matches_travel(road, vertical):
            continue
        on_road += _rect_overlap_area(shell, road.rect)
    if on_road >= area * SPAWN_MIN_ROAD_FRAC:
        return True

    for road in road_list:
        if not _car_matches_travel(road, vertical):
            continue
        if road.direction == "vertical":
            if not (
                road.rect.top <= shell.centery <= road.rect.bottom
                and shell.centerx >= road.rect.left - CAR_WIDTH - 48
                and shell.centerx <= road.rect.right + CAR_WIDTH + 48
            ):
                continue
        else:
            if not (
                road.rect.left <= shell.centerx <= road.rect.right
                and shell.centery >= road.rect.top - CAR_HEIGHT - 48
                and shell.centery <= road.rect.bottom + CAR_HEIGHT + 48
            ):
                continue
        return True
    return False


def _car_spawn_pose_valid(candidate: Car, roads, city_blocks=None) -> bool:
    block_rects = _city_block_rects_from(city_blocks)
    return _spawn_probe_pose_valid(
        candidate._collision_shell,
        candidate.rect,
        candidate.vertical,
        roads,
        road_index=candidate.road_index,
        block_rects=block_rects,
    )


def _spawn_forward_lane_clear(
    rect: Rect,
    vertical: bool,
    direction: int,
    peers,
) -> bool:
    """True when no same-lane car is too close along the travel axis (either direction)."""
    along_len = CAR_HEIGHT if vertical else CAR_WIDTH
    need_gap = max(along_len + MIN_ALONG_GAP + 6, _SPAWN_ALONG_MIN_GAP)
    for other in peers:
        if other.vertical != vertical or other.direction != direction:
            continue
        if vertical:
            ahead = (other.rect.centery - rect.centery) * direction
            lane_gap = abs(other.rect.centerx - rect.centerx)
        else:
            ahead = (other.rect.centerx - rect.centerx) * direction
            lane_gap = abs(other.rect.centery - rect.centery)
        if lane_gap >= CAR_FOLLOW_LANE_GAP:
            continue
        if abs(ahead) < need_gap:
            return False
        if ahead < 0:
            closing = -ahead
            closing_speed = max(other.current_speed, CAR_CREEP_SPEED * 0.5)
            meet = need_gap + closing_speed * CAR_SPAWN_RAMP_FRAMES
            if closing < meet:
                return False
    return True


def _spawn_probe_blocked(
    shell: Rect,
    rect: Rect,
    vertical: bool,
    direction: int,
    road_index: int,
    cars_group,
    roads,
    intersection_zones=None,
    player_rect=None,
    block_rects: tuple[Rect, ...] | None = None,
    world_rect=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
) -> bool:
    if _blocks_player_spawn_shell(shell, player_rect):
        return True
    if not _spawn_probe_pose_valid(
        shell,
        rect,
        vertical,
        roads,
        road_index=road_index,
        block_rects=block_rects,
    ):
        return True
    for cw in _round_crosswalk_rects:
        if rects_overlap(shell, cw):
            return True
    if intersection_zones:
        for zone in intersection_zones:
            if rects_overlap(zone, shell):
                return True
            if rects_overlap(
                zone.inflate(INTERSECTION_APPROACH_SPAWN_PAD, INTERSECTION_APPROACH_SPAWN_PAD),
                shell,
            ):
                return True
    pad = RECT_COLLIDE_PAD + CAR_NEARBY_PAD
    if spatial is not None and scratch is not None:
        peers = spatial.nearby(shell, pad, scratch)
    else:
        peers = cars_group
    padded = shell.inflate(RECT_COLLIDE_PAD, RECT_COLLIDE_PAD)
    for other in peers:
        oc = other._collision_shell
        if rects_overlap(padded, oc):
            return True
        if other.turn_signal != 0 or other._turn_phase != "none":
            reserved = other._turn_reserved_rect(intersection_zones)
            if reserved is not None and rects_overlap(shell, reserved):
                return True
        if other.vertical == vertical and other.direction == direction:
            if vertical:
                ahead = (other.rect.centery - rect.centery) * direction
                lane_gap = abs(other.rect.centerx - rect.centerx)
            else:
                ahead = (other.rect.centerx - rect.centerx) * direction
                lane_gap = abs(other.rect.centery - rect.centery)
            along_len = CAR_HEIGHT if vertical else CAR_WIDTH
            along_need = max(along_len + MIN_ALONG_GAP + 6, _SPAWN_ALONG_MIN_GAP)
            if lane_gap < CAR_FOLLOW_LANE_GAP and abs(ahead) < along_need:
                return True
    return False


def _car_blocks_spawn(
    candidate: Car,
    cars_group,
    roads,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
    block_rects: tuple[Rect, ...] | None = None,
) -> bool:
    if block_rects is None:
        block_rects = _city_block_rects_from(city_blocks)
    road_index = candidate.road_index if candidate.road_index is not None else -1
    return _spawn_probe_blocked(
        candidate._collision_shell,
        candidate.rect,
        candidate.vertical,
        candidate.direction,
        road_index,
        cars_group,
        roads,
        intersection_zones,
        player_rect,
        block_rects,
        world_rect,
        spatial,
        scratch,
    )


def _spawn_car_from_event(
    event: TrafficSpawn,
    roads,
    cars_group,
    all_sprites_group,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    ix_rects=None,
    max_pose_tries: int | None = None,
    for_respawn: bool = False,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
) -> bool:
    road = roads[event.road_index]
    if event.phase == PHASE_ONGOING:
        queue_cap = 3 if for_respawn else EDGE_SPAWN_QUEUE_CAP
        if not edge_spawn_lane_allowed(
            cars_group,
            road,
            event.direction,
            world_rect,
            max_queue=queue_cap,
        ):
            return False
    elif not lane_spawn_allowed(cars_group, road, event.direction, event.phase):
        return False
    if ix_rects is None:
        ix_rects = build_intersection_rects(roads)
    poses = spawn_poses_for_event(road, event, ix_rects, world_rect)
    if max_pose_tries is not None:
        poses = poses[:max_pose_tries]
    block_rects = _round_city_block_rects or _city_block_rects_from(city_blocks)
    for x, y, direction_sign, vertical in poses:
        if pose_overlaps_intersection_rects(x, y, vertical, ix_rects):
            continue
        probe_rect, probe_shell = _spawn_probe_geometry(x, y, vertical)
        direction = 1 if direction_sign >= 0 else -1
        if _spawn_probe_blocked(
            probe_shell,
            probe_rect,
            vertical,
            direction,
            event.road_index,
            cars_group,
            roads,
            intersection_zones,
            player_rect,
            block_rects,
            world_rect,
            spatial,
            scratch,
        ):
            continue
        if spatial is not None and scratch is not None:
            lane_peers = spatial.nearby(
                probe_shell, CAR_NEARBY_PAD + _SPAWN_ALONG_MIN_GAP, scratch
            )
        else:
            lane_peers = cars_group
        if not _spawn_forward_lane_clear(probe_rect, vertical, direction, lane_peers):
            continue
        speed = CAR_SPEED * CAR_SPEED_MULT * direction_sign
        candidate = Car(
            x,
            y,
            speed,
            vertical=vertical,
            archetype_index=event.archetype_index,
            spawn_id=event.event_id,
            road_index=event.road_index,
        )
        candidate._spawn_origin = CarSpawnOrigin(
            event.road_index,
            1 if direction_sign >= 0 else -1,
            event.along_frac,
            event.phase,
        )
        cars_group.add(candidate)
        all_sprites_group.add(candidate)
        if intersection_zones:
            pad = INTERSECTION_APPROACH_SPAWN_PAD
            for zone in intersection_zones:
                if rects_overlap(
                    candidate._collision_shell,
                    zone.inflate(pad, pad),
                ):
                    candidate._spawn_clear_ix_frames = 90
                    break
        return True
    return False


def _queue_car_respawn(car: Car) -> None:
    global traffic_respawn_pending, round_frame
    origin = car._spawn_origin
    if origin is None:
        return
    if len(traffic_respawn_pending) >= RESPAWN_PENDING_CAP:
        traffic_respawn_pending.pop(0)
    traffic_respawn_pending.append(
        RespawnRequest(origin, _round_frame_getter() + RESPAWN_DELAY_FRAMES)
    )


def _cached_intersection_rects(roads, frame_id: int):
    global _ix_rects_cache, _ix_rects_cache_frame
    if _ix_rects_cache_frame != frame_id:
        _ix_rects_cache = build_intersection_rects(roads)
        _ix_rects_cache_frame = frame_id
    return _ix_rects_cache


def _process_car_respawns(
    target_frame: int,
    roads,
    cars,
    all_sprites,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
    ix_rects=None,
    spatial: CarSpatialIndex | None = None,
    scratch: list | None = None,
):
    global traffic_respawn_pending, traffic_respawn_event_id

    if not traffic_respawn_pending:
        return

    ready: list[RespawnRequest] = []
    waiting: list[RespawnRequest] = []
    for req in traffic_respawn_pending:
        if req.due_frame <= target_frame:
            ready.append(req)
        else:
            waiting.append(req)

    spawned = 0
    deferred: list[RespawnRequest] = []
    for req in ready:
        if spawned >= MAX_RESPAWNS_PER_FRAME:
            deferred.append(req)
            continue
        origin = req.origin
        traffic_respawn_event_id += 1
        event = TrafficSpawn(
            frame=0,
            road_index=origin.road_index,
            along_frac=origin.along_frac,
            direction=origin.direction,
            archetype_index=sprites.pick_random_archetype_index(),
            event_id=traffic_respawn_event_id,
            phase=origin.phase,
        )
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            max_pose_tries=RESPAWN_POSE_TRIES,
            for_respawn=True,
            spatial=spatial,
            scratch=scratch,
        ):
            spawned += 1
        else:
            deferred.append(
                RespawnRequest(origin, target_frame + RESPAWN_RETRY_FRAMES)
            )

    traffic_respawn_pending = waiting + deferred
    if len(traffic_respawn_pending) > RESPAWN_PENDING_CAP:
        traffic_respawn_pending = traffic_respawn_pending[-RESPAWN_PENDING_CAP:]


def _process_traffic_spawns_through_frame(
    target_frame: int,
    roads,
    cars,
    all_sprites,
    intersection_zones=None,
    player_rect=None,
    city_blocks=None,
    world_rect=None,
):
    global traffic_spawn_cursor, traffic_spawn_retry

    spawn_scratch = _frame_nearby_scratch
    ix_rects = _cached_intersection_rects(roads, target_frame)
    backlog = len(traffic_spawn_retry)
    spawn_budget = 6
    if backlog >= 16:
        spawn_budget = 2
    elif backlog >= 8:
        spawn_budget = 4
    retry_budget = SPAWN_RETRY_BUDGET_PER_FRAME
    if backlog >= 24:
        retry_budget = 1

    _process_car_respawns(
        target_frame,
        roads,
        cars,
        all_sprites,
        intersection_zones,
        player_rect,
        city_blocks,
        world_rect,
        ix_rects=ix_rects,
        spatial=_frame_car_spatial,
        scratch=spawn_scratch,
    )

    still_retry: list[TrafficSpawn] = []
    for event in traffic_spawn_retry:
        if spawn_budget <= 0 or retry_budget <= 0:
            still_retry.append(event)
            continue
        if event.frame > target_frame:
            still_retry.append(event)
            continue
        if target_frame - event.frame > MAX_SPAWN_DEFER_FRAMES:
            continue
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            spatial=_frame_car_spatial,
            scratch=spawn_scratch,
        ):
            spawn_budget -= 1
            retry_budget -= 1
            continue
        still_retry.append(event)
    traffic_spawn_retry = still_retry[:SPAWN_RETRY_SLOTS]

    while traffic_spawn_cursor < len(traffic_schedule) and spawn_budget > 0:
        event = traffic_schedule[traffic_spawn_cursor]
        if event.frame > target_frame:
            break
        lag = target_frame - event.frame
        if lag > MAX_SPAWN_DEFER_FRAMES:
            traffic_spawn_cursor += 1
            continue
        if _spawn_car_from_event(
            event,
            roads,
            cars,
            all_sprites,
            intersection_zones,
            player_rect,
            city_blocks,
            world_rect,
            ix_rects=ix_rects,
            spatial=_frame_car_spatial,
            scratch=spawn_scratch,
        ):
            traffic_spawn_cursor += 1
            spawn_budget -= 1
            continue
        if (
            lag < MAX_SPAWN_DEFER_FRAMES
            and len(still_retry) < SPAWN_RETRY_SLOTS
            and len(still_retry) < 32
        ):
            still_retry.append(event)
        traffic_spawn_cursor += 1




set_car_removed_callback(_queue_car_respawn)
