"""Detect car-shell and intersection anomalies in straight-only traffic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pathwise.geom import Rect, collide, rects_overlap
from pathwise.sim_constants import INTERSECTION_STUCK_CREEP_FRAMES

OVERLAP_REPORT_MIN_PAIRS = 1
GRIDLOCK_MIN_CARS = 3
GRIDLOCK_SPEED_THRESH = 0.3
PARTIAL_IX_STOP_FRAMES = 45
SPAWN_LANE_GAP_AHEAD_PX = 150


@dataclass
class CarAnomaly:
    kind: str
    sim_t: float
    frame: int
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "sim_t": round(self.sim_t, 3),
            "frame": self.frame,
            "summary": self.summary,
            "details": self.details,
        }


class SpectateTracker:
    def __init__(self) -> None:
        self.anomalies: list[CarAnomaly] = []
        self._overlap_cooldown = 0
        self._gridlock_streak = 0
        self._emitted_gridlock = False
        self._known_spawn_ids: set[int] = set()
        self._partial_ix_streak: dict[int, int] = {}
        self._emitted_partial_ix: set[int] = set()
        self.max_overlap_pairs = 0
        self.overlap_frames = 0
        self.pre_separation_overlap_frames = 0
        self.spawn_in_lane_ahead_count = 0
        self.partial_ix_stop_count = 0

    def observe_pre_separation(
        self,
        *,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
    ) -> list[CarAnomaly]:
        del frame, sim_t, intersection_zones
        alive = [c for c in cars if c.alive()]
        if _overlap_pairs(alive):
            self.pre_separation_overlap_frames += 1
        return []

    def observe(
        self,
        *,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
        road_states_for_car=None,
    ) -> list[CarAnomaly]:
        del road_states_for_car
        emitted: list[CarAnomaly] = []
        alive = [c for c in cars if c.alive()]

        pairs = _overlap_pairs(alive)
        if pairs:
            self.overlap_frames += 1
            self.max_overlap_pairs = max(self.max_overlap_pairs, len(pairs))
            if self._overlap_cooldown <= 0 and len(pairs) >= OVERLAP_REPORT_MIN_PAIRS:
                ids = sorted({a for pair in pairs for a in pair})
                anomaly = CarAnomaly(
                    kind="shell_overlap",
                    sim_t=sim_t,
                    frame=frame,
                    summary=f"{len(pairs)} overlapping pair(s), cars {ids[:8]}",
                    details={"pairs": pairs, "pair_count": len(pairs)},
                )
                self.anomalies.append(anomaly)
                emitted.append(anomaly)
                self._overlap_cooldown = 30
        if self._overlap_cooldown > 0:
            self._overlap_cooldown -= 1

        if intersection_zones:
            slow_in_ix = 0
            for car in alive:
                if car.current_speed >= GRIDLOCK_SPEED_THRESH:
                    continue
                if not _car_in_any_zone(car, intersection_zones):
                    continue
                if getattr(car, "_gridlock_frames", 0) >= INTERSECTION_STUCK_CREEP_FRAMES:
                    continue
                if getattr(car, "_stopped_frames", 0) >= 24:
                    continue
                slow_in_ix += 1
            if slow_in_ix >= GRIDLOCK_MIN_CARS:
                self._gridlock_streak += 1
            else:
                self._gridlock_streak = 0
            if self._gridlock_streak >= 90 and not self._emitted_gridlock:
                self._emitted_gridlock = True
                anomaly = CarAnomaly(
                    kind="intersection_gridlock",
                    sim_t=sim_t,
                    frame=frame,
                    summary=f"{slow_in_ix} slow cars in intersection(s) for 90+ frames",
                    details={"slow_car_count": slow_in_ix},
                )
                self.anomalies.append(anomaly)
                emitted.append(anomaly)

        current_ids = {c.spawn_id for c in alive}
        new_ids = current_ids - self._known_spawn_ids
        self._known_spawn_ids = current_ids
        seen_partial: set[int] = set()

        for car in alive:
            sid = car.spawn_id
            if sid in new_ids and car._spawn_age <= 3:
                for other in alive:
                    if other is car:
                        continue
                    if other.vertical != car.vertical or other.direction != car.direction:
                        continue
                    if car.vertical:
                        lane_gap = abs(other.rect.centerx - car.rect.centerx)
                        gap = (car.rect.centery - other.rect.centery) * car.direction
                    else:
                        lane_gap = abs(other.rect.centery - car.rect.centery)
                        gap = (car.rect.centerx - other.rect.centerx) * car.direction
                    if lane_gap > 45:
                        continue
                    if 0 < gap < SPAWN_LANE_GAP_AHEAD_PX and other.current_speed > 1.5:
                        self.spawn_in_lane_ahead_count += 1
                        anomaly = CarAnomaly(
                            kind="spawn_in_lane_ahead",
                            sim_t=sim_t,
                            frame=frame,
                            summary=(
                                f"Spawn {sid} placed {gap:.0f}px ahead of mover {other.spawn_id}"
                            ),
                            details={
                                "spawn_id": sid,
                                "mover_id": other.spawn_id,
                                "gap_px": round(gap, 1),
                                "mover_speed": round(other.current_speed, 2),
                            },
                        )
                        self.anomalies.append(anomaly)
                        emitted.append(anomaly)
                        break

            if (
                intersection_zones
                and car.current_speed < 0.15
                and _partial_intersection_overlap(car, intersection_zones)
            ):
                seen_partial.add(sid)
                streak = self._partial_ix_streak.get(sid, 0) + 1
                self._partial_ix_streak[sid] = streak
                if streak >= PARTIAL_IX_STOP_FRAMES and sid not in self._emitted_partial_ix:
                    self._emitted_partial_ix.add(sid)
                    self.partial_ix_stop_count += 1
                    anomaly = CarAnomaly(
                        kind="partial_ix_stop",
                        sim_t=sim_t,
                        frame=frame,
                        summary=f"Car {sid} stopped {streak} frames at intersection edge",
                        details={
                            "car_id": sid,
                            "streak_frames": streak,
                            "pos": [car.rect.centerx, car.rect.centery],
                        },
                    )
                    self.anomalies.append(anomaly)
                    emitted.append(anomaly)
            else:
                self._partial_ix_streak[sid] = 0

        for sid in list(self._partial_ix_streak):
            if sid not in seen_partial:
                self._partial_ix_streak[sid] = 0

        return emitted

    def summary_dict(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for a in self.anomalies:
            by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        return {
            "anomaly_count": len(self.anomalies),
            "by_kind": by_kind,
            "overlap_frames": self.overlap_frames,
            "max_overlap_pairs": self.max_overlap_pairs,
            "pre_separation_overlap_frames": self.pre_separation_overlap_frames,
            "spawn_in_lane_ahead_count": self.spawn_in_lane_ahead_count,
            "partial_ix_stop_count": self.partial_ix_stop_count,
        }


def _overlap_pairs(alive: list) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for i in range(len(alive)):
        for j in range(i + 1, len(alive)):
            if rects_overlap(alive[i]._collision_shell, alive[j]._collision_shell):
                a = alive[i].spawn_id
                b = alive[j].spawn_id
                pairs.append((min(a, b), max(a, b)))
    return pairs


def _car_in_any_zone(car, zones: list[Rect]) -> bool:
    for zone in zones:
        if rects_overlap(zone, car.rect):
            return True
    return False


def _partial_intersection_overlap(car, zones: list[Rect]) -> bool:
    for zone in zones:
        if not collide(zone, car.rect):
            continue
        fully = (
            car.rect.left >= zone.left
            and car.rect.right <= zone.right
            and car.rect.top >= zone.top
            and car.rect.bottom <= zone.bottom
        )
        if not fully:
            return True
    return False
