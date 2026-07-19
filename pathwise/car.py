"""Vehicle entity, spatial index, and lane-peer helpers."""

from __future__ import annotations

import math
import random

from dataclasses import dataclass

from map_generation.lane_geometry import lane_center_xy
from map_generation.traffic_schedule import MIN_ALONG_GAP, RECT_COLLIDE_PAD
from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect, collide, clip_rect, contains_rect, rect_overlap_area, rects_overlap
from pathwise.traffic_signal_layout import (
    APPROACH_EAST,
    APPROACH_NORTH,
    APPROACH_SOUTH,
    APPROACH_WEST,
)
from pathwise.modifiers import high_speed, highway, ignored, lag, lawless, rainy_roads, untrustworthy, variable_speed_zones
from pathwise.sim_constants import *  # noqa: F403
import pathwise.sim_constants as _tune

_car_removed_callback = None
_traffic_map_seed = 0
_intersection_zones_shell: list = []


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
    lane_index: int = 0


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


def _separation_peers(
    car,
    alive: list,
    spatial: "CarSpatialIndex | None",
    scratch: list,
) -> list:
    if spatial is not None:
        return spatial.nearby(car._collision_shell, _tune.SHELL_SEP_PEER_PAD, scratch)
    return alive


def _fleet_has_shell_overlap(
    cars: list,
    spatial: "CarSpatialIndex | None",
    scratch: list,
) -> bool:
    alive = [c for c in cars if c.alive()]
    for car in alive:
        peers = _separation_peers(car, alive, spatial, scratch)
        for other in peers:
            if other is car:
                continue
            if collide(car._collision_shell, other._collision_shell):
                return True
    return False


def _resolve_all_shell_overlaps(
    car_list: list,
    spatial: "CarSpatialIndex | None" = None,
    scratch: list | None = None,
) -> None:
    """One deterministic separation pass after all cars move."""
    if not ENABLE_CAR_CAR_SOFT_AVOIDANCE:
        return
    alive = sorted((c for c in car_list if c.alive()), key=lambda c: c.spawn_id)
    sep_passes = 1 if len(alive) > _tune.SHELL_SEP_FLEET_THRESHOLD else _tune.SHELL_PENETRATION_PASSES
    for car in alive:
        car._resolve_shell_penetration(
            alive,
            max_nudge=SHELL_PENETRATION_MAX_NUDGE,
            passes=sep_passes,
        )
    for car in alive:
        if car.current_speed >= 0.25:
            continue
        car._sync_collision_shell()
        for other in alive:
            if other is car or other.current_speed >= 0.25:
                continue
            if collide(car._collision_shell, other._collision_shell):
                car._resolve_shell_penetration(
                    alive,
                    max_nudge=max(SHELL_PENETRATION_MAX_NUDGE, 12),
                    passes=2,
                )
                break


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
        lane_index: int = 0,
    ):
        super().__init__()
        self.direction = 1 if speed >= 0 else -1
        self.vertical = vertical
        self.spawn_id = spawn_id
        self.road_index = road_index
        self.lane_index = int(lane_index)
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
        self._spawn_age = 0
        self._spawn_clear_ix_frames = 0
        self._exit_lane_snap_steps = 0
        self._exit_lane_target = None
        # Straight-only mode keeps minimal turn fields for legacy readers.
        self.turn_signal = 0
        self._turn_phase = "none"
        self._turn_display_angle = 0.0
        self._turn_exit = None
        self._turn_hold_frames = 0
        self._turn_reservation_frames = 0
        self._turn_abort_cooldown = 0
        self._turn_peer_retreat_cooldown = 0
        self._turn_snap_travel = 0.0
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None
        self._turn_arc_age = 0
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
        return self.vertical, self.direction

    def _sync_collision_shell(self, force: bool = False):
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
        tcx, tcy = lane_center_xy(
            road, self.direction, lane_index=getattr(self, "lane_index", 0)
        )
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
        self,
        player_body_rect,
        player_on_crosswalk: bool,
        honk_allowed: bool,
        game_time,
        *,
        conflict_car_vertical: bool | None = None,
    ):
        self.honk_risk_pending = False
        if not honk_allowed:
            return
        if (
            conflict_car_vertical is not None
            and self.vertical != conflict_car_vertical
        ):
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
        return False

    def _committed_intersection_turn(self, intersection_zones=None) -> bool:
        return False

    def _conflicts_with_committed_turner(
        self, other, intersection_zones=None, *, pad: int = 10, road_states=None
    ) -> bool:
        return False

    def _planned_move_conflicts_active_turn(
        self, next_rect, peers, intersection_zones
    ) -> bool:
        return False

    def _exit_blocked_by_active_turn(self, next_rect, peers, intersection_zones) -> bool:
        return False
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

    def _approaching_or_in_intersection(self, intersection_zones, extra: int = 0) -> bool:
        if not intersection_zones:
            return False
        if self._rect_in_intersection(self.rect, intersection_zones):
            return True
        lead = IX_QUERY_PAD + extra
        for zone in intersection_zones:
            d = self._distance_to_intersection_entry(zone)
            if d is not None and 0 <= d < lead:
                return True
        return False

    def _effective_approach_light(self, state: dict) -> str:
        return state.get("light_state", "green")

    def _effective_seconds_to_change(self, state: dict) -> float:
        return float(state.get("seconds_to_change", 0.0))

    def _car_approach_label(self) -> str:
        if self.vertical:
            return APPROACH_NORTH if self.direction > 0 else APPROACH_SOUTH
        return APPROACH_WEST if self.direction > 0 else APPROACH_EAST

    def _signal_orient_and_label(self) -> tuple[str, str]:
        use_entry = self._turn_phase in ("to_hub", "turning", "settling") or (
            getattr(self, "_use_entry_approach_signal", False)
            and self._turn_phase == "none"
        )
        if use_entry:
            entry_v = (
                self._turn_entry_vertical
                if self._turn_phase != "to_hub"
                else self.vertical
            )
            entry_d = (
                self._turn_entry_direction
                if self._turn_phase != "to_hub"
                else self.direction
            )
        else:
            entry_v = self.vertical
            entry_d = self.direction
        orient = "vertical" if entry_v else "horizontal"
        if entry_v:
            label = APPROACH_NORTH if entry_d > 0 else APPROACH_SOUTH
        else:
            label = APPROACH_WEST if entry_d > 0 else APPROACH_EAST
        return orient, label

    def _on_approach_crosswalk(self, crosswalk: Rect) -> bool:
        return crosswalk.collidepoint(
            self.rect.centerx, self.rect.centery
        ) or collide(self.rect, crosswalk)

    def _approach_crosswalk_relevant(self, crosswalk: Rect) -> bool:
        """Signals for crosswalks behind travel are ignored (open-road cruise)."""
        if not self._in_crossing_lane(crosswalk):
            return False
        if self._on_approach_crosswalk(crosswalk):
            return True
        stop_axis = self._signal_stop_axis(crosswalk)
        stop_dist = self._distance_to_signal_stop(stop_axis)
        if stop_dist < -STOP_LINE_GAP:
            return False
        return stop_dist <= RED_SIGNAL_BRAKE_DIST * 2.5

    def _states_for_our_approach(self, road_states) -> list:
        orient, label = self._signal_orient_and_label()
        return [
            s
            for s in road_states
            if s.get("direction") == orient and s.get("approach") == label
        ]

    def _straight_light_at_approach(self, road_states) -> str | None:
        if not road_states:
            return None
        approach = self._approach_state_for_signal(road_states)
        if approach is None:
            return None
        return approach.get("light_state", "green")

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
        if not intersection_zones:
            return False
        key = (rect.left, rect.top, rect.right, rect.bottom)
        cached = getattr(self, "_ix_rect_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        hit = any(rects_overlap(zone, rect) for zone in intersection_zones)
        self._ix_rect_cache = (key, hit)
        return hit

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
        """Segment gaps between intersections: center can miss thin road rects."""
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

    def _nudge_clear_intersection_tail(
        self, intersection_zones, *, max_step_total: int | None = None
    ) -> None:
        """Creep forward until the collision shell leaves the intersection box."""
        if not intersection_zones:
            return
        self._sync_collision_shell(force=True)
        if not any(collide(z, self._collision_shell) for z in intersection_zones):
            return
        step = max(2, int(CAR_CREEP_SPEED * 2))
        moved = 0
        for _ in range(48):
            if not any(collide(z, self._collision_shell) for z in intersection_zones):
                break
            if max_step_total is not None and moved >= max_step_total:
                break
            if self.vertical:
                self.rect.y += self.direction * step
            else:
                self.rect.x += self.direction * step
            moved += step
            self._sync_collision_shell(force=True)

    def _intersection_zone_at(self, intersection_zones):
        for zone in intersection_zones:
            if collide(zone, self.rect):
                return zone
        return None

    def _approach_intersection_zone(self, intersection_zones):
        """Zone the car is in or approaching (for signal clearance at the crosswalk)."""
        if not intersection_zones:
            return None
        in_zone = self._intersection_zone_at(intersection_zones)
        if in_zone is not None:
            return in_zone
        best = None
        best_d = 1e9
        for zone in intersection_zones:
            d = self._distance_to_intersection_entry(zone)
            if d is None or d < 0 or d > RED_SIGNAL_BRAKE_DIST * 2:
                continue
            if d < best_d:
                best_d = d
                best = zone
        return best

    def _spawn_ramp_limit(self) -> int:
        if highway.is_active():
            return highway.spawn_ramp_frames()
        return CAR_SPAWN_RAMP_FRAMES

    def _spawn_ramp_cap(self) -> float:
        ramp = self._spawn_ramp_limit()
        if self._spawn_age >= ramp:
            return self.base_speed
        t = self._spawn_age / max(1, ramp)
        ease = t * t * (3.0 - 2.0 * t)
        return self.base_speed * ease

    def _has_exited_map_along_route(
        self, roads, intersection_zones, world_rect
    ) -> bool:
        """Despawn only after the car fully leaves the map (exit corridor handles segment ends)."""
        if self._spawn_age < self._spawn_ramp_limit():
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
        if self._spawn_age < self._spawn_ramp_limit():
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

    def _obeys_traffic_signals(self) -> bool:
        return lawless.signals_enabled() and highway.signals_enabled()

    def _runs_red_lights(self) -> bool:
        if not self._obeys_traffic_signals():
            return True
        return untrustworthy.should_skip_red_stop(spawn_id=self.spawn_id)

    def _ignores_player(self) -> bool:
        return (
            ignored.should_disable_player_yield()
            or highway.should_disable_player_yield()
            or untrustworthy.should_disable_player_yield(spawn_id=self.spawn_id)
        )

    def _skips_player_body_block(self) -> bool:
        return (
            ignored.should_skip_player_body_block()
            or highway.should_skip_player_body_block()
            or untrustworthy.should_skip_player_body_block(spawn_id=self.spawn_id)
        )

    def _shared_intersection_zone(self, other, intersection_zones, *, pad: int = 96):
        if not intersection_zones:
            return None
        for zone in intersection_zones:
            expanded = zone.inflate(pad * 2, pad * 2)
            if rects_overlap(expanded, self.rect) and rects_overlap(expanded, other.rect):
                return zone
        return None

    def _propagate_unlawful_to_cars_ahead(self, peers, intersection_zones) -> None:
        """If this car is lawless, infect cars ahead in the same intersection queue."""
        if not untrustworthy.is_active() or not self._runs_red_lights():
            return
        if not intersection_zones:
            return
        for other in peers:
            if other is self or not other.alive():
                continue
            if other.vertical != self.vertical or other.direction != self.direction:
                continue
            if not self._same_lane(other):
                continue
            if self._shared_intersection_zone(other, intersection_zones) is None:
                continue
            ahead, _lane_gap = self._distance_to_other(other)
            if ahead <= 0 or ahead > untrustworthy.CONTAGION_RANGE_PX:
                continue
            untrustworthy.mark_unlawful(other.spawn_id)

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

    def _would_block_at_signal_stop(self, stop_axis: int, signed_speed: float) -> bool:
        """True when a forward move would cross the stop line from the approach side."""
        if signed_speed == 0:
            return False
        if self._distance_to_signal_stop(stop_axis) < 0:
            return False
        if self.vertical:
            if self.direction > 0:
                return self.rect.bottom + signed_speed >= stop_axis - STOP_LINE_GAP
            return self.rect.top + signed_speed <= stop_axis + STOP_LINE_GAP
        if self.direction > 0:
            return self.rect.right + signed_speed >= stop_axis - STOP_LINE_GAP
        return self.rect.left + signed_speed <= stop_axis + STOP_LINE_GAP

    def _clamp_at_signal_stop(self, stop_axis: int) -> None:
        if self.vertical:
            if self.direction > 0:
                self.rect.bottom = stop_axis - STOP_LINE_GAP
            else:
                self.rect.top = stop_axis + STOP_LINE_GAP
        elif self.direction > 0:
            self.rect.right = stop_axis - STOP_LINE_GAP
        else:
            self.rect.left = stop_axis + STOP_LINE_GAP

    def _enforce_signal_stop_line(self, stop_axis: int) -> bool:
        """Clamp at stop line only for a minor overshoot past the line."""
        stop_dist = self._distance_to_signal_stop(stop_axis)
        if stop_dist < -STOP_LINE_GAP * 3 or stop_dist > STOP_LINE_GAP:
            return False
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
        if stop_distance >= brake_dist:
            return desired_speed
        light = self._effective_approach_light(state)
        if stop_distance < STOP_LINE_GAP and light == "red":
            if state not in blocking_controls:
                blocking_controls.append(state)
            return 0.0
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
        scoped = self._states_for_our_approach(road_states)
        if not scoped:
            scoped = road_states
        best = None
        best_d = 1e9
        for state in scoped:
            if not rects_overlap(self.rect, state["approach_rect"]):
                continue
            crosswalk = state["crosswalk"]
            if not self._in_crossing_lane(crosswalk):
                continue
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_distance = self._distance_to_signal_stop(stop_axis)
            on_crosswalk = crosswalk.collidepoint(self.rect.centerx, self.rect.centery)
            if stop_distance <= -STOP_LINE_GAP and not on_crosswalk:
                continue
            if not self._approach_crosswalk_relevant(crosswalk):
                continue
            if stop_distance < best_d:
                best_d = stop_distance
                best = state
        return best

    def _approach_state_for_signal(self, road_states):
        """Approach signal for this travel direction, including inside the intersection."""
        scoped = self._states_for_our_approach(road_states)
        if not scoped:
            scoped = list(road_states) if road_states else []
        for state in scoped:
            crosswalk = state["crosswalk"]
            if crosswalk.collidepoint(self.rect.centerx, self.rect.centery):
                return state
        hit = self._nearest_approach_state(road_states)
        if hit is not None:
            return hit
        if not scoped:
            return None
        best = None
        best_key = 1e9
        brake = RED_SIGNAL_BRAKE_DIST * 2
        for state in scoped:
            crosswalk = state["crosswalk"]
            if not self._approach_crosswalk_relevant(crosswalk):
                continue
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_distance = self._distance_to_signal_stop(stop_axis)
            if abs(stop_distance) > brake:
                continue
            key = abs(stop_distance)
            if key < best_key:
                best_key = key
                best = state
        return best

    def _committed_past_signal_stop(self, state: dict) -> bool:
        """Past the stop line on the approach crosswalk: must clear, not re-queue."""
        crosswalk = state.get("crosswalk")
        if crosswalk is None:
            return False
        if not self._in_crossing_lane(crosswalk):
            return False
        stop_axis = self._signal_stop_axis(crosswalk)
        return self._distance_to_signal_stop(stop_axis) <= 0

    def _can_clear_signal_in_time(self, state, zone: Rect) -> bool:
        light = self._effective_approach_light(state)
        if self._committed_past_signal_stop(state) and light in ("green", "yellow"):
            return True
        clear_dist = self._clear_distance_through_zone(zone)
        if clear_dist <= 0:
            return True
        speed_px_per_frame = max(self.current_speed, CAR_CREEP_SPEED * 0.45, 0.8)
        speed_px_per_s = speed_px_per_frame * SIM_FPS
        time_needed = clear_dist / speed_px_per_s
        time_left = max(0.0, self._effective_seconds_to_change(state))
        if light == "green":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S
        if light == "yellow":
            return time_needed <= time_left + INTERSECTION_CLEAR_BUFFER_S * 0.5
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

        approach = self._approach_state_for_signal(road_states)
        committed = (
            approach is not None and self._committed_past_signal_stop(approach)
        )
        signals_on = self._obeys_traffic_signals()
        if approach is not None and signals_on:
            light = self._effective_approach_light(approach)
            cannot_clear = not self._can_clear_signal_in_time(approach, target_zone)
            if light == "red":
                if entering and not self._runs_red_lights():
                    return True
            elif light == "yellow" and cannot_clear and not committed:
                return True
            # Green never hard-blocks for cannot_clear timing. Valid green stops are
            # player yield / untrustworthy handling elsewhere, not signal entry gates.

        if not entering:
            return False

        # Past the stop line on green (or with signals off): clear into the box instead
        # of freezing for moving cross traffic.
        treat_as_green = (not signals_on) or (
            approach is not None
            and self._effective_approach_light(approach) == "green"
        )
        if committed and treat_as_green:
            if self._exit_blocked_by_active_turn(
                next_rect, move_peers or peers, intersection_zones
            ):
                return True
            return False

        # On green before the stop line (or unsignalized): keep advancing.
        if treat_as_green:
            if self._exit_blocked_by_active_turn(
                next_rect, move_peers or peers, intersection_zones
            ):
                return True
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

    def _inside_intersection(self, intersection_zones) -> bool:
        if not intersection_zones:
            return False
        return any(collide(z, self.rect) for z in intersection_zones)

    def _crosswalk_advance_blocked(
        self, next_rect, road_states, intersection_zones
    ) -> bool:
        """Do not step onto or creep across the crosswalk unless the signal allows clearing."""
        if not self._obeys_traffic_signals() or self._runs_red_lights():
            return False
        if self._turn_phase in ("turning", "settling", "to_hub"):
            return False
        if not road_states:
            return False
        approach = self._approach_state_for_signal(road_states)
        if approach is None:
            return False
        crosswalk = approach["crosswalk"]
        if not self._approach_crosswalk_relevant(crosswalk):
            return False
        if not self._in_crossing_lane(crosswalk):
            return False
        if not collide(next_rect, crosswalk):
            return False
        if self._inside_intersection(intersection_zones):
            return False
        if collide(self.rect, crosswalk):
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_dist = self._distance_to_signal_stop(stop_axis)
            if stop_dist <= 0:
                light = self._effective_approach_light(approach)
                if light == "red":
                    return True
                if light == "yellow":
                    zone = self._approach_intersection_zone(intersection_zones)
                    if zone is None:
                        return False
                    return not self._can_clear_signal_in_time(approach, zone)
        light = self._effective_approach_light(approach)
        if light == "red":
            return True
        if light == "green":
            return False
        zone = self._approach_intersection_zone(intersection_zones)
        if zone is None:
            return False
        return not self._can_clear_signal_in_time(approach, zone)

    def _retreat_from_crosswalk_on_red(
        self,
        state: dict,
        *,
        inside_intersection: bool,
        intersection_zones,
        allow_overshoot: bool = False,
    ) -> bool:
        """Clamp cars behind the stop line instead of idling on the crosswalk."""
        if allow_overshoot or self._runs_red_lights():
            return False
        if inside_intersection or self._inside_intersection(intersection_zones):
            return False
        if self._turn_phase in ("turning", "settling", "to_hub"):
            return False
        crosswalk = state["crosswalk"]
        if not self._in_crossing_lane(crosswalk) or not collide(self.rect, crosswalk):
            return False
        light = self._effective_approach_light(state)
        if light != "red":
            return False
        stop_axis = self._signal_stop_axis(crosswalk)
        self._clamp_at_signal_stop(stop_axis)
        self.current_speed = 0.0
        self.speed = 0.0
        return True

    def _intersection_advance_blocked_on_red(
        self, next_rect, road_states, intersection_zones
    ) -> bool:
        """Red gates approach entry; cars already inside the box may clear."""
        if self._turn_reservation_frames > 0:
            return False
        if self._turn_phase == "turning" and self._turn_arc_travel > 0:
            return False
        if self._turn_phase in ("settling", "to_hub") and self._turn_exit:
            return False
        if not intersection_zones:
            return False
        if not self._in_or_entering_intersection(next_rect, intersection_zones):
            return False
        if self._inside_intersection(intersection_zones):
            return False
        return False

    def _intersection_move_blocked(
        self, next_rect, peers, intersection_zones, allow_perp_creep=False, *,
        block_cross_traffic: bool = True,
    ):
        if not ENABLE_CAR_CAR_COLLISION:
            return False
        if not intersection_zones:
            return False
        if not self._in_or_entering_intersection(next_rect, intersection_zones):
            return False
        if (
            block_cross_traffic
            and not allow_perp_creep
            and self._entry_blocks_moving_cross_traffic(
                next_rect, peers, intersection_zones
            )
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
        if variable_speed_zones.is_active():
            desired_speed *= variable_speed_zones.speed_mult_for_car(self, roads)
        blocking_controls: list = []
        self._spawn_age += 1
        desired_speed = min(desired_speed, self._spawn_ramp_cap())

        nearest = self._nearest_approach_state(road_states)
        if nearest is not None:
            approach_light = self._effective_approach_light(nearest)
            stop_axis = self._signal_stop_axis(nearest["crosswalk"])
            stop_distance = self._distance_to_signal_stop(stop_axis)
            if approach_light == "red":
                if not self._runs_red_lights():
                    desired_speed = self._apply_approach_signal_braking(
                        nearest,
                        stop_distance,
                        desired_speed,
                        blocking_controls,
                        brake_dist=RED_SIGNAL_BRAKE_DIST,
                        creep_dist=RED_SIGNAL_CREEP_DIST,
                    )
        # Snap back only a minor overshoot at a red light (e.g. spawned 1-2 frames past).
        if (
            not self._runs_red_lights()
            and self._turn_phase == "none"
            and self.current_speed < 0.5
        ):
            for state in self._states_for_our_approach(road_states) or road_states:
                cw = state["crosswalk"]
                if not self._approach_crosswalk_relevant(cw):
                    continue
                if not self._in_crossing_lane(cw):
                    continue
                sa = self._signal_stop_axis(cw)
                dist = self._distance_to_signal_stop(sa)
                if -STOP_LINE_GAP * 3 <= dist < -STOP_LINE_GAP:
                    light = self._effective_approach_light(state)
                    if light == "red":
                        self._enforce_signal_stop_line(sa)
                        break

        ramp = self._spawn_ramp_limit()
        scale = high_speed.car_speed_scale() * lag.physics_scale()
        desired_speed *= scale
        accel = (
            self.base_speed * scale / max(1, ramp)
            if self._spawn_age < ramp
            else self.acceleration * scale
        )
        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + accel)
        else:
            brake = rainy_roads.effective_brake_strength(self.brake_strength)
            self.current_speed = max(desired_speed, self.current_speed - brake)

        signed_speed = self.current_speed * self.direction
        blocked_by_line = False
        for state in blocking_controls:
            stop_axis = self._signal_stop_axis(state["crosswalk"])
            if self._would_block_at_signal_stop(stop_axis, signed_speed):
                self._clamp_at_signal_stop(stop_axis)
                blocked_by_line = True
            elif self._enforce_signal_stop_line(stop_axis):
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
            if player_body_rect is not None and not self._skips_player_body_block():
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
        if variable_speed_zones.is_active():
            desired_speed *= variable_speed_zones.speed_mult_for_car(self, roads)
        blocking_controls = []
        yield_roll = (_traffic_map_seed + self.spawn_id * 17) % 100
        will_yield_to_player = yield_roll < int(PLAYER_AVOIDANCE_CHANCE * 100)
        if ped_legal_crossing:
            will_yield_to_player = True
        car_respect_player = respect_player and not self._ignores_player()
        if self._ignores_player():
            will_yield_to_player = False
        runs_red = self._runs_red_lights()
        self._propagate_unlawful_to_cars_ahead(lane_peers or move_peers, intersection_zones)

        inside_intersection = bool(intersection_zones) and self._rect_in_intersection(
            self.rect, intersection_zones
        )
        if self._spawn_clear_ix_frames > 0:
            self._spawn_clear_ix_frames -= 1
            desired_speed = max(desired_speed, CAR_CREEP_SPEED)
        if (
            inside_intersection
            and self.turn_signal != 0
            and self._turn_phase == "none"
            and road_states
            and self._straight_light_at_approach(road_states) == "green"
            and self.current_speed < 0.5
        ):
            desired_speed = max(desired_speed, self.base_speed * 0.85)
        if not inside_intersection:
            self._use_entry_approach_signal = False
        if (
            inside_intersection
            and self._turn_phase not in ("turning", "to_hub", "settling")
            and (
                not road_states
                or self._intersection_advance_blocked_on_red(
                    self.rect, road_states, intersection_zones
                )
            )
        ):
            desired_speed = 0.0
            self.current_speed = 0.0
            self.speed = 0.0
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
        if self._exit_lane_snap_steps > 0 and self._turn_phase == "none":
            target = self._exit_lane_target
            if target is not None:
                tx, ty = target
                cx, cy = self.rect.center
                step = 10
                nx = cx + max(-step, min(step, tx - cx))
                ny = cy + max(-step, min(step, ty - cy))
                self.rect.center = (nx, ny)
                if abs(tx - nx) < 1.0 and abs(ty - ny) < 1.0:
                    self._exit_lane_target = None
            else:
                self._snap_center_to_left_lane(roads, max_nudge=8)
            self._exit_lane_snap_steps -= 1
            self._nudge_clear_intersection_tail(intersection_zones, max_step_total=10)
            self._sync_collision_shell()
        if self._turn_abort_cooldown > 0:
            self._turn_abort_cooldown -= 1
        if self._turn_peer_retreat_cooldown > 0:
            self._turn_peer_retreat_cooldown -= 1
        ramp_cap = self._spawn_ramp_cap()
        self.turn_signal = 0
        self._turn_phase = "none"
        self._turn_exit = None
        self._turn_hold_frames = 0
        self._turn_reservation_frames = 0

        if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
            if self._turn_phase not in ("turning", "settling") and len(lane_peers) > 1:
                self._resolve_same_lane_penetration(lane_peers)
        self._sync_collision_shell()

        for state in road_states:
            if not self._obeys_traffic_signals():
                break
            approach = state["approach_rect"]
            if not rects_overlap(self.rect, approach):
                continue

            crosswalk = state["crosswalk"]
            stop_axis = self._signal_stop_axis(crosswalk)
            stop_distance = self._distance_to_signal_stop(stop_axis)
            in_crossing_lane = self._in_crossing_lane(crosswalk)

            if in_crossing_lane and not self._approach_crosswalk_relevant(crosswalk):
                continue

            if in_crossing_lane:
                crosswalk_key = crosswalk.x * 31 + crosswalk.y
                overshoot_stop = rainy_roads.crosswalk_overshoot_enabled(
                    spawn_id=self.spawn_id,
                    crosswalk_key=crosswalk_key,
                )
                # Snap back over the stop line if the car is stopped at a red and
                # slightly overshot (e.g. spawned 1-2 frames past the line).  Only
                # correct minor overshoots (<= STOP_LINE_GAP * 3) so we never teleport
                # a car that is already deep inside the intersection.
                if (
                    not runs_red
                    and not overshoot_stop
                    and not inside_intersection
                    and self._turn_phase == "none"
                    and self.current_speed < 0.5
                    and -STOP_LINE_GAP * 3 <= stop_distance < -STOP_LINE_GAP
                    and self._effective_approach_light(state) == "red"
                ):
                    self._enforce_signal_stop_line(stop_axis)

                if self._turn_phase not in ("turning", "settling"):
                    approach_light = self._effective_approach_light(state)
                    if not inside_intersection:
                        brake_dist = RED_SIGNAL_BRAKE_DIST
                        if approach_light == "red" and collide(
                            crosswalk, player_body_rect
                        ):
                            brake_dist = RED_SIGNAL_BRAKE_DIST + 24
                        if approach_light == "red" and not runs_red:
                            if overshoot_stop and stop_distance < RED_SIGNAL_CREEP_DIST:
                                overshoot_px = rainy_roads.crosswalk_overshoot_distance_px(
                                    spawn_id=self.spawn_id,
                                    crosswalk_key=crosswalk_key,
                                )
                                if stop_distance <= -overshoot_px:
                                    desired_speed = 0.0
                                elif stop_distance < 0:
                                    # Past the line, still closing on overshoot depth.
                                    remain = overshoot_px + stop_distance
                                    frac = max(0.0, remain / max(1, overshoot_px))
                                    desired_speed = min(
                                        desired_speed, self.base_speed * 0.2 * frac
                                    )
                                else:
                                    desired_speed = min(
                                        desired_speed,
                                        self.base_speed
                                        * max(0.12, stop_distance / max(1, overshoot_px)),
                                    )
                            else:
                                desired_speed = self._apply_approach_signal_braking(
                                    state,
                                    stop_distance,
                                    desired_speed,
                                    blocking_controls,
                                    brake_dist=brake_dist,
                                    creep_dist=RED_SIGNAL_CREEP_DIST,
                                )
                        elif (
                            approach_light == "yellow"
                            and stop_distance < YELLOW_SIGNAL_BRAKE_DIST
                        ):
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
                                desired_speed = min(
                                    desired_speed, self.base_speed * 0.45
                                )

                        if (
                            not runs_red
                            and approach_light in ("red", "yellow")
                            and state["stop_active"]
                            and 0 < stop_distance < RED_SIGNAL_CREEP_DIST
                        ):
                            desired_speed = min(desired_speed, CAR_CREEP_SPEED)

                    self._retreat_from_crosswalk_on_red(
                        state,
                        inside_intersection=inside_intersection,
                        intersection_zones=intersection_zones,
                        allow_overshoot=overshoot_stop,
                    )

        # Strong player-avoidance behavior: brake early when player is in/near lane ahead.
        if self.vertical:
            player_ahead = (player_body_rect.centery - self.rect.centery) * self.direction
            player_lane_gap = abs(player_body_rect.centerx - self.rect.centerx)
        else:
            player_ahead = (player_body_rect.centerx - self.rect.centerx) * self.direction
            player_lane_gap = abs(player_body_rect.centery - self.rect.centery)

        if ped_legal_crossing and car_respect_player and player_lane_gap < 58:
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
        elif car_respect_player and 0 < player_ahead < 220 and player_lane_gap < 52:
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
                if self._conflicts_with_committed_turner(
                    other, intersection_zones, road_states=road_states
                ):
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
        if (
            inside_intersection
            and self._turn_phase not in ("turning", "settling", "to_hub")
            and road_states
            and self._intersection_advance_blocked_on_red(
                self.rect, road_states, intersection_zones
            )
        ):
            desired_speed = 0.0
        ramp = self._spawn_ramp_limit()
        scale = high_speed.car_speed_scale() * lag.physics_scale()
        desired_speed *= scale
        if self._spawn_age < ramp:
            accel = self.base_speed * scale / max(1, ramp)
        else:
            accel = self.acceleration * scale

        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + accel)
        else:
            brake = rainy_roads.effective_brake_strength(self.brake_strength)
            self.current_speed = max(desired_speed, self.current_speed - brake)

        signed_speed = self.current_speed * self.direction
        if (
            signed_speed != 0
            and inside_intersection
            and self._turn_phase not in ("turning", "settling", "to_hub")
            and road_states
            and self._intersection_advance_blocked_on_red(
                self.rect, road_states, intersection_zones
            )
        ):
            self.current_speed = 0.0
            self.speed = 0.0
            signed_speed = 0.0

        blocked_by_line = False
        if signed_speed != 0:
            for state in blocking_controls:
                stop_axis = self._signal_stop_axis(state["crosswalk"])
                if self._would_block_at_signal_stop(stop_axis, signed_speed):
                    self._clamp_at_signal_stop(stop_axis)
                    blocked_by_line = True
                if blocked_by_line:
                    break

        if blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            next_rect = self.rect.copy()
            if self.vertical:
                next_rect.y += signed_speed
            else:
                next_rect.x += signed_speed

            if ENABLE_CAR_CAR_SOFT_AVOIDANCE:
                next_rect = self._cap_next_rect_same_lane(next_rect, lane_peers)
                if self._peers_may_block_move(next_rect, move_peers):
                    next_rect = self._cap_next_rect_all_cars(next_rect, move_peers)

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

            advance_blocked = (
                signed_speed != 0
                and self._turn_phase not in ("turning", "settling")
                and self._intersection_advance_blocked_on_red(
                    next_rect, road_states, intersection_zones
                )
            )
            if advance_blocked:
                next_rect = self.rect.copy()

            crosswalk_blocked = (
                signed_speed != 0
                and self._crosswalk_advance_blocked(
                    next_rect, road_states, intersection_zones
                )
            )
            if crosswalk_blocked:
                next_rect = self.rect.copy()

            blocked = False
            creep_cap = None
            my_n = sprites.car_collision_rect_into(
                next_rect, self.vertical, self._body_rect_scratch
            )
            in_ix_move = self._in_or_entering_intersection(next_rect, intersection_zones)
            if signed_speed != 0:
                if ENABLE_CAR_CAR_COLLISION:
                    approach_state = (
                        self._approach_state_for_signal(road_states)
                        if road_states
                        else None
                    )
                    approach_is_green = (
                        approach_state is not None
                        and self._effective_approach_light(approach_state) == "green"
                    )
                    blocked = self._intersection_move_blocked(
                        next_rect,
                        move_peers if in_ix_move else lane_peers,
                        intersection_zones,
                        allow_perp_creep=intersection_creep,
                        block_cross_traffic=not approach_is_green,
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
                    and not self._skips_player_body_block()
                    and not ped_legal_crossing
                    and player_feet_road
                    and collide(my_n, pbb)
                ):
                    blocked = True

            if blocked or entry_blocked or advance_blocked:
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

        if (
            intersection_zones
            and self._inside_intersection(intersection_zones)
            and self._turn_phase != "turning"
            and (
                not road_states
                or self._intersection_advance_blocked_on_red(
                    self.rect, road_states, intersection_zones
                )
            )
        ):
            self.current_speed = 0.0
            self.speed = 0.0

        self.rect.clamp_ip(world_rect.inflate(300, 300))
        self._turn_arc_age = 0
        self._turn_blocked_frames = 0
        self._turn_stall_frames = 0
        self._turn_stall_center = None

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
            and self._exit_lane_snap_steps <= 0
        ):
            if self.current_speed < 0.25 and self._stopped_frames > 8:
                snap_nudge = 0
            elif self._spawn_age < self._spawn_ramp_limit():
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

