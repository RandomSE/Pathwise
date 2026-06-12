"""Detect car–car and intersection anomalies while spectating a synthetic round."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pathwise.geom import Rect, rects_overlap


NEAR_TURNER_DIST = 72
FROZEN_SPEED_THRESH = 0.15
TURN_STUCK_SPEED_THRESH = 0.1
OVERLAP_REPORT_MIN_PAIRS = 1
FROZEN_NEAR_TURNER_FRAMES = 120
TURN_STUCK_FRAMES = 120
TURN_ARC_OVERLAP_FRAMES = 4
TURN_ARC_OVERLAP_COOLDOWN = 24
GRIDLOCK_MIN_CARS = 3
GRIDLOCK_SPEED_THRESH = 0.3


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
    """Stateful observer: emits anomalies when issues persist across frames."""

    def __init__(self) -> None:
        self.anomalies: list[CarAnomaly] = []
        self._overlap_cooldown = 0
        self._frozen_near_turner: dict[int, int] = {}
        self._turn_stuck: dict[int, int] = {}
        self._gridlock_streak = 0
        self._emitted_frozen: set[int] = set()
        self._emitted_turn_stuck: set[int] = set()
        self._emitted_gridlock = False
        self.max_overlap_pairs = 0
        self.overlap_frames = 0
        self.pre_separation_overlap_frames = 0
        self.turn_arc_overlap_frames = 0
        self.turn_arc_pre_separation_frames = 0
        self.max_turn_arc_overlap_pairs = 0
        self._turn_arc_pair_streak: dict[tuple[int, int], int] = {}
        self._turn_arc_post_pair_streak: dict[tuple[int, int], int] = {}
        self._turn_arc_overlap_cooldown = 0
        self._turn_arc_post_overlap_cooldown = 0

    def observe_pre_separation(
        self,
        *,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
    ) -> list[CarAnomaly]:
        """Sample overlaps after car moves, before global shell separation."""
        emitted: list[CarAnomaly] = []
        alive = [c for c in cars if c.alive()]

        all_pairs = _overlap_pairs(alive)
        if all_pairs:
            self.pre_separation_overlap_frames += 1

        arc_pairs = _turn_arc_overlap_pairs(alive)
        if arc_pairs:
            self.turn_arc_pre_separation_frames += 1
            self.max_turn_arc_overlap_pairs = max(
                self.max_turn_arc_overlap_pairs, len(arc_pairs)
            )
            active_pairs = set(arc_pairs)
            for pair in list(self._turn_arc_pair_streak):
                if pair not in active_pairs:
                    del self._turn_arc_pair_streak[pair]
            for pair in arc_pairs:
                self._turn_arc_pair_streak[pair] = (
                    self._turn_arc_pair_streak.get(pair, 0) + 1
                )
            if self._turn_arc_overlap_cooldown <= 0:
                for pair, streak in sorted(self._turn_arc_pair_streak.items()):
                    if streak >= TURN_ARC_OVERLAP_FRAMES:
                        anomaly = CarAnomaly(
                            kind="turn_arc_overlap",
                            sim_t=sim_t,
                            frame=frame,
                            summary=(
                                f"Arc turners {pair[0]}/{pair[1]} overlapped "
                                f"{streak} pre-separation frames"
                            ),
                            details={
                                "pairs": arc_pairs,
                                "pair_count": len(arc_pairs),
                                "streak_frames": streak,
                                "phase": "pre_separation",
                            },
                        )
                        self.anomalies.append(anomaly)
                        emitted.append(anomaly)
                        self._turn_arc_overlap_cooldown = TURN_ARC_OVERLAP_COOLDOWN
                        break
        else:
            self._turn_arc_pair_streak.clear()

        if self._turn_arc_overlap_cooldown > 0:
            self._turn_arc_overlap_cooldown -= 1

        return emitted

    def observe(
        self,
        *,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
    ) -> list[CarAnomaly]:
        emitted: list[CarAnomaly] = []
        alive = [c for c in cars if c.alive()]

        arc_pairs = _turn_arc_overlap_pairs(alive)
        if arc_pairs:
            self.turn_arc_overlap_frames += 1
            self.max_turn_arc_overlap_pairs = max(
                self.max_turn_arc_overlap_pairs, len(arc_pairs)
            )
            active_pairs = set(arc_pairs)
            for pair in list(self._turn_arc_post_pair_streak):
                if pair not in active_pairs:
                    del self._turn_arc_post_pair_streak[pair]
            for pair in arc_pairs:
                self._turn_arc_post_pair_streak[pair] = (
                    self._turn_arc_post_pair_streak.get(pair, 0) + 1
                )
            if self._turn_arc_post_overlap_cooldown <= 0:
                for pair, streak in sorted(self._turn_arc_post_pair_streak.items()):
                    if streak >= TURN_ARC_OVERLAP_FRAMES:
                        anomaly = CarAnomaly(
                            kind="turn_arc_overlap",
                            sim_t=sim_t,
                            frame=frame,
                            summary=(
                                f"Arc turners {pair[0]}/{pair[1]} overlapped "
                                f"{streak} post-separation frames"
                            ),
                            details={
                                "pairs": arc_pairs,
                                "pair_count": len(arc_pairs),
                                "streak_frames": streak,
                                "phase": "post_separation",
                            },
                        )
                        self.anomalies.append(anomaly)
                        emitted.append(anomaly)
                        self._turn_arc_post_overlap_cooldown = TURN_ARC_OVERLAP_COOLDOWN
                        break
        else:
            self._turn_arc_post_pair_streak.clear()
        if self._turn_arc_post_overlap_cooldown > 0:
            self._turn_arc_post_overlap_cooldown -= 1

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

        turners = [
            c
            for c in alive
            if c.turn_signal != 0
            or c._turn_phase in ("to_hub", "turning", "settling")
        ]
        seen_frozen: set[int] = set()
        for car in alive:
            if car in turners:
                continue
            if car.current_speed >= FROZEN_SPEED_THRESH:
                self._frozen_near_turner[car.spawn_id] = 0
                continue
            if car._turn_phase != "none" or car.turn_signal != 0:
                continue
            near = _near_any_turner(car, turners)
            if not near:
                self._frozen_near_turner[car.spawn_id] = 0
                continue
            sid = car.spawn_id
            seen_frozen.add(sid)
            streak = self._frozen_near_turner.get(sid, 0) + 1
            self._frozen_near_turner[sid] = streak
            if (
                streak >= FROZEN_NEAR_TURNER_FRAMES
                and sid not in self._emitted_frozen
            ):
                self._emitted_frozen.add(sid)
                anomaly = CarAnomaly(
                    kind="frozen_near_turner",
                    sim_t=sim_t,
                    frame=frame,
                    summary=(
                        f"Car {sid} frozen {streak} frames near turner "
                        f"at ({car.rect.centerx},{car.rect.centery})"
                    ),
                    details={
                        "car_id": sid,
                        "streak_frames": streak,
                        "pos": [car.rect.centerx, car.rect.centery],
                    },
                )
                self.anomalies.append(anomaly)
                emitted.append(anomaly)

        for sid in list(self._frozen_near_turner):
            if sid not in seen_frozen:
                self._frozen_near_turner[sid] = 0

        seen_turn_stuck: set[int] = set()
        for car in turners:
            if car._turn_phase == "to_hub" or car._turn_hold_frames > 0:
                self._turn_stuck[car.spawn_id] = 0
                continue
            if car.current_speed >= TURN_STUCK_SPEED_THRESH:
                self._turn_stuck[car.spawn_id] = 0
                continue
            sid = car.spawn_id
            seen_turn_stuck.add(sid)
            streak = self._turn_stuck.get(sid, 0) + 1
            self._turn_stuck[sid] = streak
            if streak >= TURN_STUCK_FRAMES and sid not in self._emitted_turn_stuck:
                self._emitted_turn_stuck.add(sid)
                anomaly = CarAnomaly(
                    kind="turn_stuck",
                    sim_t=sim_t,
                    frame=frame,
                    summary=(
                        f"Turner {sid} stuck {streak} frames "
                        f"phase={car._turn_phase} ts={car.turn_signal}"
                    ),
                    details={
                        "car_id": sid,
                        "streak_frames": streak,
                        "turn_phase": car._turn_phase,
                        "turn_signal": car.turn_signal,
                        "pos": [car.rect.centerx, car.rect.centery],
                    },
                )
                self.anomalies.append(anomaly)
                emitted.append(anomaly)

        for sid in list(self._turn_stuck):
            if sid not in seen_turn_stuck:
                self._turn_stuck[sid] = 0

        if intersection_zones:
            slow_in_ix = 0
            for car in alive:
                if car.current_speed >= GRIDLOCK_SPEED_THRESH:
                    continue
                if _car_in_any_zone(car, intersection_zones):
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
            "turn_arc_overlap_frames": self.turn_arc_overlap_frames,
            "turn_arc_pre_separation_frames": self.turn_arc_pre_separation_frames,
            "max_turn_arc_overlap_pairs": self.max_turn_arc_overlap_pairs,
        }


def _turn_arc_overlap_pairs(alive: list) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    arc = [c for c in alive if c._turn_phase in ("turning", "settling")]
    for i in range(len(arc)):
        for j in range(i + 1, len(arc)):
            if rects_overlap(arc[i]._collision_shell, arc[j]._collision_shell):
                a = arc[i].spawn_id
                b = arc[j].spawn_id
                pairs.append((min(a, b), max(a, b)))
    return pairs


def _overlap_pairs(alive: list) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for i in range(len(alive)):
        for j in range(i + 1, len(alive)):
            if rects_overlap(alive[i]._collision_shell, alive[j]._collision_shell):
                a = alive[i].spawn_id
                b = alive[j].spawn_id
                pairs.append((min(a, b), max(a, b)))
    return pairs


def _near_any_turner(car, turners: list) -> bool:
    cx, cy = car.rect.centerx, car.rect.centery
    for other in turners:
        if (
            abs(cx - other.rect.centerx) < NEAR_TURNER_DIST
            and abs(cy - other.rect.centery) < NEAR_TURNER_DIST
        ):
            return True
    return False


def _car_in_any_zone(car, zones: list[Rect]) -> bool:
    for zone in zones:
        if rects_overlap(zone, car.rect):
            return True
    return False
