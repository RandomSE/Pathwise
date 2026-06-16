"""Vehicle entity, spatial index, and lane-peer helpers."""

from __future__ import annotations

import math
import random

from dataclasses import dataclass

from map_generation.intersection_routing import (
    choose_exit,
    pick_turn_side,
    pivot_center_at_intersection,
    travel_vector,
    turn_side_from_exit,
)
from map_generation.lane_geometry import clamp_keep_left_xy, lane_center_xy
from map_generation.turn_clearance import bezier_point as _bezier_xy
from map_generation.turn_clearance import corridor_bounds as _turn_corridor_bounds
from map_generation.turn_clearance import sample_bezier as _sample_bezier_xy
from map_generation.traffic_schedule import MIN_ALONG_GAP, RECT_COLLIDE_PAD
from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect, collide, clip_rect, contains_rect, rect_overlap_area, rects_overlap
from pathwise.sim_constants import *  # noqa: F403
import pathwise.sim_constants as _tune

_car_removed_callback = None
_traffic_map_seed = 0
_intersection_zones_shell: list = []


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp_angle_deg(a: float, b: float, t: float) -> float:
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * t


def _turn_arc_delta_deg(start: float, end: float, turn_side: int) -> float:
    """Signed rotation from start→end that follows blinker side (not shortest arc)."""
    delta = (end - start + 180.0) % 360.0 - 180.0
    if turn_side == 0:
        return delta
    if turn_side > 0 and delta < 0:
        delta += 360.0
    elif turn_side < 0 and delta > 0:
        delta -= 360.0
    return delta


def _lerp_turn_angle_deg(
    start: float, end: float, t: float, turn_side: int
) -> float:
    return start + _turn_arc_delta_deg(start, end, turn_side) * t


def _rect_overlap_area(a: Rect, b: Rect) -> int:
    return rect_overlap_area(a, b)


def set_traffic_map_seed(seed: int) -> None:
    global _traffic_map_seed
    _traffic_map_seed = int(seed)


def set_intersection_zones_shell(zones_shell: list) -> None:
    global _intersection_zones_shell
    _intersection_zones_shell = list(zones_shell)


def set_car_removed_callback(callback) -> None:
    global _car_removed_callback
    _car_removed_callback = callback


def _notify_car_removed(car: "Car") -> None:
    if _car_removed_callback is not None:
        _car_removed_callback(car)


@dataclass(frozen=True)
class CarSpawnOrigin:
    """Entry point for respawn when a car is removed (unchanged after turns)."""
    road_index: int
    direction: int
    along_frac: float
    phase: str


@dataclass(frozen=True)
class RespawnRequest:
    origin: CarSpawnOrigin
    due_frame: int


class CarSpatialIndex:
    """Uniform grid so each car only checks nearby peers (not the full fleet)."""

    __slots__ = ("cell", "_cells", "_stamp", "_rebuild_counter")

    def __init__(self, cell_size: int = SPATIAL_CELL):
        self.cell = cell_size
        self._cells: dict[tuple[int, int], list] = {}
        self._stamp = 0
        self._rebuild_counter = 0

    def clear(self) -> None:
        self._cells.clear()

    def _cell_keys_for_shell(self, shell: Rect) -> list[tuple[int, int]]:
        cs = self.cell
        x0 = shell.left // cs
        x1 = shell.right // cs
        y0 = shell.top // cs
        y1 = shell.bottom // cs
        keys: list[tuple[int, int]] = []
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                keys.append((cx, cy))
        return keys

    def _remove_car_from_cells(self, car) -> None:
        keys = getattr(car, "_spatial_cell_keys", ())
        if not keys:
            return
        cells = self._cells
        for key in keys:
            bucket = cells.get(key)
            if bucket is not None:
                while car in bucket:
                    bucket.remove(car)
                if not bucket:
                    del cells[key]
        car._spatial_cell_keys = ()
        car._spatial_stamp = 0

    def _insert_car_into_cells(self, car) -> None:
        if not car.alive():
            self._remove_car_from_cells(car)
            return
        shell = car._collision_shell
        cells = self._cells
        keys = self._cell_keys_for_shell(shell)
        for key in keys:
            bucket = cells.get(key)
            if bucket is None:
                cells[key] = [car]
            elif car not in bucket:
                bucket.append(car)
        car._spatial_cell_keys = tuple(keys)

    def relocate_car(self, car) -> None:
        self._remove_car_from_cells(car)
        self._insert_car_into_cells(car)

    def rebuild(self, car_list) -> None:
        self._rebuild_counter += 1
        if len(car_list) > 80:
            for car in car_list:
                if car.alive():
                    self.relocate_car(car)
                else:
                    self._remove_car_from_cells(car)
            return
        cells = self._cells
        for bucket in cells.values():
            bucket.clear()
        for car in car_list:
            if not car.alive():
                car._spatial_cell_keys = ()
                continue
            self._insert_car_into_cells(car)

    def _gather(self, rect: Rect, pad: int, out: list) -> list:
        out.clear()
        self._stamp += 1
        if self._stamp > 1_000_000_000:
            self._stamp = 1
        stamp = self._stamp
        cs = self.cell
        r = rect.inflate(pad, pad)
        x0 = r.left // cs
        x1 = r.right // cs
        y0 = r.top // cs
        y1 = r.bottom // cs
        cells = self._cells
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for car in cells.get((cx, cy), ()):
                    if car._spatial_stamp == stamp:
                        continue
                    car._spatial_stamp = stamp
                    out.append(car)
        return out

    def nearby(self, rect: Rect, pad: int, scratch: list) -> list:
        return self._gather(rect, pad, scratch)


_frame_car_spatial = CarSpatialIndex()
_frame_nearby_scratch: list = []
_frame_player_car_scratch: list = []
_frame_lane_scratch: list = []
_frame_car_list_scratch: list = []
_frame_draw_sprites_scratch: list = []


def _resolve_all_shell_overlaps(car_list: list) -> None:
    """One deterministic separation pass after all cars move."""
    if not ENABLE_CAR_CAR_SOFT_AVOIDANCE:
        return
    alive = sorted((c for c in car_list if c.alive()), key=lambda c: c.spawn_id)
    _resolve_arc_turn_shell_overlaps(alive)
    sep_passes = 1 if len(alive) > _tune.SHELL_SEP_FLEET_THRESHOLD else _tune.SHELL_PENETRATION_PASSES
    for car in alive:
        # Arc turners stay on the Bezier; post-frame nudging causes visible path jitter.
        if car._turn_phase in ("turning", "settling"):
            continue
        car._resolve_shell_penetration(
            alive,
            max_nudge=SHELL_PENETRATION_MAX_NUDGE,
            passes=sep_passes,
        )
    for car in alive:
        if car._turn_phase in ("turning", "settling") or car.current_speed >= 0.25:
            continue
        car._sync_collision_shell()
        for other in alive:
            if other is car or other.current_speed >= 0.25:
                continue
            if other._turn_phase in ("turning", "settling"):
                continue
            if collide(car._collision_shell, other._collision_shell):
                car._resolve_shell_penetration(
                    alive,
                    max_nudge=max(SHELL_PENETRATION_MAX_NUDGE, 12),
                    passes=2,
                )
                break


def _resolve_arc_turn_shell_overlaps(car_list: list) -> None:
    """When two arc turners overlap, lower spawn_id keeps priority; higher backs up."""
    turners = [
        c
        for c in car_list
        if c.alive() and c._turn_phase in ("turning", "settling")
    ]
    for car in turners:
        for _ in range(6):
            blocked = False
            car._sync_collision_shell()
            for other in car_list:
                if other is car or not other.alive():
                    continue
                if other._turn_phase in ("to_hub", "turning", "settling"):
                    continue
                if other.current_speed >= 0.35:
                    continue
                if not collide(car._collision_shell, other._collision_shell):
                    continue
                car._backup_turn_arc(max(car.base_speed * 0.35, 0.75))
                car.speed = 0.0
                car.current_speed = 0.0
                blocked = True
            if not blocked:
                break
    if len(turners) < 2:
        return
    turners.sort(key=lambda c: c.spawn_id)
    for i, car in enumerate(turners):
        for other in turners[i + 1 :]:
            if not rects_overlap(car._collision_shell, other._collision_shell):
                continue
            if rect_overlap_area(car._collision_shell, other._collision_shell) < 6:
                continue
            if car.spawn_id < other.spawn_id:
                other._yield_turn_arc_from_peer_overlap([car])
            else:
                car._yield_turn_arc_from_peer_overlap([other])


# --- Entities ---
class Car(Entity):
    def __init__(
        self,
        x,
        y,
        speed,
        vertical=False,
        archetype_index=None,
        spawn_id=0,
        road_index=None,
        spawn_origin: CarSpawnOrigin | None = None,
    ):
        super().__init__()
        self.direction = 1 if speed >= 0 else -1
        self.vertical = vertical
        self.spawn_id = spawn_id
        self.road_index = road_index
        self._spawn_origin = spawn_origin
        if archetype_index is None:
            archetype_index = sprites.pick_random_archetype_index()
        self.archetype_index = archetype_index
        self.image = sprites.make_car_surface(
            vertical=vertical,
            direction=self.direction,
            archetype_index=self.archetype_index,
        )
        self.rect = Rect(x, y, self.image.get_width(), self.image.get_height())
        self.base_speed = abs(speed)
        self.acceleration = 0.16
        self.brake_strength = 0.42
        self.honk_until = 0.0
        self._last_honk_time = -999.0
        self.honk_risk_pending = False
        self.honk_reason = None
        self._stopped_frames = 0
        self._intersection_stuck_frames = 0
        self._gridlock_frames = 0
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_hold_frames = 0
        self._turn_reservation_frames = 0
        self._spawn_age = 0
        self.turn_signal = 0
        self._turn_zone_key = None
        self._turn_exit = None
        self._turn_hub = None
        self._turn_phase = "none"
        self._turn_blend = 0.0
        self._turn_px = 0.0
        self._turn_py = 0.0
        self._turn_side = max(CAR_WIDTH, CAR_HEIGHT)
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_display_angle = 0.0
        self._turn_arc_start = (0.0, 0.0)
        self._turn_arc_mid = (0.0, 0.0)
        self._turn_arc_end = (0.0, 0.0)
        self._turn_settle_blend = 0.0
        self._turn_settle_target = (0.0, 0.0)
        self._turn_entry_vertical = vertical
        self._turn_entry_direction = self.direction
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_peer_stall_frames = 0
        self._turn_arc_age = 0
        self._turn_arc_side = 0
        self._turn_snap_travel = 0.0
        self._turn_snap_px = 0.0
        self._turn_snap_py = 0.0
        self._turn_abort_cooldown = 0
        self._off_road_frames = 0
        self._spatial_stamp = 0
        self._spatial_cell_keys: tuple = ()
        self._shell_sync_key = None
        self._body_rect_scratch = Rect(0, 0, self.rect.width, self.rect.height)
        self._frame_move_peers: list | None = None
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)
        self._last_good_center = self.rect.center
        self.current_speed = 0.0
        self.speed = 0.0

    def _effective_travel(self) -> tuple[bool, int]:
        if self._turn_phase in ("to_hub", "turning", "settling") and self._turn_exit:
            return self._turn_entry_vertical, self._turn_entry_direction
        return self.vertical, self.direction

    def _sync_collision_shell(self, force: bool = False):
        if self._turn_phase in ("turning", "settling"):
            cx, cy = round(self._turn_px), round(self._turn_py)
            key = (cx, cy, self._turn_side, 2)
            if not force and key == self._shell_sync_key:
                return
            self._shell_sync_key = key
            body = Rect(0, 0, self._turn_side, self._turn_side)
            body.center = (cx, cy)
            self._collision_shell = sprites.car_collision_rect_turn(body)
            return
        key = (self.rect.x, self.rect.y, 0, self.vertical)
        if not force and key == self._shell_sync_key:
            return
        self._shell_sync_key = key
        self._collision_shell = sprites.car_collision_rect(self.rect, self.vertical)

    def _snap_center_to_left_lane(self, roads, max_nudge: int | None = 8):
        """Align to keep-left lane center on the axis perpendicular to travel."""
        if max_nudge == 0:
            return
        if self.road_index is None or self.road_index >= len(roads):
            return
        road = roads[self.road_index]
        tcx, tcy = lane_center_xy(road, self.direction)
        if road.direction == "vertical":
            if max_nudge is None:
                self.rect.centery = tcy
            else:
                dy = max(-max_nudge, min(max_nudge, tcy - self.rect.centery))
                self.rect.centery += dy
        else:
            if max_nudge is None:
                self.rect.centerx = tcx
            else:
                dx = max(-max_nudge, min(max_nudge, tcx - self.rect.centerx))
                self.rect.centerx += dx

    def _shell_hits_any_car(self, rect, vertical, peers, shell: Rect | None = None) -> bool:
        if shell is None:
            shell = sprites.car_collision_rect_into(rect, vertical, self._body_rect_scratch)
        for other in peers:
            if other is self:
                continue
            if collide(shell, other._collision_shell):
                return True
        return False

    def is_honking(self, game_time):
        return game_time < self.honk_until

    def trigger_honk(self, game_time, reason):
        if game_time - self._last_honk_time < HONK_COOLDOWN:
            return False
        self.honk_until = game_time + HONK_DURATION
        self._last_honk_time = game_time
        self.honk_reason = reason
        return True

    def _player_in_travel_lane(self, player_body_rect):
        if self.vertical:
            lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
            ahead = (player_body_rect.centery - self.rect.centery) * self.direction
        else:
            lane_gap = abs(player_body_rect.centery - self.rect.centery)
            ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
        return lane_gap < 55 and 0 < ahead < 250

    def _player_blocking_lane(self, player_body_rect):
        if collide(self._collision_shell, player_body_rect):
            return True
        if self.vertical:
            lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
            ahead = (player_body_rect.centery - self.rect.centery) * self.direction
        else:
            lane_gap = abs(player_body_rect.centery - self.rect.centery)
            ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
        return lane_gap < 50 and 0 <= ahead < 130

    def evaluate_honk(
        self, player_body_rect, player_on_crosswalk: bool, honk_allowed: bool, game_time
    ):
        self.honk_risk_pending = False
        if not honk_allowed:
            return

        too_close = collide(
            self._collision_shell.inflate(HONK_CLOSE_PAD, HONK_CLOSE_PAD),
            player_body_rect,
        )
        blocked_by_player = (
            self.current_speed < self.base_speed * 0.25
            and self._player_blocking_lane(player_body_rect)
        )
        jaywalking = (
            not player_on_crosswalk
            and self._player_in_travel_lane(player_body_rect)
            and self.current_speed >= self.base_speed * 0.15
        )

        if too_close and self.trigger_honk(game_time, "close"):
            self.honk_risk_pending = True
        elif blocked_by_player and self.trigger_honk(game_time, "blocked"):
            self.honk_risk_pending = True
        elif jaywalking and self.trigger_honk(game_time, "jaywalk"):
            self.honk_risk_pending = True

    def _distance_to_other(self, other):
        v, d = self._effective_travel()
        my = self._collision_shell
        ot = other._collision_shell
        if v:
            ahead = (ot.centery - my.centery) * d
            lane_gap = abs(ot.centerx - my.centerx)
        else:
            ahead = (ot.centerx - my.centerx) * d
            lane_gap = abs(ot.centery - my.centery)
        return ahead, lane_gap

    def _apply_lane_follow_speed(self, lane_peers, desired_speed: float) -> float:
        """Match speed to slower traffic ahead in-lane (no hard stop)."""
        for other in lane_peers:
            if other is self or other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other):
                continue
            ahead, _lane_gap = self._distance_to_other(other)
            if ahead <= 0 or ahead > CAR_SOFT_FOLLOW_RANGE:
                continue
            if ahead < 20:
                follow_cap = 0.0 if other.current_speed < 0.4 else other.current_speed * 0.65
                desired_speed = min(desired_speed, follow_cap)
            else:
                follow_cap = other.current_speed * max(0.45, (ahead - 16) / 80)
                desired_speed = min(desired_speed, max(follow_cap, CAR_CREEP_SPEED))
        return desired_speed

    def _other_in_active_turn(self, other) -> bool:
        """Only committed turn phases block peers — blinkers alone must not gridlock."""
        return other._turn_phase in ("to_hub", "turning", "settling")

    def _committed_intersection_turn(self, intersection_zones) -> bool:
        """Turn plan committed only when executing the arc or signaling inside the box."""
        if self._turn_phase in ("turning", "settling"):
            return True
        if not intersection_zones:
            return False
        if self._turn_phase == "to_hub":
            if self._rect_in_intersection(self.rect, intersection_zones):
                return self.current_speed >= 0.12
            if self._turn_hub is not None and self.current_speed >= 0.12:
                hx, hy = self._turn_hub
                dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
                lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
                return dist <= lead + 8
            return False
        return (
            self.turn_signal != 0
            and self._turn_exit is not None
            and self._turn_phase == "to_hub"
            and self._rect_in_intersection(self.rect, intersection_zones)
            and self.current_speed >= 0.12
        )

    def _conflicts_with_committed_turner(
        self, other, intersection_zones, *, pad: int = 10
    ) -> bool:
        if not other._committed_intersection_turn(intersection_zones):
            return False
        if intersection_zones and not self._approaching_or_in_intersection(
            intersection_zones
        ):
            return False
        if rects_overlap(self._collision_shell, other._collision_shell):
            return True
        return rects_overlap(
            self._collision_shell.inflate(pad, pad),
            other._collision_shell.inflate(pad, pad),
        )

    def _planned_move_conflicts_active_turn(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        """Block on turner shells; corridor reservation only for same-axis + active arc."""
        if self._turn_phase in ("to_hub", "turning", "settling"):
            return False
        my = sprites.car_collision_rect_into(
            next_rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            oc = other._collision_shell
            if other._committed_intersection_turn(intersection_zones):
                if rects_overlap(my.inflate(28, 28), oc):
                    return True
                if other._turn_phase in ("turning", "settling") and intersection_zones:
                    reserved = other._turn_reserved_rect(intersection_zones)
                    if reserved is not None and rects_overlap(my, reserved):
                        return True
                continue
            if rects_overlap(my, oc):
                if other._turn_phase in ("to_hub", "turning", "settling"):
                    return True
                continue
            if other._turn_phase not in ("turning", "settling"):
                continue
            if other.vertical != self.vertical:
                continue
            if intersection_zones:
                reserved = other._turn_reserved_rect(intersection_zones)
                if reserved is not None and rects_overlap(my, reserved):
                    return True
        return False

    def _both_active_turn_peers_at_intersection(
        self, other, intersection_zones
    ) -> bool:
        if self._turn_phase not in ("to_hub", "turning", "settling"):
            return False
        if other._turn_phase not in ("to_hub", "turning", "settling"):
            return False
        if not intersection_zones:
            return True
        self_ix = self._rect_in_intersection(self.rect, intersection_zones) or (
            self._approaching_or_in_intersection(intersection_zones)
        )
        other_ix = other._rect_in_intersection(other.rect, intersection_zones) or (
            other._approaching_or_in_intersection(intersection_zones)
        )
        return self_ix and other_ix

    def _turn_side_for_exit_plan(
        self, exit_plan=None, *, entry_vertical=None, entry_direction=None
    ) -> int:
        """Map a committed exit arm to left/right/straight for replanning."""
        plan = exit_plan if exit_plan is not None else self._turn_exit
        if plan is None:
            return 0
        _idx, d, exit_vertical = plan
        ev = (
            self._turn_entry_vertical
            if entry_vertical is None
            else entry_vertical
        )
        ed = (
            self._turn_entry_direction
            if entry_direction is None
            else entry_direction
        )
        return turn_side_from_exit(ev, ed, exit_vertical, d)

    def _replan_turn_at_zone(
    self,
    roads,
    zone,
    key,
    peers,
    player_body_rect,
    ped_legal_crossing: bool,
    *,
    intended_exit=None,
    intended_signal: int = 0,
        ) -> bool: 
            """Retry turn planning without flipping blinker to the opposite direction."""
            if self._turn_phase in ("turning", "settling"):
                if intended_exit is not None and intended_exit == self._turn_exit:
                    self._prime_turn_arc_geometry(roads, zone)
                    return True
                return False
            if intended_exit is not None and intended_signal != 0:
                turn_side = self._turn_side_for_exit_plan(intended_exit)
                if turn_side != 0:
                    return self._apply_turn_plan_for_side(
                        roads,
                        zone,
                        key,
                        turn_side,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                    )
            # Only retry the intended signal or straight — NEVER the opposite direction.
            if intended_signal != 0:
                candidates = [intended_signal, 0]
            else:
                candidates = [0]
            for turn_side in candidates:
                if self._apply_turn_plan_for_side(
                    roads,
                    zone,
                    key,
                    turn_side,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                ):
                    return True
            return False

    def _probe_turn_shell_overlaps_peer(self, peers, cx: float, cy: float) -> bool:
        shell = self._turn_probe_shell(cx, cy)
        for other in peers:
            if other is self or not other.alive():
                continue
            if collide(shell, other._collision_shell):
                return True
        return False

    def _turn_replay_rect(self) -> Rect:
        """Match replay draw bounds used by frame_recorder for arc turners."""
        if self._turn_phase in ("turning", "settling"):
            cx = round(float(self._turn_px))
            cy = round(float(self._turn_py))
        else:
            cx, cy = self.rect.center
        return Rect(cx - CAR_WIDTH // 2, cy - CAR_HEIGHT // 2, CAR_WIDTH, CAR_HEIGHT)

    def _turn_replay_rect_overlaps_peer(self, peers) -> bool:
        if self._turn_phase not in ("turning", "settling"):
            return False
        my = self._turn_replay_rect()
        for other in peers:
            if other is self or not other.alive():
                continue
            if other._turn_phase not in ("turning", "settling"):
                continue
            if rects_overlap(my, other._turn_replay_rect()):
                return True
        return False

    def _turn_shell_overlaps_peer(
        self, peers, intersection_zones=None
    ) -> bool:
        shell = self._collision_shell
        for other in peers:
            if other is self or not other.alive():
                continue
            if collide(shell, other._collision_shell):
                return True
        return False

    def _backup_turn_arc(self, backup_px: float) -> None:
        if self._turn_phase != "turning" or self._turn_arc_len <= 0:
            return
        self._turn_arc_travel = max(0.0, self._turn_arc_travel - backup_px)
        t = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
        ease = _smoothstep(min(1.0, t))
        cx, cy = self._bezier_point(ease)
        angle = _lerp_angle_deg(
            self._turn_angle_start, self._turn_angle_end, ease
        )
        self._set_turn_visual(angle, cx, cy)
        self._sync_collision_shell(force=True)

    def _yield_turn_arc_from_peer_overlap(self, peers) -> bool:
        """Lower spawn_id has priority; back up along the arc until shells separate."""
        for other in peers:
            if other is self or not other.alive():
                continue
            if other._turn_phase not in ("turning", "settling"):
                continue
            if not collide(self._collision_shell, other._collision_shell):
                continue
            if other.spawn_id < self.spawn_id:
                self._backup_turn_arc(max(self.base_speed * 0.5, 1.0))
                self.speed = 0.0
                self.current_speed = 0.0
                return True
        return False

    def _mitigate_turn_peer_deadlock(
        self, peers, intersection_zones, roads
    ) -> None:
        """Higher spawn_id yields when two turners overlap in the same intersection."""
        if self._turn_phase not in ("to_hub", "turning", "settling"):
            self._turn_peer_stall_frames = 0
            return
        blocked_by_priority_peer = False
        for other in peers:
            if other is self or not other.alive():
                continue
            if not self._both_active_turn_peers_at_intersection(
                other, intersection_zones
            ):
                continue
            if not rects_overlap(self._collision_shell, other._collision_shell):
                continue
            if other.spawn_id < self.spawn_id:
                blocked_by_priority_peer = True
                break
        if blocked_by_priority_peer:
            self._turn_peer_stall_frames += 1
            self._yield_turn_arc_from_peer_overlap(peers)
        elif self.current_speed >= 0.45:
            self._turn_peer_stall_frames = max(0, self._turn_peer_stall_frames - 2)
        else:
            self._turn_peer_stall_frames = 0
        yield_frames = TURN_PEER_YIELD_FRAMES
        if self._turn_phase in ("turning", "settling"):
            yield_frames = max(8, TURN_PEER_YIELD_FRAMES // 2)
        if self._turn_peer_stall_frames >= yield_frames:
            if self._turn_phase in ("turning", "settling") and intersection_zones:
                zone = self._intersection_zone_at(intersection_zones)
                if zone is not None:
                    self._freeze_blocked_turn_in_intersection(
                        intersection_zones,
                        roads,
                        peers,
                        Rect(0, 0, 1, 1),
                        True,
                        zone,
                    )
            elif self._turn_phase not in ("turning", "settling"):
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                )
            self._turn_peer_stall_frames = 0

    def _soft_overlap_creep_cap(
        self, next_rect, move_peers, lane_peers, intersection_zones=None
    ) -> float | None:
        """Max creep speed when the planned move still overlaps another car shell."""
        ix_creep = self._intersection_stuck_frames >= INTERSECTION_STUCK_CREEP_FRAMES
        if intersection_zones and self._planned_move_conflicts_active_turn(
            next_rect, move_peers, intersection_zones
        ):
            if ix_creep:
                return CAR_CREEP_SPEED * 0.45
            return 0.0
        if not self._shell_hits_any_car(next_rect, self.vertical, move_peers):
            return None
        my = sprites.car_collision_rect(next_rect, self.vertical)
        for other in move_peers:
            if other is self:
                continue
            if self._other_in_active_turn(other) and rects_overlap(
                my, other._collision_shell
            ):
                return 0.0
        min_gap = 1e9
        for other in lane_peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_BLOCK_LANE_GAP):
                continue
            gap, _ = self._distance_to_other(other)
            if gap > 0:
                min_gap = min(min_gap, gap)
        if min_gap <= CAR_SOFT_STOP_GAP:
            if ix_creep:
                return CAR_CREEP_SPEED * 0.3
            return 0.0
        if min_gap < 28:
            return CAR_CREEP_SPEED * 0.35
        if min_gap < 52:
            return CAR_CREEP_SPEED * 0.7
        return CAR_CREEP_SPEED

    def _same_lane(self, other, max_lane_gap=CAR_FOLLOW_LANE_GAP):
        sv, sd = self._effective_travel()
        ov, od = other._effective_travel()
        if sv != ov or sd != od:
            return False
        _, lane_gap = self._distance_to_other(other)
        return lane_gap < max_lane_gap

    def _in_crosswalk_lane(self, state):
        if self.vertical:
            return abs(self.rect.centerx - state["crosswalk"].centerx) < 50
        return abs(self.rect.centery - state["crosswalk"].centery) < 50

    def _distance_to_intersection_entry(self, zone):
        """Distance along travel to intersection entry; None if past or wrong side."""
        if self.vertical:
            if self.direction > 0:
                if self.rect.top >= zone.bottom:
                    return None
                return zone.top - self.rect.bottom
            if self.rect.bottom <= zone.top:
                return None
            return self.rect.top - zone.bottom
        if self.direction > 0:
            if self.rect.left >= zone.right:
                return None
            return zone.left - self.rect.right
        if self.rect.right <= zone.left:
            return None
        return self.rect.left - zone.right

    def _zone_on_entry_route(self, zone, roads) -> bool:
        if self.road_index is not None and 0 <= self.road_index < len(roads):
            return collide(roads[self.road_index].rect, zone)
        for road in roads:
            if self._matches_road_travel(road) and collide(road.rect, zone):
                return True
        return False

    def _intersection_zone_for_turn_planning(self, intersection_zones, roads):
        if not intersection_zones:
            return None
        in_zone = self._intersection_zone_at(intersection_zones)
        if in_zone is not None:
            return in_zone
        best = None
        best_d = 1e9
        for zone in intersection_zones:
            if not self._zone_on_entry_route(zone, roads):
                continue
            d = self._distance_to_intersection_entry(zone)
            if d is None or d < 0 or d > TURN_SIGNAL_LEAD_DIST:
                continue
            if d < best_d:
                best_d = d
                best = zone
        return best

    def _approaching_or_in_intersection(self, intersection_zones, extra: int = 0) -> bool:
        if not intersection_zones:
            return False
        if self._rect_in_intersection(self.rect, intersection_zones):
            return True
        lead = TURN_SIGNAL_LEAD_DIST + extra
        for zone in intersection_zones:
            d = self._distance_to_intersection_entry(zone)
            if d is not None and 0 <= d < lead:
                return True
        return False

    def _pivot_exit_clear(
        self,
        roads,
        zone,
        exit_plan,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        idx, d, vertical = exit_plan
        px, py = pivot_center_at_intersection(roads, zone, idx, d, vertical)
        if vertical:
            pw, ph = CAR_HEIGHT, CAR_WIDTH
        else:
            pw, ph = CAR_WIDTH, CAR_HEIGHT
        probe = Rect(0, 0, pw, ph)
        probe.center = (px, py)
        probe_shell = sprites.car_collision_rect(probe, vertical)
        if ENABLE_CAR_CAR_COLLISION:
            for other in peers:
                if other is self:
                    continue
                if collide(probe_shell, other._collision_shell):
                    return False
            if not ped_legal_crossing and collide(probe_shell, player_body_rect):
                return False
        return True

    def _planned_turn_is_protected(self) -> bool:
        if self.turn_signal != 0:
            return True
        if not self._turn_exit:
            return False
        idx, d, exit_vertical = self._turn_exit
        entry_v = (
            self._turn_entry_vertical
            if self._turn_phase in ("turning", "settling")
            else self.vertical
        )
        entry_d = (
            self._turn_entry_direction
            if self._turn_phase in ("turning", "settling")
            else self.direction
        )
        return turn_side_from_exit(entry_v, entry_d, exit_vertical, d) != 0

    def _uses_turn_approach_light(self) -> bool:
        if self.turn_signal != 0:
            return True
        if self._turn_phase in ("to_hub", "turning", "settling"):
            return self._planned_turn_is_protected()
        return False

    def _effective_approach_light(self, state: dict) -> str:
        if self._uses_turn_approach_light():
            return state.get("turn_light_state", state.get("light_state", "green"))
        return state.get("light_state", "green")

    def _effective_seconds_to_change(self, state: dict) -> float:
        if self._uses_turn_approach_light():
            return float(state.get("turn_seconds_to_change", 0.0))
        return float(state.get("seconds_to_change", 0.0))

    def _maintain_turn_plan(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        road_states=None,
    ) -> None:
        """Drop stale turn plans that block traffic or never start."""
        if self._turn_phase == "to_hub":
            self._turn_wait_frames += 1
            if self._turn_wait_frames >= TURN_TO_HUB_WAIT_ABORT_FRAMES:
                self._turn_phase = "none"
                self._turn_hub = None
                self._turn_wait_frames = 0
                self._turn_blocked_frames = 0
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                )
                return
            if self._turn_exit and not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones=intersection_zones,
            ):
                if self._turn_wait_frames >= TURN_PATH_BLOCKED_ABORT_FRAMES:
                    self._hold_turn_and_replan(
                        intersection_zones,
                        roads,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                    )
                return
            return
        if self._turn_phase in ("turning", "settling"):
            overlapped = self._turn_replay_rect_overlaps_peer(
                peers
            ) or self._turn_shell_overlaps_peer(peers, intersection_zones)
            if overlapped:
                self._turn_overlap_frames += 1
            elif self._turn_overlap_frames > 0:
                self._turn_overlap_frames = max(0, self._turn_overlap_frames - 2)
            if not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                t_max=0.35,
                intersection_zones=intersection_zones,
            ):
                self._turn_overlap_frames += 1
            if self._turn_overlap_frames >= 1:
                yield_to_peer = False
                for other in peers:
                    if other is self or not other.alive():
                        continue
                    if other._turn_phase not in ("turning", "settling"):
                        continue
                    if not (
                        rects_overlap(
                            self._turn_replay_rect(), other._turn_replay_rect()
                        )
                        or collide(self._collision_shell, other._collision_shell)
                    ):
                        continue
                    if other.spawn_id < self.spawn_id:
                        yield_to_peer = True
                        break
                if yield_to_peer:
                    self._exit_turn_visual_keep_plan()
            return
        if self.turn_signal == 0 and self._turn_exit is None:
            self._turn_wait_frames = 0
            return
        if self.current_speed >= 0.35:
            self._turn_wait_frames = 0
            return
        stalled_in_ix = (
            intersection_zones
            and self._turn_phase == "none"
            and self.turn_signal != 0
            and self._rect_in_intersection(self.rect, intersection_zones)
            and self.current_speed < 0.2
        )
        stuck_turn_plan = (
            self._turn_phase == "none"
            and self.turn_signal != 0
            and self._turn_exit is not None
            and self.current_speed < 0.2
        )
        if road_states and self._uses_turn_approach_light() and not (
            stalled_in_ix or stuck_turn_plan
        ):
            approach = self._nearest_approach_state(road_states)
            if (
                approach is not None
                and self._effective_approach_light(approach) == "green"
                and self._turn_path_clear(
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                    intersection_zones=intersection_zones,
                )
            ):
                self._turn_wait_frames = max(0, self._turn_wait_frames - 3)
                return
        self._turn_wait_frames += 1
        if self._turn_exit and not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        ):
            if self._turn_wait_frames >= TURN_PATH_BLOCKED_ABORT_FRAMES:
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                )
            return
        if self._turn_wait_frames >= TURN_SIGNAL_STUCK_FRAMES:
            zone = self._intersection_zone_for_turn_planning(
                intersection_zones, roads
            )
            if zone is None:
                zone = self._intersection_zone_at(intersection_zones)
            if (
                zone is not None
                and (
                    self._occupies_intersection(zone)
                    or (
                        stuck_turn_plan
                        and self._turn_wait_frames >= TURN_SIGNAL_STUCK_FRAMES * 2
                    )
                )
                and self._turn_wait_frames >= TURN_SIGNAL_STUCK_FRAMES * 2
            ):
                key = (zone.x, zone.y, zone.w, zone.h)
                committed = False
                for turn_side in (-1, 1, 0):
                    if turn_side == self.turn_signal:
                        continue
                    if not self._apply_turn_plan_for_side(
                        roads,
                        zone,
                        key,
                        turn_side,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                    ):
                        continue
                    if turn_side == 0 or self._begin_turn_steer(
                        roads,
                        zone,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                        intersection_zones=intersection_zones,
                    ):
                        committed = True
                        break
                if not committed:
                    self._apply_turn_plan_for_side(
                        roads,
                        zone,
                        key,
                        0,
                        peers,
                        player_body_rect,
                        ped_legal_crossing,
                    )
                self._turn_wait_frames = 0
            else:
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                )

    def _hold_turn_and_replan(
        self,
        intersection_zones,
        roads,
        peers=None,
        player_body_rect=None,
        ped_legal_crossing: bool = True,
    ) -> None:
        """Blocked turn: stop and wait — keep blinker/plan, retry when path may clear."""
        peers = peers or []
        if player_body_rect is None:
            player_body_rect = Rect(0, 0, 1, 1)
        # Mid-arc: never cancel/replan (replay continuity); pause on the Bezier instead.
        if self._turn_phase in ("turning", "settling"):
            zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
            if zone is None:
                zone = self._intersection_zone_at(intersection_zones)
            if zone is not None:
                self._freeze_blocked_turn_in_intersection(
                    intersection_zones,
                    roads,
                    peers,
                    player_body_rect,
                    ped_legal_crossing,
                    zone,
                )
            else:
                self.speed = 0.0
                self.current_speed = 0.0
                self._set_turn_visual(
                    self._turn_display_angle, self._turn_px, self._turn_py
                )
                self._sync_collision_shell(force=True)
            return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        in_ix = zone is not None and self._occupies_intersection(zone)
        committed_turn = self._turn_phase in ("turning", "settling") or (
            self._turn_phase == "to_hub" and in_ix
        )
        if committed_turn and in_ix:
            self._freeze_blocked_turn_in_intersection(
                intersection_zones,
                roads,
                peers,
                player_body_rect,
                ped_legal_crossing,
                zone,
            )
            return

        intended_signal = self.turn_signal
        intended_exit = self._turn_exit
        was_visual_turn = self._turn_phase in ("turning", "settling")
        if was_visual_turn:
            self._cancel_turn_visual()
        if self._turn_phase == "to_hub":
            self._turn_phase = "none"
            self._turn_hub = None
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_hold_frames += 1
        if self._turn_hold_frames >= TURN_HOLD_ZONE_RESET_FRAMES:
            self._turn_zone_key = None
        self.turn_signal = intended_signal
        self._turn_exit = intended_exit
        if zone is not None and not was_visual_turn:
            # Only clamp if the car hasn't moved far past the zone entry edge;
            # large overshoots mean the car is already inside the box and should
            # clear it rather than be snapped backward (which causes a teleport).
            if self.vertical:
                if self.direction > 0:
                    overshoot = self.rect.bottom - (zone.top - STOP_LINE_GAP)
                else:
                    overshoot = (zone.bottom + STOP_LINE_GAP) - self.rect.top
            else:
                if self.direction > 0:
                    overshoot = self.rect.right - (zone.left - STOP_LINE_GAP)
                else:
                    overshoot = (zone.right + STOP_LINE_GAP) - self.rect.left
            if overshoot <= max(CAR_WIDTH, CAR_HEIGHT):
                self._clamp_before_intersection(zone)
        if zone is not None and (
            self._turn_hold_frames == 1
            or self._turn_hold_frames % TURN_HOLD_RETRY_FRAMES == 0
        ):
            key = (zone.x, zone.y, zone.w, zone.h)
            self._replan_turn_at_zone(
                roads,
                zone,
                key,
                peers,
                player_body_rect,
                ped_legal_crossing,
                intended_exit=intended_exit,
                intended_signal=intended_signal,
            )
        self.current_speed = 0.0
        self.speed = 0.0

    def _exit_turn_visual_keep_plan(self) -> None:
        """Drop arc sprite only; keep blinker/exit so the turn retries when the box clears."""
        if self._turn_phase not in ("turning", "settling") or not self._turn_exit:
            return
        signal = self.turn_signal
        exit_plan = self._turn_exit
        zone_key = self._turn_zone_key
        snap = (
            self._turn_arc_travel,
            self._turn_arc_len,
            self._turn_angle_start,
            self._turn_angle_end,
            self._turn_arc_start,
            self._turn_arc_mid,
            self._turn_arc_end,
            self._turn_entry_vertical,
            self._turn_entry_direction,
            float(self._turn_px),
            float(self._turn_py),
            self._turn_arc_side,
        )
        self._cancel_turn_visual()
        (
            self._turn_arc_travel,
            self._turn_arc_len,
            self._turn_angle_start,
            self._turn_angle_end,
            self._turn_arc_start,
            self._turn_arc_mid,
            self._turn_arc_end,
            self._turn_entry_vertical,
            self._turn_entry_direction,
            self._turn_snap_px,
            self._turn_snap_py,
            self._turn_arc_side,
        ) = snap
        self._turn_snap_travel = self._turn_arc_travel
        self.turn_signal = signal
        self._turn_exit = exit_plan
        self._turn_zone_key = zone_key
        self._turn_hold_frames = TURN_PEER_YIELD_FRAMES
        self._turn_stall_frames = 0
        self._turn_blocked_frames = 0
        self._turn_overlap_frames = 0
        self._turn_arc_age = 0
        self.speed = 0.0
        self.current_speed = 0.0

    def _resume_snapped_turn_arc(self, peers=None) -> bool:
        if self._turn_phase != "none" or self._turn_arc_len <= 0 or self._turn_snap_travel <= 0:
            return False
        self._turn_arc_travel = self._turn_snap_travel
        t = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
        ease = _smoothstep(min(1.0, t))
        angle = _lerp_turn_angle_deg(
            self._turn_angle_start,
            self._turn_angle_end,
            ease,
            self._turn_arc_side,
        )
        self._turn_phase = "turning"
        self._set_turn_visual(angle, self._turn_snap_px, self._turn_snap_py)
        self._sync_collision_shell(force=True)
        if peers:
            for other in peers:
                if other is self or not other.alive():
                    continue
                if other._turn_phase in ("turning", "settling") and rects_overlap(
                    self._turn_replay_rect(), other._turn_replay_rect()
                ):
                    self._turn_phase = "none"
                    self._turn_hold_frames = TURN_PEER_YIELD_FRAMES
                    return False
        return True

    def _can_resume_turn_arc(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones,
    ) -> bool:
        if self._turn_hold_frames <= 0 or not self._turn_exit:
            return False
        if self._turn_phase == "none":
            if self._turn_snap_travel <= 0:
                return False
            for other in peers:
                if other is self or not other.alive():
                    continue
                if other._turn_phase in ("turning", "settling"):
                    if rects_overlap(self.rect, other._turn_replay_rect()):
                        return False
                    if collide(self.rect, other._collision_shell):
                        return False
            return self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones=intersection_zones,
            )
        if self._turn_phase not in ("turning", "settling"):
            return False
        if self._turn_shell_overlaps_peer(peers, intersection_zones):
            return False
        return self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        )

    def _try_resume_turn_after_block(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones,
    ) -> None:
        if self._turn_hold_frames <= 0:
            return
        if not self._can_resume_turn_arc(
            peers, player_body_rect, ped_legal_crossing, intersection_zones
        ):
            return
        self._turn_hold_frames = 0
        self._turn_stall_frames = 0
        self._turn_blocked_frames = 0
        self._turn_stall_center = None
        self._turn_peer_stall_frames = 0
        self._turn_arc_age = 0
        if self._turn_phase == "none":
            self._resume_snapped_turn_arc(peers)

    def _freeze_blocked_turn_in_intersection(
        self,
        intersection_zones,
        roads,
        peers,
        player_body_rect,
        ped_legal_crossing,
        zone,
    ) -> None:
        """Pause mid-turn inside the intersection without snapping back to the stop line."""
        if self._turn_hold_frames >= TURN_HOLD_RETRY_FRAMES * 2:
            if self._turn_shell_overlaps_peer(peers, intersection_zones):
                self._exit_turn_visual_keep_plan()
            else:
                self._pause_turn_commitment()
            return
        self._yield_turn_arc_from_peer_overlap(peers)
        intended_signal = self.turn_signal
        intended_exit = self._turn_exit
        self._turn_hold_frames += 1
        self._turn_wait_frames = 0
        self._turn_blocked_frames = max(0, self._turn_blocked_frames - 2)
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_overlap_frames = max(0, self._turn_overlap_frames - 2)
        self.turn_signal = intended_signal
        self._turn_exit = intended_exit
        self.speed = 0.0
        self.current_speed = 0.0
        if self._turn_phase == "turning" and self._turn_arc_len > 0:
            t = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
            ease = _smoothstep(min(1.0, t))
            angle = _lerp_turn_angle_deg(
                self._turn_angle_start,
                self._turn_angle_end,
                ease,
                self._turn_arc_side,
            )
            self._set_turn_visual(angle, self._turn_px, self._turn_py)
        elif self._turn_phase == "settling":
            self._set_turn_visual(
                self._turn_display_angle, self._turn_px, self._turn_py
            )
        self._sync_collision_shell(force=True)
        if self._turn_hold_frames % TURN_HOLD_RETRY_FRAMES == 0:
            key = (zone.x, zone.y, zone.w, zone.h)
            self._replan_turn_at_zone(
                roads,
                zone,
                key,
                peers,
                player_body_rect,
                ped_legal_crossing,
                intended_exit=intended_exit,
                intended_signal=intended_signal,
            )
        self._try_resume_turn_after_block(
            peers, player_body_rect, ped_legal_crossing, intersection_zones
        )

    def _pause_turn_commitment(self) -> None:
        """Hold the arc pose and turn plan until cross traffic clears — do not go straight."""
        self._turn_hold_frames = max(1, self._turn_hold_frames)
        self._turn_stall_frames = 0
        self._turn_blocked_frames = 0
        self._turn_overlap_frames = max(0, self._turn_overlap_frames - 2)
        self._turn_peer_stall_frames = 0
        self.speed = 0.0
        self.current_speed = 0.0
        if self._turn_phase == "turning" and self._turn_arc_len > 0:
            t = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
            ease = _smoothstep(min(1.0, t))
            angle = _lerp_turn_angle_deg(
                self._turn_angle_start,
                self._turn_angle_end,
                ease,
                self._turn_arc_side,
            )
            self._set_turn_visual(angle, self._turn_px, self._turn_py)
            self._sync_collision_shell(force=True)
        elif self._turn_phase == "settling":
            self._set_turn_visual(
                self._turn_display_angle, self._turn_px, self._turn_py
            )
            self._sync_collision_shell(force=True)

    def _cancel_turn_visual(self) -> None:
        px = float(self._turn_px) if self._turn_phase in ("turning", "settling") else float(
            self.rect.centerx
        )
        py = float(self._turn_py) if self._turn_phase in ("turning", "settling") else float(
            self.rect.centery
        )
        self._turn_phase = "none"
        self._turn_hub = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_settle_blend = 0.0
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._refresh_car_sprite()
        self.rect.center = (round(px), round(py))
        self._sync_collision_shell(force=True)

    def _abort_turn(self):
        was_visual_turn = self._turn_phase in ("turning", "settling")
        self.turn_signal = 0
        self._turn_wait_frames = 0
        self._turn_overlap_frames = 0
        self._turn_hold_frames = 0
        self._turn_exit = None
        self._turn_phase = "none"
        self._turn_hub = None
        self._turn_zone_key = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_start = 0.0
        self._turn_angle_end = 0.0
        self._turn_angle_draw_q = -999
        self._turn_settle_blend = 0.0
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_peer_stall_frames = 0
        self._turn_abort_cooldown = TURN_ABORT_COOLDOWN_FRAMES
        if was_visual_turn:
            self._refresh_car_sprite()
            self._sync_collision_shell(force=True)

    def _occupies_intersection(self, zone: Rect) -> bool:
        """True when body, shell, or arc center is inside the intersection box."""
        if collide(self.rect, zone) or collide(self._collision_shell, zone):
            return True
        if self._turn_phase in ("turning", "settling"):
            cx, cy = self._turn_px, self._turn_py
            side = max(12, int(self._turn_side * 0.35))
            probe = Rect(0, 0, side, side)
            probe.center = (round(cx), round(cy))
            return collide(probe, zone)
        return False

    def _clamp_before_intersection(self, zone):
        if self.vertical:
            if self.direction > 0:
                self.rect.bottom = zone.top - STOP_LINE_GAP
            else:
                self.rect.top = zone.bottom + STOP_LINE_GAP
        else:
            if self.direction > 0:
                self.rect.right = zone.left - STOP_LINE_GAP
            else:
                self.rect.left = zone.right + STOP_LINE_GAP

    def _cap_next_rect_same_lane(self, next_rect, peers):
        """
        Never allow next_rect to overlap a same-direction car ahead in-lane.
        Uses shell hitboxes (matches drawn car body).
        """
        g = CAR_FOLLOW_SEP
        my = sprites.car_collision_rect_into(
            next_rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_FOLLOW_LANE_GAP):
                continue
            ahead, _ = self._distance_to_other(other)
            if ahead <= 0:
                continue
            oc = other._collision_shell
            if self.vertical:
                if self.direction > 0:
                    if my.bottom > oc.top - g:
                        next_rect.y -= my.bottom - (oc.top - g)
                else:
                    if my.top < oc.bottom + g:
                        next_rect.y += (oc.bottom + g) - my.top
            else:
                if self.direction > 0:
                    if my.right > oc.left - g:
                        next_rect.x -= my.right - (oc.left - g)
                else:
                    if my.left < oc.right + g:
                        next_rect.x += (oc.right + g) - my.left
        return next_rect

    def _peers_may_block_move(self, next_rect, peers) -> bool:
        my = sprites.car_collision_rect_into(
            next_rect, self.vertical, self._body_rect_scratch
        )
        probe = my.inflate(CAR_FOLLOW_SEP + 6, CAR_FOLLOW_SEP + 6)
        for other in peers:
            if other is not self and collide(probe, other._collision_shell):
                return True
        return False

    def _cap_next_rect_all_cars(self, next_rect, peers):
        """Never advance into any car shell (all orientations) along our travel axis."""
        g = CAR_FOLLOW_SEP
        iterations = _tune.CAP_ALL_CARS_ITERATIONS
        for _ in range(iterations):
            my = sprites.car_collision_rect_into(
                next_rect, self.vertical, self._body_rect_scratch
            )
            nudged = False
            for other in peers:
                if other is self:
                    continue
                oc = other._collision_shell
                if not collide(my, oc):
                    continue
                if self.vertical:
                    if self.direction > 0:
                        limit = oc.top - g
                        if my.bottom > limit:
                            next_rect.y -= my.bottom - limit
                            nudged = True
                    else:
                        limit = oc.bottom + g
                        if my.top < limit:
                            next_rect.y += limit - my.top
                            nudged = True
                else:
                    if self.direction > 0:
                        limit = oc.left - g
                        if my.right > limit:
                            next_rect.x -= my.right - limit
                            nudged = True
                    else:
                        limit = oc.right + g
                        if my.left < limit:
                            next_rect.x += limit - my.left
                            nudged = True
            if not nudged:
                break
        return next_rect

    def _hard_shell_overlap(self, rect, vertical, other, body_rect: Rect | None = None) -> bool:
        my = (
            body_rect
            if body_rect is not None
            else sprites.car_collision_rect_into(rect, vertical, self._body_rect_scratch)
        )
        oc = other._collision_shell.inflate(-PERP_OVERLAP_SHRINK, -PERP_OVERLAP_SHRINK)
        if oc.width < 3 or oc.height < 3:
            return False
        return collide(my, oc)

    def _ix_creep_has_priority(self, other, intersection_zones=None) -> bool:
        """Committed turners beat straight traffic; else alternate stuck creep."""
        self_turn = self._committed_intersection_turn(intersection_zones)
        other_turn = other._committed_intersection_turn(intersection_zones)
        if self_turn and not other_turn:
            return True
        if other_turn and not self_turn:
            return False
        if self._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return False
        if other._intersection_stuck_frames < INTERSECTION_STUCK_CREEP_FRAMES:
            return True
        return (self.spawn_id % 2) <= (other.spawn_id % 2)

    def _hard_block_after_cap(
        self,
        next_rect,
        peers,
        intersection_creep: bool,
        intersection_zones=None,
    ) -> bool:
        for other in peers:
            if other is self:
                continue
            if not self._hard_shell_overlap(next_rect, self.vertical, other):
                continue
            if other.vertical != self.vertical:
                if intersection_creep and self._ix_creep_has_priority(
                    other, intersection_zones
                ):
                    continue
                return True
            if other.direction == self.direction and self._same_lane(other, CAR_BLOCK_LANE_GAP):
                return True
        return False

    def _nudge_car_position(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        self.rect.x += dx
        self.rect.y += dy
        if self._turn_phase in ("turning", "settling"):
            self._turn_px += dx
            self._turn_py += dy
        self._shell_sync_key = None

    def _resolve_shell_penetration(
        self,
        peers,
        *,
        max_nudge: int = SHELL_PENETRATION_MAX_NUDGE,
        passes: int = SHELL_PENETRATION_PASSES,
    ) -> None:
        """Push apart when collision shells overlap (any orientation)."""
        if not ENABLE_CAR_CAR_SOFT_AVOIDANCE:
            return
        g = CAR_FOLLOW_SEP
        for _ in range(passes):
            self._sync_collision_shell()
            my = self._collision_shell
            moved = False
            for other in peers:
                if other is self or not other.alive():
                    continue
                other._sync_collision_shell()
                oc = other._collision_shell
                if not collide(my, oc):
                    continue
                overlap_x = min(my.right, oc.right) - max(my.left, oc.left)
                overlap_y = min(my.bottom, oc.bottom) - max(my.top, oc.top)
                if overlap_x <= 0 or overlap_y <= 0:
                    continue
                dx = dy = 0
                if overlap_x <= overlap_y:
                    half = min(max_nudge, int(overlap_x * 0.55 + g))
                    dx = -half if my.centerx <= oc.centerx else half
                else:
                    half = min(max_nudge, int(overlap_y * 0.55 + g))
                    dy = -half if my.centery <= oc.centery else half
                if dx or dy:
                    self._nudge_car_position(dx, dy)
                    moved = True
                    self._sync_collision_shell()
                    my = self._collision_shell
            if not moved:
                break

    def _resolve_same_lane_penetration(self, peers):
        """If shells overlap a car ahead, push back (fixes frame-order / spawn glitches)."""
        g = CAR_FOLLOW_SEP
        my = sprites.car_collision_rect_into(
            self.rect, self.vertical, self._body_rect_scratch
        )
        for other in peers:
            if other is self:
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other, CAR_FOLLOW_LANE_GAP):
                continue
            ahead, _ = self._distance_to_other(other)
            if ahead <= 0:
                continue
            oc = other._collision_shell
            if not collide(my, oc):
                continue
            if self.vertical:
                if self.direction > 0:
                    if my.bottom > oc.top - g:
                        self.rect.y -= my.bottom - (oc.top - g)
                else:
                    if my.top < oc.bottom + g:
                        self.rect.y += (oc.bottom + g) - my.top
            else:
                if self.direction > 0:
                    if my.right > oc.left - g:
                        self.rect.x -= my.right - (oc.left - g)
                else:
                    if my.left < oc.right + g:
                        self.rect.x += (oc.right + g) - my.left

    def _rect_in_intersection(self, rect, intersection_zones):
        for zone in intersection_zones:
            if rects_overlap(zone, rect):
                return True
        return False

    def _near_intersection_bbox(self, intersection_zones, margin: int = 120) -> bool:
        if not intersection_zones:
            return False
        cx, cy = self.rect.centerx, self.rect.centery
        for zone in intersection_zones:
            if (
                zone.left - margin <= cx <= zone.right + margin
                and zone.top - margin <= cy <= zone.bottom + margin
            ):
                return True
        return False

    def _shell_overlaps_intersection(self, intersection_zones, pad: int = 0) -> bool:
        if not intersection_zones:
            return False
        shell = self._collision_shell
        if pad == INTERSECTION_SHELL_PAD and _intersection_zones_shell:
            zones = _intersection_zones_shell
        elif pad:
            for zone in intersection_zones:
                if rects_overlap(zone.inflate(pad, pad), shell):
                    return True
            return False
        else:
            zones = intersection_zones
        for zone in zones:
            if rects_overlap(zone, shell):
                return True
        return False

    def _matches_road_travel(self, road) -> bool:
        return (road.direction == "vertical" and not self.vertical) or (
            road.direction == "horizontal" and self.vertical
        )

    def _in_street_corridor(self, roads) -> bool:
        """Segment gaps between intersections — center can miss thin road rects."""
        cx, cy = self.rect.centerx, self.rect.centery
        for road in roads:
            if not self._matches_road_travel(road):
                continue
            band = road.rect.inflate(STREET_CORRIDOR_PAD, STREET_CORRIDOR_PAD)
            if band.collidepoint(cx, cy):
                return True
        return False

    def _corridor_lane_roads(self, roads) -> list:
        lane = self._lane_corridor_roads(roads)
        if lane:
            return lane
        if self.road_index is not None and 0 <= self.road_index < len(roads):
            r = roads[self.road_index]
            if self._matches_road_travel(r):
                return [r]
        return []

    def _lane_corridor_roads(self, roads) -> list:
        """Road segments on the same street row/column as this car (travel-matched)."""
        cx, cy = self.rect.centerx, self.rect.centery
        out = []
        for road in roads:
            if not self._matches_road_travel(road):
                continue
            band = road.rect.inflate(STREET_CORRIDOR_PAD, STREET_CORRIDOR_PAD)
            if band.collidepoint(cx, cy):
                out.append(road)
        return out

    def _far_extent_on_route(self, roads):
        """Leading edge of the last asphalt segment along current travel."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            if self.direction > 0:
                return max(r.rect.bottom for r in lane)
            return min(r.rect.top for r in lane)
        if self.direction > 0:
            return max(r.rect.right for r in lane)
        return min(r.rect.left for r in lane)

    def _entry_corridor_rect(self, roads, world_rect):
        """Driveable strip from map edge to first road segment (ongoing edge spawns)."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            cx = int(sum(r.rect.centerx for r in lane) / len(lane))
            half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.width for r in lane) // 2 + 12)
            if self.direction > 0:
                bottom = min(r.rect.top for r in lane)
                h = bottom - (world_rect.top - CAR_EXIT_DESPAWN_MARGIN)
                if h <= 4:
                    return None
                return Rect(
                    cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h
                )
            top = max(r.rect.bottom for r in lane)
            h = world_rect.bottom + CAR_EXIT_DESPAWN_MARGIN - top
            if h <= 4:
                return None
            return Rect(cx - half, top, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            right = min(r.rect.left for r in lane)
            w = right - (world_rect.left - CAR_EXIT_DESPAWN_MARGIN)
            if w <= 4:
                return None
            return Rect(
                world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2
            )
        left = max(r.rect.right for r in lane)
        w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
        if w <= 4:
            return None
        return Rect(left, cy - half, w, half * 2)

    def _exit_corridor_rect(self, roads, world_rect):
        """Driveable strip from last road segment to the map edge (segmented maps)."""
        lane = self._corridor_lane_roads(roads)
        if not lane:
            return None
        if self.vertical:
            cx = int(sum(r.rect.centerx for r in lane) / len(lane))
            half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.width for r in lane) // 2 + 12)
            if self.direction > 0:
                top = max(r.rect.bottom for r in lane)
                h = world_rect.bottom + CAR_EXIT_DESPAWN_MARGIN - top
                if h <= 4:
                    return None
                return Rect(cx - half, top, half * 2, h)
            bottom = min(r.rect.top for r in lane)
            h = bottom - world_rect.top + CAR_EXIT_DESPAWN_MARGIN
            if h <= 4:
                return None
            return Rect(cx - half, world_rect.top - CAR_EXIT_DESPAWN_MARGIN, half * 2, h)
        cy = int(sum(r.rect.centery for r in lane) / len(lane))
        half = max(EXIT_CORRIDOR_LATERAL, max(r.rect.height for r in lane) // 2 + 12)
        if self.direction > 0:
            left = max(r.rect.right for r in lane)
            w = world_rect.right + CAR_EXIT_DESPAWN_MARGIN - left
            if w <= 4:
                return None
            return Rect(left, cy - half, w, half * 2)
        right = min(r.rect.left for r in lane)
        w = right - world_rect.left + CAR_EXIT_DESPAWN_MARGIN
        if w <= 4:
            return None
        return Rect(world_rect.left - CAR_EXIT_DESPAWN_MARGIN, cy - half, w, half * 2)

    def _shell_asphalt_overlap_frac(
        self, roads, intersection_zones, road_subset: list | None = None
    ) -> float:
        """Strict overlap with real road/intersection geometry (no huge inflate)."""
        shell = self._collision_shell
        area = max(1, shell.width * shell.height)
        on = 0
        pad = ROAD_SURFACE_PAD
        check = road_subset if road_subset is not None else roads
        for road in check:
            r = road.rect
            if (
                shell.right < r.left - pad
                or shell.left > r.right + pad
                or shell.bottom < r.top - pad
                or shell.top > r.bottom + pad
            ):
                continue
            on += _rect_overlap_area(shell, r.inflate(pad, pad))
            if on / area >= MIN_ON_ROAD_FRAC:
                return min(1.0, on / area)
        for zone in intersection_zones or []:
            if not collide(shell, zone):
                continue
            on += _rect_overlap_area(shell, zone)
            if on / area >= MIN_ON_ROAD_FRAC:
                return min(1.0, on / area)
        return min(1.0, on / area)

    def _is_on_drivable_surface(self, roads, intersection_zones, world_rect) -> bool:
        """True only when shell actually touches asphalt, an intersection, or exit lane."""
        if self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            return True
        if self._in_street_corridor(roads):
            return True
        if self._shell_asphalt_overlap_frac(roads, intersection_zones) >= MIN_ON_ROAD_FRAC:
            return True
        if world_rect is not None and self._off_road_frames > 0:
            for corridor in (
                self._entry_corridor_rect(roads, world_rect),
                self._exit_corridor_rect(roads, world_rect),
            ):
                if corridor is not None and collide(corridor, self._collision_shell):
                    return True
        return False

    def _on_traffic_network(self, roads, intersection_zones, world_rect=None) -> bool:
        """Generous check for anchoring only (segment gaps); not used for despawn."""
        shell = self._collision_shell
        for road in roads:
            if collide(road.rect.inflate(NETWORK_ROAD_PAD, NETWORK_ROAD_PAD), shell):
                return True
        if self._in_street_corridor(roads):
            return True
        if world_rect is not None:
            for corridor in (
                self._entry_corridor_rect(roads, world_rect),
                self._exit_corridor_rect(roads, world_rect),
            ):
                if corridor is not None and collide(corridor, shell):
                    return True
        if intersection_zones:
            for zone in intersection_zones:
                z = zone.inflate(NETWORK_IX_PAD, NETWORK_IX_PAD)
                if collide(z, shell):
                    return True
        return False

    def _anchor_network_position(self, roads, intersection_zones, world_rect=None):
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            self._last_good_center = self.rect.center

    def _restore_if_orphaned(self, roads, intersection_zones, world_rect=None):
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            return
        # Off road: do not snap back; removal runs in _should_remove_car.

    def _refresh_car_sprite(self):
        center = self.rect.center
        self.image = sprites.make_car_surface(
            vertical=self.vertical,
            direction=self.direction,
            archetype_index=self.archetype_index,
        )
        self.rect = Rect(0, 0, self.image.get_width(), self.image.get_height())
        self.rect.center = center
        self._shell_sync_key = None

    def _hub_travel_offset(self) -> float:
        """Signed distance from hub along entry travel (+ = past hub)."""
        if self._turn_hub is None:
            return 0.0
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        return (self.rect.centerx - hx) * fx + (self.rect.centery - hy) * fy

    def _snap_to_hub_approach(self, max_past: float = 0.0):
        """Pull back if the car rolled past the hub while waiting to turn."""
        if self._turn_hub is None:
            return
        off = self._hub_travel_offset()
        if off <= max_past:
            return
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        self.rect.center = (
            round(self.rect.centerx - (off - max_past) * fx),
            round(self.rect.centery - (off - max_past) * fy),
        )

    def _cap_next_rect_to_hub(self, next_rect: Rect) -> Rect:
        """While approaching the hub, do not drive through before the turn starts."""
        if self._turn_phase != "to_hub" or self._turn_hub is None:
            return next_rect
        hx, hy = self._turn_hub
        fx, fy = travel_vector(self.vertical, self.direction)
        cx, cy = next_rect.center
        off = (cx - hx) * fx + (cy - hy) * fy
        if off > TURN_HUB_HOLD_DIST:
            cx -= (off - TURN_HUB_HOLD_DIST) * fx
            cy -= (off - TURN_HUB_HOLD_DIST) * fy
            next_rect.center = (round(cx), round(cy))
        return next_rect

    def _turn_arc_midpoint(
        self, roads, zone, exit_x: float, exit_y: float
    ) -> tuple[float, float]:
        """Bezier control point: tangent-corner biased to keep turns tight."""
        hx, hy = self._turn_hub or (zone.centerx, zone.centery)
        off = self._hub_travel_offset()
        if off <= 2:
            return float(hx), float(hy)
        px, py = float(self.rect.centerx), float(self.rect.centery)
        # Use the intersection of entry and exit tangents, then keep a small
        # hub influence so we avoid abrupt corner snaps in dense traffic.
        if self.vertical:
            corner_x, corner_y = px, exit_y
        else:
            corner_x, corner_y = exit_x, py
        bias = float(TURN_ARC_CORNER_BIAS)
        mid_x = corner_x * bias + hx * (1.0 - bias)
        mid_y = corner_y * bias + hy * (1.0 - bias)
        pad = max(6.0, TURN_RESERVE_PAD * 0.35)
        mid_x = max(zone.left + pad, min(zone.right - pad, mid_x))
        mid_y = max(zone.top + pad, min(zone.bottom - pad, mid_y))
        return mid_x, mid_y

    def _clamp_turn_point_keep_left(
        self, roads, cx: float, cy: float, ease: float
    ) -> tuple[float, float]:
        """Nudge turn probes toward keep-left — avoid crossing the yellow line."""
        if not self._turn_exit:
            return cx, cy
        nudge = 0.55 + 0.35 * _smoothstep(ease)
        entry_road = None
        if self.road_index is not None and 0 <= self.road_index < len(roads):
            entry_road = roads[self.road_index]
        idx, d, _exit_vertical = self._turn_exit
        exit_road = roads[idx] if 0 <= idx < len(roads) else None
        if entry_road is not None:
            cx, cy = clamp_keep_left_xy(
                entry_road, self._turn_entry_direction, cx, cy, strength=nudge
            )
        if exit_road is not None and ease >= 0.2:
            exit_strength = nudge * _smoothstep((ease - 0.2) / 0.8)
            cx, cy = clamp_keep_left_xy(exit_road, d, cx, cy, strength=exit_strength)
        return cx, cy

    def _complete_turn_on_exit_lane(self, roads) -> None:
        """Swap to exit-lane sprite and resume straight travel."""
        idx, d, exit_vertical = self._turn_exit
        exit_dir = 1 if d >= 0 else -1
        self.road_index = idx
        self.vertical = exit_vertical
        self.direction = exit_dir
        self._refresh_car_sprite()
        self.rect.center = (round(self._turn_px), round(self._turn_py))
        self._snap_center_to_left_lane(roads, max_nudge=None)
        self.turn_signal = 0
        self._turn_phase = "none"
        self._turn_exit = None
        self._turn_hub = None
        self._turn_blend = 0.0
        self._turn_arc_len = 0.0
        self._turn_arc_travel = 0.0
        self._turn_angle_draw_q = -999
        self._turn_settle_blend = 0.0
        self._turn_hold_frames = 0
        self._turn_stall_frames = 0
        self._turn_overlap_frames = 0
        self._last_good_center = self.rect.center
        self.current_speed = self.base_speed
        self.speed = self.base_speed * exit_dir
        self._turn_reservation_frames = max(8, _tune.TURN_RESERVATION_HOLD_FRAMES // 2)
        self._sync_collision_shell(force=True)

    def _bezier_point(self, t: float) -> tuple[float, float]:
        return _bezier_xy(t, self._turn_arc_start, self._turn_arc_mid, self._turn_arc_end)

    def _turn_probe_rect(self, px: float, py: float) -> Rect:
        body = Rect(0, 0, self._turn_side, self._turn_side)
        body.center = (round(px), round(py))
        return body

    def _turn_probe_shell(self, px: float, py: float) -> Rect:
        return sprites.car_collision_rect_turn(self._turn_probe_rect(px, py))

    def _prime_turn_arc_geometry(self, roads, zone):
        if not self._turn_exit:
            return
        idx, d, _exit_vertical = self._turn_exit
        ex, ey = lane_center_xy(roads[idx], d)
        mx, my = self._turn_arc_midpoint(roads, zone, float(ex), float(ey))
        self._turn_arc_start = (float(self.rect.centerx), float(self.rect.centery))
        self._turn_arc_mid = (mx, my)
        self._turn_arc_end = (float(ex), float(ey))

    def _turn_path_points(self, t_max: float = 1.0) -> list[tuple[float, float]]:
        count = max(2, TURN_PATH_SAMPLES)
        if t_max >= 1.0:
            pts = _sample_bezier_xy(
                self._turn_arc_start, self._turn_arc_mid, self._turn_arc_end, count
            )
            return pts
        return [
            self._bezier_point((i / (count - 1)) * t_max) for i in range(count)
        ]

    def _turn_path_conflict_rect(self, pad: int = TURN_CORRIDOR_PAD) -> Rect | None:
        if not self._turn_exit:
            return None
        pts = self._turn_path_points(1.0)
        left, top, right, bottom = _turn_corridor_bounds(pts, pad)
        return Rect(
            int(left),
            int(top),
            max(1, int(right - left)),
            max(1, int(bottom - top)),
        )

    def _travel_distance_to_rect(self, other, target: Rect) -> float | None:
        """Distance until `other` enters target along its travel axis."""
        if other.vertical:
            if other.direction > 0:
                if other.rect.top >= target.bottom:
                    return None
                return max(0.0, float(target.top - other.rect.bottom))
            if other.rect.bottom <= target.top:
                return None
            return max(0.0, float(other.rect.top - target.bottom))
        if other.direction > 0:
            if other.rect.left >= target.right:
                return None
            return max(0.0, float(target.left - other.rect.right))
        if other.rect.right <= target.left:
            return None
        return max(0.0, float(other.rect.left - target.right))

    def _turn_eta_to_conflict(self, conflict: Rect) -> float:
        """Estimated seconds before this turner reaches the conflict corridor."""
        if self._turn_phase in ("turning", "settling"):
            return 0.0
        fps = max(1.0, float(SIM_FPS))
        approach_speed = max(0.35, self.current_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC * 0.7)
        approach_eta = 0.0
        if self._turn_phase == "to_hub" and self._turn_hub is not None:
            hx, hy = self._turn_hub
            approach_eta = math.hypot(self.rect.centerx - hx, self.rect.centery - hy) / (approach_speed * fps)
        arc_speed = max(0.35, self.base_speed * TURN_DRIFT_SPEED_FRAC)
        pts = self._turn_path_points(1.0)
        if not pts:
            return approach_eta
        cum = 0.0
        prev = pts[0]
        for i, pt in enumerate(pts):
            if i > 0:
                cum += math.hypot(pt[0] - prev[0], pt[1] - prev[1])
                prev = pt
            probe = self._turn_probe_shell(pt[0], pt[1])
            if rects_overlap(probe.inflate(4, 4), conflict):
                return approach_eta + (cum / (arc_speed * fps))
        return approach_eta + (cum / (arc_speed * fps))

    def _turn_conflict_window(self, conflict: Rect) -> tuple[float, float]:
        entry_eta = self._turn_eta_to_conflict(conflict)
        clearance = max(0.25, TURN_SETTLE_FRAMES / max(1.0, SIM_FPS))
        drift_speed = max(0.35, self.base_speed * TURN_DRIFT_SPEED_FRAC)
        window = max(clearance, conflict.width / max(1.0, drift_speed * 30.0))
        return entry_eta, entry_eta + window

    def _straight_priority_blocker(self, peers, intersection_zones) -> bool:
        """Turning traffic yields to moving straight-through traffic."""
        if not intersection_zones:
            return False
        conflict = self._turn_path_conflict_rect(_tune.TURN_PRIORITY_CONFLICT_PAD)
        if conflict is None:
            return False
        turn_entry_eta, turn_exit_eta = self._turn_conflict_window(conflict)
        margin = _tune.TURN_PRIORITY_TIME_MARGIN_S
        predict_s = _tune.TURN_PRIORITY_PREDICT_SECONDS
        for other in peers:
            if other is self or not other.alive():
                continue
            if other._turn_phase != "none" or other.turn_signal != 0:
                continue
            if other.current_speed < _tune.TURN_PRIORITY_MIN_STRAIGHT_SPEED:
                continue
            dist = self._travel_distance_to_rect(other, conflict)
            if dist is None:
                continue
            straight_eta = dist / (max(other.current_speed, _tune.TURN_PRIORITY_MIN_STRAIGHT_SPEED) * max(1.0, float(SIM_FPS)))
            if straight_eta > predict_s:
                continue
            if straight_eta <= (turn_exit_eta + margin) and straight_eta >= (turn_entry_eta - margin):
                return True
        return False

    def _turn_reserved_rect(self, intersection_zones) -> Rect | None:
        if not self._turn_exit or self._turn_hub is None:
            return None
        if self._turn_phase not in ("turning", "settling"):
            return None
        pts = self._turn_path_points(1.0)
        left, top, right, bottom = _turn_corridor_bounds(pts, TURN_RESERVE_PAD)
        return Rect(
            int(left),
            int(top),
            max(1, int(right - left)),
            max(1, int(bottom - top)),
        )

    def _shell_blocks_turn_path(
        self,
        shell: Rect,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones=None,
    ) -> bool:
        for other in peers:
            if other is self:
                continue
            other_shell = other._collision_shell
            other_speed = getattr(other, "current_speed", 0.0)
            other_phase = getattr(other, "_turn_phase", "none")
            if other_speed < CAR_CREEP_SPEED * 1.25 and other_phase == "none":
                if collide(shell.inflate(10, 10), other_shell):
                    return True
            elif collide(shell, other_shell):
                return True
        if not ENABLE_CAR_CAR_COLLISION:
            if not ped_legal_crossing and collide(shell, player_body_rect):
                return True
        return False

    def _exit_lane_travel(self) -> tuple[bool, int] | None:
        if not self._turn_exit:
            return None
        _idx, d, exit_vertical = self._turn_exit
        return exit_vertical, 1 if d >= 0 else -1

    def _gap_along_exit_lane(self, other, exit_vertical: bool, exit_dir: int) -> tuple[float, float]:
        if self._turn_phase in ("turning", "settling"):
            ref_x, ref_y = self._turn_px, self._turn_py
        else:
            ref_x, ref_y = self.rect.centerx, self.rect.centery
        if exit_vertical:
            ahead = (other.rect.centery - ref_y) * exit_dir
            lane_gap = abs(other.rect.centerx - ref_x)
        else:
            ahead = (other.rect.centerx - ref_x) * exit_dir
            lane_gap = abs(other.rect.centery - ref_y)
        return ahead, lane_gap

    def _stopped_car_blocks_turn_exit(self, peers) -> bool:
        """Hold turn when a stopped vehicle occupies the exit lane ahead."""
        if self._turn_phase not in ("to_hub", "turning", "settling"):
            return False
        travel = self._exit_lane_travel()
        if travel is None:
            return False
        exit_vertical, exit_dir = travel
        block_dist = _tune.TURN_EXIT_STOPPED_BLOCK_DIST
        for other in peers:
            if other is self or not other.alive():
                continue
            if other._turn_phase in ("turning", "settling", "to_hub"):
                continue
            if other.vertical != exit_vertical:
                continue
            if other.direction != exit_dir:
                # Opposing lane traffic should only block when it is already
                # physically crowding the turner's shell near the exit.
                if self._turn_phase in ("turning", "settling") and collide(
                    self._collision_shell.inflate(6, 6),
                    other._collision_shell.inflate(6, 6),
                ):
                    return True
                continue
            if other.current_speed > CAR_CREEP_SPEED * 1.5:
                continue
            ahead, lane_gap = self._gap_along_exit_lane(other, exit_vertical, exit_dir)
            if ahead <= 0 or ahead > block_dist:
                continue
            if lane_gap < CAR_BLOCK_LANE_GAP + 8:
                return True
        return False

    def _turn_path_clear(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        t_max: float = 1.0,
        intersection_zones=None,
    ) -> bool:
        for px, py in self._turn_path_points(t_max):
            if self._shell_blocks_turn_path(
                self._turn_probe_shell(px, py),
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones,
            ):
                return False
        return True

    def _turn_segment_clear(
        self,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        t_from: float,
        t_to: float,
        intersection_zones=None,
    ) -> bool:
        t0 = max(0.0, min(1.0, t_from))
        t1 = max(0.0, min(1.0, t_to))
        if t1 < t0:
            t0, t1 = t1, t0
        samples = max(3, int((t1 - t0) * TURN_PATH_SAMPLES) + 1)
        for i in range(samples):
            t = t0 + (t1 - t0) * (i / max(1, samples - 1))
            cx, cy = self._bezier_point(t)
            if self._shell_blocks_turn_path(
                self._turn_probe_shell(cx, cy),
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones,
            ):
                return False
        return True

    def _turn_segment_blocked_by_stopped_straight(
        self, peers, t_from: float, t_to: float
    ) -> bool:
        """True when a stopped straight-through car occupies this arc segment."""
        t0 = max(0.0, min(1.0, t_from))
        t1 = max(0.0, min(1.0, t_to))
        if t1 < t0:
            t0, t1 = t1, t0
        samples = max(3, int((t1 - t0) * TURN_PATH_SAMPLES) + 1)
        for i in range(samples):
            t = t0 + (t1 - t0) * (i / max(1, samples - 1))
            cx, cy = self._bezier_point(t)
            shell = self._turn_probe_shell(cx, cy)
            for other in peers:
                if other is self or not other.alive():
                    continue
                if other._turn_phase != "none" or other.turn_signal != 0:
                    continue
                if other.current_speed >= CAR_CREEP_SPEED * 1.25:
                    continue
                if collide(shell.inflate(10, 10), other._collision_shell):
                    return True
        return False

    def _estimate_turn_arc_len(self) -> float:
        pts = [self._bezier_point(i / 8.0) for i in range(9)]
        total = 0.0
        for i in range(1, len(pts)):
            total += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        return max(TURN_MIN_ARC_LEN, total)

    def _cap_turn_motion_step(
        self, prev_x: float, prev_y: float, cx: float, cy: float
    ) -> tuple[float, float]:
        max_step = max(2.5, self.base_speed * 1.02)
        dx = cx - prev_x
        dy = cy - prev_y
        dist = math.hypot(dx, dy)
        if dist > max_step:
            scale = max_step / dist
            return prev_x + dx * scale, prev_y + dy * scale
        return cx, cy

    def _set_turn_visual(self, angle_deg: float, px: float, py: float):
        self._turn_px = float(round(px))
        self._turn_py = float(round(py))
        self._turn_display_angle = angle_deg
        angle_q = int(round(angle_deg / 2.0) * 2) % 360
        if angle_q != self._turn_angle_draw_q:
            self._turn_angle_draw_q = angle_q
            self.image = sprites.make_car_rotated_in_box(
                self.archetype_index, angle_q, self._turn_side, self._turn_side
            )
        self.rect = Rect(0, 0, self._turn_side, self._turn_side)
        self.rect.center = (round(px), round(py))
        self._shell_sync_key = None

    def _intersection_zone_at(self, intersection_zones):
        for zone in intersection_zones:
            if collide(zone, self.rect):
                return zone
        return None

    def _turn_side_candidates(self, preferred: int) -> list[int]:
        if preferred == 0:
            return [0, -1, 1]
        return [preferred, -preferred, 0]

    def _apply_turn_plan_for_side(
        self,
        roads,
        zone,
        key: tuple[int, int, int, int],
        turn_side: int,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        if self._turn_phase in ("turning", "settling"):
            return False
        if turn_side == 0:
            self._turn_zone_key = key
            self.turn_signal = 0
            self._turn_exit = None
            self._turn_hub = None
            self._turn_hold_frames = 0
            return True
        entry_v = self.vertical
        entry_d = self.direction
        if self._turn_phase == "to_hub":
            entry_v = self._turn_entry_vertical
            entry_d = self._turn_entry_direction
        exit_plan = choose_exit(
            roads,
            zone,
            entry_v,
            entry_d,
            turn_side,
            self.rect.center,
            self.road_index,
        )
        if exit_plan is None:
            return False
        if not self._pivot_exit_clear(
            roads, zone, exit_plan, peers, player_body_rect, ped_legal_crossing
        ):
            return False
        self._turn_hub = (zone.centerx, zone.centery)
        self._turn_exit = exit_plan
        self._prime_turn_arc_geometry(roads, zone)
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=[zone],
        ):
            self._turn_hub = None
            self._turn_exit = None
            return False
        if self._straight_priority_blocker(peers, [zone]):
            self._turn_hub = None
            self._turn_exit = None
            return False
        self._turn_zone_key = key
        self.turn_signal = turn_side
        self._turn_hold_frames = 0
        return True

    def _plan_turn_at_intersection(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ):
        if not intersection_zones or self._turn_phase in ("to_hub", "turning", "settling"):
            return
        if self._turn_abort_cooldown > 0:
            return
        if self.turn_signal == 0 and not self._approaching_or_in_intersection(
            intersection_zones
        ):
            return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            if self._turn_phase == "none":
                self.turn_signal = 0
                self._turn_exit = None
            self._turn_zone_key = None
            return
        key = (zone.x, zone.y, zone.w, zone.h)
        if key == self._turn_zone_key and self.turn_signal != 0:
            return
        rng = random.Random((_traffic_map_seed + self.spawn_id * 31) & 0xFFFFFFFF)
        preferred = pick_turn_side(rng, TURN_CHANCE)
        for turn_side in self._turn_side_candidates(preferred):
            if self._apply_turn_plan_for_side(
                roads,
                zone,
                key,
                turn_side,
                peers,
                player_body_rect,
                ped_legal_crossing,
            ):
                return
        self._hold_turn_and_replan(
            intersection_zones,
            roads,
            peers,
            player_body_rect,
            ped_legal_crossing,
        )

    def _arm_turn_through_hub(
        self,
        roads,
        intersection_zones,
        peers=None,
        player_body_rect=None,
        ped_legal_crossing: bool = True,
    ):
        """Commit to hub turn once a planned turn is near or inside the box."""
        if self.turn_signal == 0 or not self._turn_exit or not intersection_zones:
            return
        if self._turn_hold_frames > 0:
            return
        if not self._approaching_or_in_intersection(intersection_zones):
            return
        if peers is not None and player_body_rect is not None:
            if not self._turn_path_clear(
                peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones=intersection_zones,
            ):
                return
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return
        if self._turn_phase == "none":
            in_ix = self._rect_in_intersection(self.rect, intersection_zones)
            if not in_ix:
                hx, hy = zone.centerx, zone.centery
                dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
                lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
                if dist > lead + 10:
                    return
            self._turn_phase = "to_hub"
            self._turn_hub = (zone.centerx, zone.centery)

    def _begin_turn_steer(
        self,
        roads,
        zone,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
        intersection_zones=None,
    ) -> bool:
        self._prime_turn_arc_geometry(roads, zone)
        ix = intersection_zones if intersection_zones is not None else [zone]
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=ix,
        ):
            return False
        if self._stopped_car_blocks_turn_exit(peers):
            return False
        if self._straight_priority_blocker(peers, ix):
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self.speed = 0.0
            self.current_speed = 0.0
            return False
        self._snap_to_hub_approach(max_past=0.0)
        self._turn_entry_vertical = self.vertical
        self._turn_entry_direction = self.direction
        self._turn_blend = 0.0
        self._turn_arc_travel = 0.0
        self._turn_arc_len = 0.0
        self._turn_angle_draw_q = -999
        self._turn_side = max(CAR_WIDTH, CAR_HEIGHT)
        self._turn_px = float(self.rect.centerx)
        self._turn_py = float(self.rect.centery)
        idx, d, exit_vertical = self._turn_exit
        exit_dir = 1 if d >= 0 else -1
        self._turn_angle_start = sprites.car_travel_angle_deg(
            self._turn_entry_vertical, self._turn_entry_direction
        )
        self._turn_angle_end = sprites.car_travel_angle_deg(exit_vertical, exit_dir)
        self._turn_arc_side = self._turn_side_for_exit_plan()
        ex, ey = lane_center_xy(roads[idx], d)
        mx, my = self._turn_arc_midpoint(roads, zone, float(ex), float(ey))
        self._turn_arc_start = (self._turn_px, self._turn_py)
        self._turn_arc_mid = (mx, my)
        self._turn_arc_end = (float(ex), float(ey))
        self._turn_arc_len = self._estimate_turn_arc_len()
        self._turn_phase = "turning"
        self._turn_arc_age = 0
        self._turn_reservation_frames = _tune.TURN_RESERVATION_HOLD_FRAMES
        self._set_turn_visual(self._turn_angle_start, self._turn_px, self._turn_py)
        self.current_speed = max(self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.5)
        self._sync_collision_shell(force=True)
        return True

    def _steer_through_turn(
        self,
        roads,
        intersection_zones,
        peers,
        player_body_rect,
        ped_legal_crossing: bool,
    ) -> bool:
        """Bezier path + gradual sprite rotation; returns True when arc is done."""
        if self._turn_phase != "turning" or not self._turn_exit:
            return False

        if self._stopped_car_blocks_turn_exit(peers):
            self.speed = 0.0
            self.current_speed = 0.0
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self._sync_collision_shell()
            return False
        if self._turn_arc_len < 1.0:
            self._turn_arc_len = self._estimate_turn_arc_len()

        drift_floor = self.base_speed * TURN_MIN_STEP_FRAC
        step = max(drift_floor, self.current_speed) * TURN_DRIFT_SPEED_FRAC
        step = min(step, self.base_speed * 1.05)
        t_now = self._turn_arc_travel / max(1e-6, self._turn_arc_len)
        next_travel = min(self._turn_arc_len, self._turn_arc_travel + step)
        t_next = next_travel / max(1e-6, self._turn_arc_len)
        eased_now = _smoothstep(t_now)
        eased_next = _smoothstep(t_next)
        segment_clear = self._turn_segment_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            eased_now,
            eased_next,
            intersection_zones=intersection_zones,
        )
        near_arc_end = t_now >= 0.9
        if not segment_clear and not near_arc_end:
            self.speed = 0.0
            self.current_speed = max(
                self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.55,
                self.current_speed * 0.92,
            )
            self._turn_overlap_frames += 1
            self._turn_stall_frames += 1
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self._sync_collision_shell()
            return False

        prev_px, prev_py = self._turn_px, self._turn_py
        ease = _smoothstep(t_next)
        if near_arc_end and not segment_clear:
            if not self._turn_segment_blocked_by_stopped_straight(
                peers, eased_now, eased_next
            ):
                ease = 1.0
                next_travel = self._turn_arc_len
        angle = _lerp_turn_angle_deg(
            self._turn_angle_start,
            self._turn_angle_end,
            ease,
            self._turn_arc_side,
        )
        cx, cy = self._bezier_point(ease)
        cx, cy = self._clamp_turn_point_keep_left(roads, cx, cy, ease)
        cx, cy = self._cap_turn_motion_step(prev_px, prev_py, cx, cy)
        overlap = self._probe_turn_shell_overlaps_peer(peers, cx, cy)
        if overlap:
            self.speed = 0.0
            self.current_speed = max(
                self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.55,
                self.current_speed * 0.92,
            )
            self._turn_overlap_frames += 1
            self._turn_stall_frames += 1
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self._sync_collision_shell()
            return False

        self._turn_arc_travel = next_travel
        self._set_turn_visual(angle, cx, cy)
        self._sync_collision_shell()

        self.current_speed = max(
            self.current_speed, self.base_speed * TURN_DRIFT_SPEED_FRAC * 0.65
        )
        self.speed = self.current_speed * self._turn_entry_direction

        if ease >= 1.0:
            idx, d, exit_vertical = self._turn_exit
            tcx, tcy = lane_center_xy(roads[idx], d)
            self._turn_settle_target = (float(tcx), float(tcy))
            self._turn_settle_blend = 0.0
            self._turn_phase = "settling"
            self.current_speed = self.base_speed
            self.speed = self.base_speed * self._turn_entry_direction
            self._sync_collision_shell(force=True)
        else:
            self._sync_collision_shell()
        return False

    def _settle_turn_exit(
        self, roads, peers=None, intersection_zones=None
    ) -> bool:
        """Brief lane alignment while continuing forward on the exit road."""
        if self._turn_phase != "settling" or not self._turn_exit:
            return False
        if peers and self._stopped_car_blocks_turn_exit(peers):
            self._turn_stall_frames += 1
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self.speed = 0.0
            self.current_speed = 0.0
            self._sync_collision_shell()
            return False
        idx, d, exit_vertical = self._turn_exit
        exit_dir = 1 if d >= 0 else -1
        prev_x, prev_y = self._turn_px, self._turn_py
        forward = self.base_speed * exit_dir * 0.72
        if exit_vertical:
            self._turn_py += forward
        else:
            self._turn_px += forward
        self._turn_settle_blend += 1.0 / max(1, TURN_SETTLE_FRAMES)
        t = _smoothstep(min(1.0, self._turn_settle_blend))
        tx, ty = self._turn_settle_target
        if exit_vertical:
            self._turn_px += (tx - self._turn_px) * t
        else:
            self._turn_py += (ty - self._turn_py) * t
        cx, cy = self._turn_px, self._turn_py
        cx, cy = self._clamp_turn_point_keep_left(roads, cx, cy, t)
        cx, cy = self._cap_turn_motion_step(prev_x, prev_y, cx, cy)
        self._turn_px, self._turn_py = cx, cy
        end_angle = sprites.car_travel_angle_deg(exit_vertical, exit_dir)
        settle_side = self._turn_arc_side if self._turn_arc_side != 0 else self.turn_signal
        angle = _lerp_turn_angle_deg(
            self._turn_angle_end, end_angle, t, settle_side
        )
        self._set_turn_visual(angle, cx, cy)
        self.current_speed = self.base_speed
        self.speed = self.base_speed * exit_dir
        if t < 1.0:
            self._sync_collision_shell()
            return False
        self._complete_turn_on_exit_lane(roads)
        return True

    def _try_start_turn_at_hub(
    self,
    roads,
    intersection_zones,
    peers,
    player_body_rect,
    ped_legal_crossing: bool,
    road_states=None,
    ) -> bool:
        if self._turn_phase != "to_hub" or not self._turn_exit or not self._turn_hub:
            return False
        zone = self._intersection_zone_for_turn_planning(intersection_zones, roads)
        if zone is None:
            zone = self._intersection_zone_at(intersection_zones)
        if zone is None:
            return False
        hx, hy = self._turn_hub
        dist = math.hypot(self.rect.centerx - hx, self.rect.centery - hy)
        past = self._hub_travel_offset()
        if past > TURN_OVERSHOOT_ABORT:
            self._hold_turn_and_replan(
                intersection_zones,
                roads,
                peers,
                player_body_rect,
                ped_legal_crossing,
            )
            return False
        lead = TURN_HUB_DIST + TURN_SIGNAL_LEAD_DIST // 3
        if dist > lead and past <= 0:
            return False
        # --- RED LIGHT GATE ---
        if road_states:
            approach = self._nearest_approach_state(road_states)
            if approach is not None:
                light = self._effective_approach_light(approach)
                if light == "red":
                    self.speed = 0.0
                    self.current_speed = 0.0
                    return False
        # ----------------------
        if not self._turn_path_clear(
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        ):
            return False
        if self._straight_priority_blocker(peers, intersection_zones):
            self.speed = 0.0
            self.current_speed = 0.0
            self._turn_hold_frames = max(1, self._turn_hold_frames)
            self._sync_collision_shell()
            return False
        return self._begin_turn_steer(
            roads,
            zone,
            peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones=intersection_zones,
        )

    def _spawn_ramp_cap(self) -> float:
        if self._spawn_age >= CAR_SPAWN_RAMP_FRAMES:
            return self.base_speed
        t = self._spawn_age / CAR_SPAWN_RAMP_FRAMES
        ease = t * t * (3.0 - 2.0 * t)
        return self.base_speed * ease

    def _has_exited_map_along_route(
        self, roads, intersection_zones, world_rect
    ) -> bool:
        """Despawn only after the car fully leaves the map (exit corridor handles segment ends)."""
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            return False
        if self._near_intersection_bbox(intersection_zones) and self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            return False
        shell = self._collision_shell
        edge_m = CAR_EXIT_DESPAWN_MARGIN
        if self.vertical:
            if self.direction > 0:
                return shell.top > world_rect.bottom + edge_m
            return shell.bottom < world_rect.top - edge_m
        if self.direction > 0:
            return shell.left > world_rect.right + edge_m
        return shell.right < world_rect.left - edge_m

    def _removal_reason(
        self, roads, intersection_zones, world_rect, frame_index: int = 0
    ) -> str | None:
        """Why this car should despawn; None = keep."""
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            return None
        if (
            self._gridlock_frames >= INTERSECTION_GRIDLOCK_FRAMES
            and self._turn_phase == "none"
            and self.turn_signal == 0
            and intersection_zones
            and self._rect_in_intersection(self.rect, intersection_zones)
            and self.current_speed < 0.35
        ):
            return "gridlock"
        if self._turn_phase in ("to_hub", "turning", "settling") or self.turn_signal != 0:
            return None
        if self._near_intersection_bbox(intersection_zones) and self._shell_overlaps_intersection(
            intersection_zones, INTERSECTION_SHELL_PAD
        ):
            self._off_road_frames = 0
            return None
        if self._has_exited_map_along_route(roads, intersection_zones, world_rect):
            return "exit"
        if (
            self._off_road_frames == 0
            and (frame_index + self.spawn_id) % SURFACE_CHECK_INTERVAL != 0
        ):
            return None
        if self._is_on_drivable_surface(roads, intersection_zones, world_rect):
            self._off_road_frames = 0
            return None
        self._off_road_frames += 1
        if self._off_road_frames >= OFF_ROAD_REMOVE_FRAMES:
            return "off_road"
        return None

    def _in_or_entering_intersection(self, next_rect, intersection_zones) -> bool:
        if not intersection_zones:
            return False
        return any(
            collide(z, self.rect) or collide(z, next_rect) for z in intersection_zones
        )

    def _entry_blocks_moving_cross_traffic(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        """Do not enter the box if we'd cut in front of cross traffic or a committed turn."""
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for zone in intersection_zones:
            entering = collide(next_rect, zone) and not collide(self.rect, zone)
            if not entering:
                continue
            for other in peers:
                if other is self:
                    continue
                if other._committed_intersection_turn(intersection_zones):
                    if zone.collidepoint(other.rect.center) and collide(
                        my_n, other._collision_shell
                    ):
                        return True
                    continue
                if other.vertical == self.vertical:
                    continue
                if other.current_speed < other.base_speed * 0.2:
                    continue
                if not zone.collidepoint(other.rect.center):
                    continue
                orect = other._collision_shell.inflate(-6, -6)
                if orect.width > 2 and orect.height > 2 and collide(my_n, orect):
                    return True
        return False

    def _distance_to_clear_zone(self, zone: Rect) -> float:
        """Along-travel distance from the leading edge to the far side of a zone."""
        if self.vertical:
            if self.direction > 0:
                return max(0.0, float(zone.bottom - self.rect.bottom))
            return max(0.0, float(self.rect.top - zone.top))
        if self.direction > 0:
            return max(0.0, float(zone.left - self.rect.right))
        return max(0.0, float(self.rect.left - zone.right))

    def _clear_distance_through_zone(self, zone: Rect) -> float:
        """Distance needed to fully exit the zone along current travel."""
        if collide(zone, self.rect):
            return self._distance_to_clear_zone(zone)
        entry = self._distance_to_intersection_entry(zone)
        if entry is None or entry < 0:
            return 0.0
        depth = zone.height if self.vertical else zone.width
        return float(entry) + float(depth)

    def _signal_stop_axis(self, crosswalk: Rect) -> int:
        """Crosswalk edge along our travel axis (white stop line)."""
        if self.vertical:
            return crosswalk.top if self.direction > 0 else crosswalk.bottom
        return crosswalk.left if self.direction > 0 else crosswalk.right

    def _distance_to_signal_stop(self, stop_axis: int) -> float:
        """Distance from our leading edge to the stop line (positive = before the line)."""
        if self.vertical:
            if self.direction > 0:
                return float(stop_axis - self.rect.bottom)
            return float(self.rect.top - stop_axis)
        if self.direction > 0:
            return float(stop_axis - self.rect.right)
        return float(self.rect.left - stop_axis)

    def _enforce_signal_stop_line(self, stop_axis: int) -> bool:
        """Clamp at stop line even if already slowly overshot."""
        clamped = False
        if self.vertical:
            if self.direction > 0:
                limit = stop_axis - STOP_LINE_GAP
                if self.rect.bottom > limit:
                    self.rect.bottom = limit
                    clamped = True
            else:
                limit = stop_axis + STOP_LINE_GAP
                if self.rect.top < limit:
                    self.rect.top = limit
                    clamped = True
        else:
            if self.direction > 0:
                limit = stop_axis - STOP_LINE_GAP
                if self.rect.right > limit:
                    self.rect.right = limit
                    clamped = True
            else:
                limit = stop_axis + STOP_LINE_GAP
                if self.rect.left < limit:
                    self.rect.left = limit
                    clamped = True
        return clamped

    def _in_crossing_lane(self, crosswalk: Rect) -> bool:
        if self.vertical:
            return abs(self.rect.centerx - crosswalk.centerx) < 50
        return abs(self.rect.centery - crosswalk.centery) < 50

    def _apply_approach_signal_braking(
        self,
        state: dict,
        stop_distance: float,
        desired_speed: float,
        blocking_controls: list,
        *,
        brake_dist: float,
        creep_dist: float,
    ) -> float:
        if stop_distance <= -STOP_LINE_GAP or stop_distance >= brake_dist:
            return desired_speed
        if stop_distance <= creep_dist:
            desired_speed = min(desired_speed, CAR_CREEP_SPEED)
            blocking_controls.append(state)
        else:
            span = max(1.0, brake_dist - creep_dist)
            t = (stop_distance - creep_dist) / span
            cap = self.base_speed * max(0.15, min(1.0, t) * 0.9)
            desired_speed = min(desired_speed, cap)
        if stop_distance <= STOP_LINE_GAP + 4:
            desired_speed = 0.0
            if state not in blocking_controls:
                blocking_controls.append(state)
        return desired_speed

    def _nearest_approach_state(self, road_states):
        best = None
        best_d = 1e9
        for state in road_states:
            if not rects_overlap(self.rect, state["approach_rect"]):
                continue
            crosswalk = state["crosswalk"]
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_distance = self._distance_to_signal_stop(stop_axis)
            if not self._in_crossing_lane(crosswalk) or stop_distance <= -STOP_LINE_GAP:
                continue
            if stop_distance < best_d:
                best_d = stop_distance
                best = state
        return best

    def _can_clear_signal_in_time(self, state, zone: Rect) -> bool:
        clear_dist = self._clear_distance_through_zone(zone)
        if clear_dist <= 0:
            return True
        speed_px_per_frame = max(self.current_speed, CAR_CREEP_SPEED * 0.45, 0.8)
        speed_px_per_s = speed_px_per_frame * SIM_FPS
        time_needed = clear_dist / speed_px_per_s
        time_left = self._effective_seconds_to_change(state)
        light = self._effective_approach_light(state)
        if light == "green":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S
        if light == "yellow":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S * 0.5
        return False

    def _exit_blocked_by_active_turn(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for other in peers:
            if other is self:
                continue
            if other._turn_phase in ("turning", "settling"):
                if rects_overlap(my_n, other._collision_shell):
                    return True
                reserved = other._turn_reserved_rect(intersection_zones)
                if reserved is not None and rects_overlap(my_n, reserved):
                    return True
            elif other._committed_intersection_turn(intersection_zones):
                if rects_overlap(my_n.inflate(16, 16), other._collision_shell):
                    return True
        return False

    def _intersection_entry_blocked(
        self,
        next_rect,
        road_states,
        intersection_zones,
        peers,
        move_peers,
    ) -> bool:
        """Do not enter the box unless the approach is green/yellow-clearable and exit is open."""
        if not intersection_zones:
            return False
        target_zone = None
        entering = False
        for zone in intersection_zones:
            if collide(next_rect, zone) and not collide(self.rect, zone):
                target_zone = zone
                entering = True
                break
        if target_zone is None:
            for zone in intersection_zones:
                entry = self._distance_to_intersection_entry(zone)
                if entry is not None and 0 <= entry <= 48:
                    target_zone = zone
                    break
        if target_zone is None:
            return False

        approach = self._nearest_approach_state(road_states)
        if approach is not None:
            light = self._effective_approach_light(approach)
            if light == "red":
                return True
            if light in ("green", "yellow") and not self._can_clear_signal_in_time(
                approach, target_zone
            ):
                return True

        if not entering:
            return False

        if self._entry_blocks_moving_cross_traffic(
            next_rect, move_peers or peers, intersection_zones
        ):
            return True
        if self._exit_blocked_by_active_turn(
            next_rect, move_peers or peers, intersection_zones
        ):
            return True
        return False

    def _intersection_move_blocked(
        self, next_rect, peers, intersection_zones, allow_perp_creep=False
    ):
        if not ENABLE_CAR_CAR_COLLISION:
            return False
        if not intersection_zones:
            return False
        if not self._in_or_entering_intersection(next_rect, intersection_zones):
            return False
        if not allow_perp_creep and self._entry_blocks_moving_cross_traffic(
            next_rect, peers, intersection_zones
        ):
            return True
        my_n = sprites.car_collision_rect(next_rect, self.vertical)
        for other in peers:
            if other is self:
                continue
            same_lane = (
                other.vertical == self.vertical
                and other.direction == self.direction
                and self._same_lane(other, CAR_BLOCK_LANE_GAP)
            )
            if same_lane:
                if not collide(my_n, other._collision_shell):
                    continue
                gap, _ = self._distance_to_other(other)
                if gap <= 0 or gap < 22:
                    return True
                continue
            if other._turn_phase in ("turning", "settling"):
                if collide(my_n, other._collision_shell):
                    return True
                continue
            if other.vertical == self.vertical:
                continue
            if not collide(my_n, other._collision_shell):
                continue
            if allow_perp_creep:
                if not self._hard_shell_overlap(next_rect, self.vertical, other):
                    continue
                if self._ix_creep_has_priority(other, intersection_zones):
                    continue
                return True
            return True
        return False

    def straight_cruise_update(
        self,
        road_states,
        world_rect,
        lane_peers,
        frame_index,
        roads,
        intersection_zones,
        player_body_rect=None,
    ) -> None:
        """Off-screen straight traffic: signals + lane follow only (no turn/honk/player)."""
        desired_speed = self.base_speed
        blocking_controls: list = []
        self._spawn_age += 1
        desired_speed = min(desired_speed, self._spawn_ramp_cap())

        nearest = self._nearest_approach_state(road_states)
        if nearest is not None:
            approach_light = self._effective_approach_light(nearest)
            stop_axis = self._signal_stop_axis(nearest["crosswalk"])
            stop_distance = self._distance_to_signal_stop(stop_axis)
            if approach_light == "red":
                desired_speed = self._apply_approach_signal_braking(
                    nearest,
                    stop_distance,
                    desired_speed,
                    blocking_controls,
                    brake_dist=RED_SIGNAL_BRAKE_DIST,
                    creep_dist=RED_SIGNAL_CREEP_DIST,
                )
        # Snap back only a minor overshoot at a red light (e.g. spawned 1-2 frames past).
        if self._turn_phase == "none" and self.current_speed < 0.5:
            for state in road_states:
                cw = state["crosswalk"]
                if not self._in_crossing_lane(cw):
                    continue
                sa = self._signal_stop_axis(cw)
                dist = self._distance_to_signal_stop(sa)
                if -STOP_LINE_GAP * 3 <= dist < -STOP_LINE_GAP:
                    light = self._effective_approach_light(state)
                    if light == "red":
                        self._enforce_signal_stop_line(sa)
                        break

        accel = (
            self.base_speed / CAR_SPAWN_RAMP_FRAMES
            if self._spawn_age < CAR_SPAWN_RAMP_FRAMES
            else self.acceleration
        )
        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + accel)
        else:
            self.current_speed = max(desired_speed, self.current_speed - self.brake_strength)

        signed_speed = self.current_speed * self.direction
        blocked_by_line = False
        for state in blocking_controls:
            stop_axis = self._signal_stop_axis(state["crosswalk"])
            if signed_speed != 0:
                if self.vertical:
                    if self.direction > 0 and self.rect.bottom + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.bottom = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.top + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.top = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                else:
                    if self.direction > 0 and self.rect.right + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.right = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.left + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.left = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
            if self._enforce_signal_stop_line(stop_axis):
                blocked_by_line = True
            if blocked_by_line:
                break

        if blocked_by_line:
            self.current_speed = 0.0
            self.speed = 0.0
        elif signed_speed != 0:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += int(signed_speed)
            else:
                next_rect.x += int(signed_speed)
            if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                next_rect = self._cap_next_rect_same_lane(next_rect, lane_peers)
            blocked_by_player = False
            if player_body_rect is not None:
                my_n = sprites.car_collision_rect_into(
                    next_rect, self.vertical, self._body_rect_scratch
                )
                blocked_by_player = collide(my_n, player_body_rect.inflate(6, 6))
            if blocked_by_player:
                self.current_speed = 0.0
                self.speed = 0.0
            else:
                self.speed = signed_speed
                self.rect = next_rect

        self.rect.clamp_ip(world_rect.inflate(300, 300))
        if (frame_index + self.spawn_id) % SURFACE_CHECK_INTERVAL == 0:
            self._anchor_network_position(roads, intersection_zones, world_rect)
        removal = self._removal_reason(roads, intersection_zones, world_rect, frame_index)
        if removal is not None:
            _notify_car_removed(self)
            self.kill()
        self._sync_collision_shell()

    def update(
        self,
        road_states,
        world_rect,
        intersection_zones,
        player_body_rect,
        roads,
        lane_peers,
        move_peers,
        frame_index=0,
        player_on_road=False,
        player_on_crosswalk=False,
        player_feet_road=False,
        ped_legal_crossing=False,
        respect_player=False,
        honk_allowed=False,
        player_body_block=None,
        game_time=0,
    ):
        desired_speed = self.base_speed
        blocking_controls = []
        yield_roll = (_traffic_map_seed + self.spawn_id * 17) % 100
        will_yield_to_player = yield_roll < int(PLAYER_AVOIDANCE_CHANCE * 100)
        if ped_legal_crossing:
            will_yield_to_player = True

        inside_intersection = bool(intersection_zones) and self._rect_in_intersection(
            self.rect, intersection_zones
        )
        if inside_intersection and self.current_speed < 0.35:
            self._intersection_stuck_frames += 1
        else:
            self._intersection_stuck_frames = 0
        if (
            inside_intersection
            and self._turn_phase == "none"
            and self.turn_signal == 0
            and self.current_speed < 0.3
        ):
            self._gridlock_frames += 1
        else:
            self._gridlock_frames = 0
        intersection_creep = (
            inside_intersection
            and self._intersection_stuck_frames >= INTERSECTION_STUCK_CREEP_FRAMES
        )
        self._spawn_age += 1
        if self._turn_abort_cooldown > 0:
            self._turn_abort_cooldown -= 1
        ramp_cap = self._spawn_ramp_cap()
        plan_turn = self.turn_signal != 0 or self._approaching_or_in_intersection(
            intersection_zones
        )
        plan_stride = 2 if plan_turn else 0
        if plan_stride and (frame_index + self.spawn_id) % plan_stride == 0:
            self._plan_turn_at_intersection(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        if plan_turn:
            self._maintain_turn_plan(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
                road_states,
            )
        self._arm_turn_through_hub(
            roads,
            intersection_zones,
            move_peers,
            player_body_rect,
            ped_legal_crossing,
        )
        self._try_resume_turn_after_block(
            move_peers,
            player_body_rect,
            ped_legal_crossing,
            intersection_zones,
        )
        if self._turn_hold_frames > 0 and (self.turn_signal != 0 or self._turn_exit):
            desired_speed = 0.0
        if (
            self._turn_hold_frames >= TURN_HOLD_RETRY_FRAMES * 4
            and self._turn_phase == "none"
            and self._turn_snap_travel > 0
            and self._turn_exit
        ):
            self._try_resume_turn_after_block(
                move_peers,
                player_body_rect,
                ped_legal_crossing,
                intersection_zones,
            )
        if (
            self._turn_phase == "none"
            and self._turn_snap_travel > 0
            and self._turn_hold_frames > 0
        ):
            self._turn_hold_frames -= 1
        if self._turn_phase in ("to_hub", "turning", "settling"):
            desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC)
            if self._turn_reservation_frames < _tune.TURN_RESERVATION_HOLD_FRAMES:
                self._turn_reservation_frames += 1
        elif self._turn_reservation_frames > 0:
            self._turn_reservation_frames -= 1
        if self._turn_phase == "to_hub" and self._turn_hub is not None:
            hub_off = self._hub_travel_offset()
            if hub_off >= -TURN_HUB_DIST:
                desired_speed = min(desired_speed, self.base_speed * TURN_PIVOT_SPEED_FRAC * 0.65)
            if -6 <= hub_off <= TURN_HUB_HOLD_DIST:
                desired_speed = 0.0

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
            if self._turn_phase not in ("turning", "settling") and len(lane_peers) > 1:
                self._resolve_same_lane_penetration(lane_peers)
        self._sync_collision_shell()

        for state in road_states:
            approach = state["approach_rect"]
            if not rects_overlap(self.rect, approach):
                continue

            crosswalk = state["crosswalk"]
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_distance = self._distance_to_signal_stop(stop_axis)
            in_crossing_lane = self._in_crossing_lane(crosswalk)

            if in_crossing_lane:
                # Snap back over the stop line if the car is stopped at a red and
                # slightly overshot (e.g. spawned 1–2 frames past the line).  Only
                # correct minor overshoots (≤ STOP_LINE_GAP * 3) so we never teleport
                # a car that is already deep inside the intersection.
                if (
                    not inside_intersection
                    and self._turn_phase == "none"
                    and self.current_speed < 0.5
                    and -STOP_LINE_GAP * 3 <= stop_distance < -STOP_LINE_GAP
                    and self._effective_approach_light(state) == "red"
                ):
                    self._enforce_signal_stop_line(stop_axis)

                # Do not hold at lights while already in the intersection box — clear it.
                if (
                    not inside_intersection
                    and self._turn_phase not in ("turning", "settling")
                ):
                    approach_light = self._effective_approach_light(state)
                    brake_dist = RED_SIGNAL_BRAKE_DIST
                    if approach_light == "red" and collide(crosswalk, player_body_rect):
                        brake_dist = RED_SIGNAL_BRAKE_DIST + 24
                    if approach_light == "red":
                        desired_speed = self._apply_approach_signal_braking(
                            state,
                            stop_distance,
                            desired_speed,
                            blocking_controls,
                            brake_dist=brake_dist,
                            creep_dist=RED_SIGNAL_CREEP_DIST,
                        )
                    elif approach_light == "yellow" and stop_distance < YELLOW_SIGNAL_BRAKE_DIST:
                        zone = self._intersection_zone_at(intersection_zones)
                        if zone is None and intersection_zones:
                            best_d = 1e9
                            for z in intersection_zones:
                                d = self._distance_to_intersection_entry(z)
                                if d is not None and 0 <= d < best_d:
                                    best_d = d
                                    zone = z
                        if zone is None or not self._can_clear_signal_in_time(
                            state, zone
                        ):
                            desired_speed = self._apply_approach_signal_braking(
                                state,
                                stop_distance,
                                desired_speed,
                                blocking_controls,
                                brake_dist=YELLOW_SIGNAL_BRAKE_DIST,
                                creep_dist=RED_SIGNAL_CREEP_DIST,
                            )
                        elif stop_distance >= YELLOW_COMMIT_DISTANCE:
                            desired_speed = min(desired_speed, self.base_speed * 0.45)

                    if state["stop_active"] and 0 < stop_distance < RED_SIGNAL_CREEP_DIST:
                        desired_speed = min(desired_speed, CAR_CREEP_SPEED)

        # Strong player-avoidance behavior: brake early when player is in/near lane ahead.
        if self.vertical:
            player_ahead = (player_body_rect.centery - self.rect.centery) * self.direction
            player_lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
        else:
            player_ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
            player_lane_gap = abs(player_body_rect.centery - self.rect.centery)

        if ped_legal_crossing and respect_player and player_lane_gap < 58:
            for state in road_states:
                if not collide(state["crosswalk"], player_body_rect):
                    continue
                if not self._in_crosswalk_lane(state):
                    continue
                ped_axis = self._signal_stop_axis(state["crosswalk"])
                ped_stop_dist = self._distance_to_signal_stop(ped_axis)
                if 0 < ped_stop_dist < RED_SIGNAL_BRAKE_DIST:
                    desired_speed = 0
                    break
        elif respect_player and 0 < player_ahead < 220 and player_lane_gap < 52:
            if will_yield_to_player:
                if player_ahead < 70:
                    desired_speed = 0
                elif player_ahead < 120:
                    desired_speed = min(desired_speed, self.base_speed * 0.22)
                else:
                    desired_speed = min(desired_speed, self.base_speed * 0.45)
            else:
                desired_speed = min(desired_speed, self.base_speed * 0.78)

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE and self._turn_phase not in (
            "turning",
            "settling",
        ):
            desired_speed = self._apply_lane_follow_speed(lane_peers, desired_speed)

        if self._turn_phase not in ("turning", "settling"):
            for other in move_peers:
                if other is self:
                    continue
                if self._conflicts_with_committed_turner(other, intersection_zones):
                    desired_speed = 0.0
                    break
                if other._turn_phase in ("turning", "settling") and rects_overlap(
                    self._collision_shell.inflate(32, 32),
                    other._collision_shell,
                ):
                    desired_speed = 0.0
                    break
                if not self._other_in_active_turn(other):
                    continue
                if rects_overlap(
                    self._collision_shell.inflate(28, 28),
                    other._collision_shell,
                ):
                    desired_speed = min(desired_speed, self.base_speed * 0.22)
                    break

        desired_speed = min(desired_speed, ramp_cap)
        if self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
            accel = self.base_speed / CAR_SPAWN_RAMP_FRAMES
        else:
            accel = self.acceleration

        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + accel)
        else:
            self.current_speed = max(desired_speed, self.current_speed - self.brake_strength)

        signed_speed = self.current_speed * self.direction

        blocked_by_line = False
        if signed_speed != 0:
            for state in blocking_controls:
                stop_axis = self._signal_stop_axis(state["crosswalk"])
                if self.vertical:
                    if self.direction > 0 and self.rect.bottom + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.bottom = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.top + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.top = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                else:
                    if self.direction > 0 and self.rect.right + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.right = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.left + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.left = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                if blocked_by_line:
                    break

        if self._turn_phase == "turning":
            self._steer_through_turn(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,
            )
        elif self._turn_phase == "settling":
            self._settle_turn_exit(roads, move_peers, intersection_zones)
        elif blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += signed_speed
            else:
                next_rect.x += signed_speed

            if self._turn_phase == "to_hub":
                next_rect = self._cap_next_rect_to_hub(next_rect)

            if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                next_rect = self._cap_next_rect_same_lane(next_rect, lane_peers)
                if self._peers_may_block_move(next_rect, move_peers):
                    next_rect = self._cap_next_rect_all_cars(next_rect, move_peers)
                if self._planned_move_conflicts_active_turn(
                    next_rect, move_peers, intersection_zones
                ):
                    if not intersection_creep:
                        next_rect = self.rect.copy()

            entry_blocked = (
                signed_speed != 0
                and self._turn_phase not in ("turning", "settling")
                and self._intersection_entry_blocked(
                    next_rect,
                    road_states,
                    intersection_zones,
                    lane_peers,
                    move_peers,
                )
            )
            if entry_blocked:
                next_rect = self.rect.copy()

            blocked = False
            creep_cap = None
            my_n = sprites.car_collision_rect_into(
                next_rect, self.vertical, self._body_rect_scratch
            )
            in_ix_move = self._in_or_entering_intersection(next_rect, intersection_zones)
            if signed_speed != 0:
                if ENABLE_CAR_CAR_COLLISION:
                    blocked = self._intersection_move_blocked(
                        next_rect,
                        move_peers if in_ix_move else lane_peers,
                        intersection_zones,
                        allow_perp_creep=intersection_creep,
                    )
                    if not blocked and self._shell_hits_any_car(
                        next_rect, self.vertical, move_peers, shell=my_n
                    ):
                        if in_ix_move and intersection_creep and not self._hard_block_after_cap(
                            next_rect, move_peers, True, intersection_zones
                        ):
                            creep_cap = CAR_CREEP_SPEED
                        else:
                            blocked = True
                    if not blocked:
                        for other in lane_peers:
                            if other is self:
                                continue
                            if other.vertical != self.vertical or other.direction != self.direction:
                                continue
                            if not self._same_lane(other, CAR_BLOCK_LANE_GAP):
                                continue
                            if not collide(my_n, other._collision_shell):
                                continue
                            gap, _ = self._distance_to_other(other)
                            if gap <= 0:
                                blocked = True
                                break
                            if gap < 26:
                                blocked = True
                                break
                            if gap < 52 and other.current_speed < 1.2:
                                creep_cap = CAR_CREEP_SPEED
                                break
                elif ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                    if (
                        in_ix_move
                        and not intersection_creep
                        and self._entry_blocks_moving_cross_traffic(
                            next_rect, move_peers, intersection_zones
                        )
                    ):
                        creep_cap = CAR_CREEP_SPEED * 0.4
                    soft_cap = self._soft_overlap_creep_cap(
                        next_rect, move_peers, lane_peers, intersection_zones
                    )
                    if soft_cap is not None:
                        creep_cap = (
                            soft_cap
                            if creep_cap is None
                            else min(creep_cap, soft_cap)
                        )
                pbb = (
                    player_body_block
                    if player_body_block is not None
                    else player_body_rect.inflate(4, 4)
                )
                if (
                    not blocked
                    and not ped_legal_crossing
                    and player_feet_road
                    and collide(my_n, pbb)
                ):
                    blocked = True

            if blocked or entry_blocked:
                self.current_speed = 0
                self.speed = 0
            elif creep_cap is not None and signed_speed != 0:
                creep = min(abs(signed_speed), creep_cap) * self.direction
                self.speed = creep
                self.current_speed = abs(creep)
                if self.vertical:
                    self.rect.y += int(creep)
                else:
                    self.rect.x += int(creep)
            elif signed_speed != 0:
                self.speed = signed_speed
                self.rect = next_rect

        self.rect.clamp_ip(world_rect.inflate(300, 300))
        if self._turn_phase == "to_hub":
            self._snap_to_hub_approach(max_past=TURN_HUB_HOLD_DIST)
            self._try_start_turn_at_hub(
                roads,
                intersection_zones,
                move_peers,
                player_body_rect,
                ped_legal_crossing,

            )
        if self._turn_phase == "turning":
            self._turn_arc_age += 1
        elif self._turn_phase == "settling":
            self._turn_arc_age += 1
        else:
            self._turn_arc_age = 0
        turn_stall_zone = (
            self._turn_phase == "to_hub"
            or inside_intersection
            or (
                self._turn_phase in ("turning", "settling")
                and intersection_zones
                and self._approaching_or_in_intersection(intersection_zones)
            )
        )
        if self._turn_phase in ("to_hub", "turning", "settling") and turn_stall_zone:
            if self.current_speed < 0.35:
                self._turn_blocked_frames += 1
            elif self._turn_blocked_frames > 0:
                self._turn_blocked_frames = max(0, self._turn_blocked_frames - 2)
        else:
            self._turn_blocked_frames = 0
        if self._turn_phase == "turning":
            stall_center = (round(self._turn_px), round(self._turn_py))
            if stall_center == self._turn_stall_center:
                self._turn_stall_frames += 1
            else:
                self._turn_stall_frames = 0
                self._turn_stall_center = stall_center
            if (
                self._turn_stall_frames >= TURN_STALL_ABORT_FRAMES
                and intersection_zones
                and self._rect_in_intersection(self.rect, intersection_zones)
            ):
                zone = self._intersection_zone_for_turn_planning(
                    intersection_zones, roads
                )
                if zone is None:
                    zone = self._intersection_zone_at(intersection_zones)
                if zone is not None:
                    self._freeze_blocked_turn_in_intersection(
                        intersection_zones,
                        roads,
                        move_peers,
                        player_body_rect,
                        ped_legal_crossing,
                        zone,
                    )
            elif self._turn_stall_frames >= TURN_STALL_ABORT_FRAMES:
                zone = self._intersection_zone_for_turn_planning(
                    intersection_zones, roads
                )
                if zone is None:
                    zone = self._intersection_zone_at(intersection_zones)
                if self._turn_phase in ("turning", "settling") and zone is not None:
                    self._freeze_blocked_turn_in_intersection(
                        intersection_zones,
                        roads,
                        move_peers,
                        player_body_rect,
                        ped_legal_crossing,
                        zone,
                    )
                else:
                    self._hold_turn_and_replan(
                        intersection_zones,
                        roads,
                        move_peers,
                        player_body_rect,
                        ped_legal_crossing,
                    )
        if self._turn_phase in ("to_hub", "turning", "settling"):
            self._mitigate_turn_peer_deadlock(
                move_peers, intersection_zones, roads
            )
        if self._turn_phase == "turning":
            turn_abort_limit = TURN_PATH_BLOCKED_ABORT_FRAMES
        elif self._turn_phase == "to_hub":
            turn_abort_limit = TURN_TO_HUB_ABORT_FRAMES
        else:
            turn_abort_limit = TURN_ABORT_FRAMES
        if self._turn_blocked_frames >= turn_abort_limit:
            if self._turn_phase in ("turning", "settling"):
                zone = self._intersection_zone_for_turn_planning(
                    intersection_zones, roads
                )
                if zone is None:
                    zone = self._intersection_zone_at(intersection_zones)
                if zone is not None:
                    self._freeze_blocked_turn_in_intersection(
                        intersection_zones,
                        roads,
                        move_peers,
                        player_body_rect,
                        ped_legal_crossing,
                        zone,
                    )
            else:
                self._hold_turn_and_replan(
                    intersection_zones,
                    roads,
                    move_peers,
                    player_body_rect,
                    ped_legal_crossing,
                )

        if (frame_index + self.spawn_id) % SURFACE_CHECK_INTERVAL == 0:
            self._anchor_network_position(roads, intersection_zones, world_rect)
        removal = self._removal_reason(
            roads, intersection_zones, world_rect, frame_index
        )
        if removal is not None:
            _notify_car_removed(self)
            self.kill()
        self._sync_collision_shell()
        in_ix_rect = bool(intersection_zones) and self._rect_in_intersection(
            self.rect, intersection_zones
        )
        if (
            self.road_index is not None
            and self._turn_phase not in ("to_hub", "turning", "settling")
            and not in_ix_rect
        ):
            if self.current_speed < 0.25 and self._stopped_frames > 8:
                snap_nudge = 0
            elif self._spawn_age < CAR_SPAWN_RAMP_FRAMES:
                snap_nudge = 4
            else:
                snap_nudge = None
            self._snap_center_to_left_lane(roads, max_nudge=snap_nudge)

        if self.current_speed < 0.25:
            self._stopped_frames += 1
        else:
            self._stopped_frames = 0
        if self.alive() and honk_allowed:
            if (frame_index + self.spawn_id) % HONK_CHECK_INTERVAL == 0:
                pb = player_body_rect
                if (
                    abs(self.rect.centerx - pb.centerx) < PLAYER_CAR_QUERY_PAD
                    and abs(self.rect.centery - pb.centery) < PLAYER_CAR_QUERY_PAD
                ):
                    self.evaluate_honk(
                        player_body_rect,
                        player_on_crosswalk,
                        honk_allowed,
                        game_time,
                    )


def _lane_bucket_key(car) -> tuple:
    if car.vertical:
        return (1, car.direction, car.rect.centerx // LANE_BUCKET_SIZE)
    return (0, car.direction, car.rect.centery // LANE_BUCKET_SIZE)


def _build_lane_buckets(car_list) -> dict:
    buckets: dict[tuple, list] = {}
    for car in car_list:
        if not car.alive():
            continue
        key = _lane_bucket_key(car)
        lane = buckets.get(key)
        if lane is None:
            buckets[key] = [car]
        else:
            lane.append(car)
    return buckets


def _lane_peers_for(car, buckets: dict, out: list) -> list:
    out.clear()
    k = _lane_bucket_key(car)
    for delta in (-1, 0, 1):
        lane = buckets.get((k[0], k[1], k[2] + delta))
        if lane:
            out.extend(lane)
    return out

