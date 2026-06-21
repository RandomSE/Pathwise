"""Detect and log abnormal car motion (backward travel, long stalls) for debugging."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_DIAG_PATH = "car_diagnostics.jsonl"
STALL_SECONDS = 10.0
STALL_MOVE_EPS = 1.5
BACKWARD_ALONG_EPS = 2.5
BACKWARD_COOLDOWN_S = 3.0
SHELL_COLLISION_COOLDOWN_S = 1.0
CROSS_STALL_COOLDOWN_S = 2.0
CROSS_STALL_DIST_PX = 140.0
CROSS_STALL_SPEED = 0.2
PROXIMITY_THRESH_PX = 16
PROXIMITY_STREAK_FRAMES = 30
PROXIMITY_STREAK_COOLDOWN_S = 3.0


def displacement_along_travel(
    dx: float, dy: float, vertical: bool, direction: int
) -> float:
    """Signed movement along the car's travel axis (+ = forward)."""
    direction = 1 if direction >= 0 else -1
    if vertical:
        return dy * direction
    return dx * direction


def is_backward_along_travel(along: float, threshold: float = BACKWARD_ALONG_EPS) -> bool:
    return along <= -threshold


def travel_label(vertical: bool, direction: int) -> str:
    direction = 1 if direction >= 0 else -1
    if vertical:
        return "south" if direction > 0 else "north"
    return "east" if direction > 0 else "west"


@dataclass
class _CarTrack:
    last_center: tuple[float, float]
    stall_started_at: float | None = None
    last_backward_log_at: float = -1e9
    stalled_logged: bool = False
    shell_collision_logged_at: float = -1e9
    cross_stall_logged_at: float = -1e9
    proximity_streak_logged_at: float = -1e9


@dataclass
class CarDiagnosticsLogger:
    path: str = DEFAULT_DIAG_PATH
    stall_seconds: float = STALL_SECONDS
    _tracks: dict[int, _CarTrack] = field(default_factory=dict)
    _proximity_pair_streak: dict[tuple[int, int], int] = field(default_factory=dict)
    _proximity_logged_pairs: set[tuple[int, int]] = field(default_factory=set)
    _round_index: int = 0
    _round_frame: int = 0
    _session_seed: int | None = None
    _map_seed: int | None = None
    _traffic_map_seed: int | None = None
    _session_started_at: str | None = None

    def begin_session(
        self,
        *,
        session_seed: int | None = None,
        seed_source: str | None = None,
        num_rounds: int | None = None,
    ) -> None:
        self._session_started_at = datetime.now(timezone.utc).isoformat()
        self._tracks.clear()
        self._proximity_pair_streak.clear()
        self._proximity_logged_pairs.clear()
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event": "session_start",
                        "utc": self._session_started_at,
                        "session_seed": session_seed,
                        "seed_source": seed_source,
                        "num_rounds": num_rounds,
                        "stall_threshold_s": self.stall_seconds,
                        "backward_threshold_px": BACKWARD_ALONG_EPS,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )

    def begin_round(
        self,
        round_index: int,
        *,
        session_seed: int | None = None,
        map_seed: int | None = None,
        traffic_map_seed: int | None = None,
    ) -> None:
        self._round_index = round_index
        self._round_frame = 0
        self._session_seed = session_seed
        self._map_seed = map_seed
        self._traffic_map_seed = traffic_map_seed
        if self._session_started_at is None:
            self._session_started_at = datetime.now(timezone.utc).isoformat()
        self._tracks.clear()
        self._proximity_pair_streak.clear()
        self._proximity_logged_pairs.clear()
        self._append(
            {
                "event": "round_start",
                "utc": datetime.now(timezone.utc).isoformat(),
                "round_index": round_index,
                "session_seed": session_seed,
                "map_seed": map_seed,
                "traffic_map_seed": traffic_map_seed,
            }
        )

    def end_round(self) -> None:
        self._append(
            {
                "event": "round_end",
                "utc": datetime.now(timezone.utc).isoformat(),
                "round_index": self._round_index,
            }
        )

    def observe(
        self,
        car,
        *,
        game_time: float,
        round_frame: int,
        intersection_zones,
        move_peers: list,
        player_center: tuple[float, float] | None = None,
    ) -> None:
        self._round_frame = round_frame
        if not getattr(car, "alive", lambda: True)():
            self._tracks.pop(getattr(car, "spawn_id", -1), None)
            return

        spawn_id = int(getattr(car, "spawn_id", 0))
        cx, cy = float(car.rect.centerx), float(car.rect.centery)
        track = self._tracks.get(spawn_id)
        if track is None:
            self._tracks[spawn_id] = _CarTrack(last_center=(cx, cy))
            return

        lx, ly = track.last_center
        dx, dy = cx - lx, cy - ly
        moved = (dx * dx + dy * dy) ** 0.5

        vertical, direction = self._effective_travel(car)
        along = displacement_along_travel(dx, dy, vertical, direction)
        from pathwise.geom import collide

        my_shell = getattr(car, "_collision_shell", car.rect)
        for other in move_peers:
            if other is car or not getattr(other, "alive", lambda: True)():
                continue
            if collide(my_shell, other._collision_shell):
                if game_time - track.shell_collision_logged_at >= SHELL_COLLISION_COOLDOWN_S:
                    track.shell_collision_logged_at = game_time
                    self._log_anomaly(
                        car,
                        kind="shell_collision",
                        game_time=game_time,
                        round_frame=round_frame,
                        dx=dx,
                        dy=dy,
                        along_travel=along,
                        moved=moved,
                        intersection_zones=intersection_zones,
                        move_peers=move_peers,
                        player_center=player_center,
                        extra={"other_spawn_id": getattr(other, "spawn_id", None)},
                    )
                break

        self._observe_proximity_streaks(
            car,
            my_shell=my_shell,
            game_time=game_time,
            round_frame=round_frame,
            dx=dx,
            dy=dy,
            along=along,
            moved=moved,
            intersection_zones=intersection_zones,
            move_peers=move_peers,
            player_center=player_center,
        )

        if float(getattr(car, "current_speed", 0.0)) < CROSS_STALL_SPEED:
            for other in move_peers:
                if other is car or not getattr(other, "alive", lambda: True)():
                    continue
                if float(getattr(other, "current_speed", 0.0)) >= CROSS_STALL_SPEED:
                    continue
                ox, oy = other.rect.centerx, other.rect.centery
                dist = ((ox - cx) ** 2 + (oy - cy) ** 2) ** 0.5
                if dist > CROSS_STALL_DIST_PX:
                    continue
                ov, od = self._effective_travel(other)
                if vertical == ov and direction == od:
                    continue
                if game_time - track.cross_stall_logged_at >= CROSS_STALL_COOLDOWN_S:
                    track.cross_stall_logged_at = game_time
                    self._log_anomaly(
                        car,
                        kind="cross_direction_stall",
                        game_time=game_time,
                        round_frame=round_frame,
                        dx=dx,
                        dy=dy,
                        along_travel=along,
                        moved=moved,
                        intersection_zones=intersection_zones,
                        move_peers=move_peers,
                        player_center=player_center,
                        extra={
                            "other_spawn_id": getattr(other, "spawn_id", None),
                            "other_travel": travel_label(ov, od),
                            "distance_px": round(dist, 1),
                        },
                    )
                break

        backward = is_backward_along_travel(along)

        if backward:
            if game_time - track.last_backward_log_at >= BACKWARD_COOLDOWN_S:
                track.last_backward_log_at = game_time
                self._log_anomaly(
                    car,
                    kind="backward",
                    game_time=game_time,
                    round_frame=round_frame,
                    dx=dx,
                    dy=dy,
                    along_travel=along,
                    moved=moved,
                    intersection_zones=intersection_zones,
                    move_peers=move_peers,
                    player_center=player_center,
                )
        else:
            track.last_backward_log_at = max(-1e9, track.last_backward_log_at)

        if moved <= STALL_MOVE_EPS and float(getattr(car, "current_speed", 0.0)) < 0.35:
            if track.stall_started_at is None:
                track.stall_started_at = game_time
            elif (
                not track.stalled_logged
                and game_time - track.stall_started_at >= self.stall_seconds
            ):
                track.stalled_logged = True
                self._log_anomaly(
                    car,
                    kind="stalled",
                    game_time=game_time,
                    round_frame=round_frame,
                    dx=dx,
                    dy=dy,
                    along_travel=along,
                    moved=moved,
                    stall_duration_s=round(game_time - track.stall_started_at, 2),
                    intersection_zones=intersection_zones,
                    move_peers=move_peers,
                    player_center=player_center,
                )
        else:
            track.stall_started_at = None
            track.stalled_logged = False

        track.last_center = (cx, cy)

    def _effective_travel(self, car) -> tuple[bool, int]:
        return bool(car.vertical), int(car.direction)

    def _car_snapshot(
        self,
        car,
        *,
        dx: float,
        dy: float,
        along_travel: float,
        moved: float,
        stall_duration_s: float | None = None,
    ) -> dict[str, Any]:
        vertical, direction = self._effective_travel(car)
        snap: dict[str, Any] = {
            "spawn_id": getattr(car, "spawn_id", None),
            "road_index": getattr(car, "road_index", None),
            "center": [int(car.rect.centerx), int(car.rect.centery)],
            "rect": [int(car.rect.x), int(car.rect.y), int(car.rect.width), int(car.rect.height)],
            "vertical": bool(car.vertical),
            "direction": int(car.direction),
            "travel": travel_label(vertical, direction),
            "current_speed": round(float(getattr(car, "current_speed", 0.0)), 3),
            "speed": round(float(getattr(car, "speed", 0.0)), 3),
            "base_speed": round(float(getattr(car, "base_speed", 0.0)), 3),
            "intersection_stuck_frames": int(getattr(car, "_intersection_stuck_frames", 0)),
            "stopped_frames": int(getattr(car, "_stopped_frames", 0)),
            "spawn_age_frames": int(getattr(car, "_spawn_age", 0)),
            "frame_delta": {
                "dx": round(dx, 2),
                "dy": round(dy, 2),
                "along_travel": round(along_travel, 2),
                "moved_px": round(moved, 2),
            },
        }
        if stall_duration_s is not None:
            snap["stall_duration_s"] = stall_duration_s
        return snap

    def _nearby_snapshot(self, car, peers, player_center) -> list[dict[str, Any]]:
        cx, cy = car.rect.centerx, car.rect.centery
        out: list[dict[str, Any]] = []
        for other in peers:
            if other is car or not getattr(other, "alive", lambda: True)():
                continue
            ox, oy = other.rect.centerx, other.rect.centery
            dist = ((ox - cx) ** 2 + (oy - cy) ** 2) ** 0.5
            if dist > 320:
                continue
            ov, od = self._effective_travel(other)
            out.append(
                {
                    "spawn_id": getattr(other, "spawn_id", None),
                    "center": [int(ox), int(oy)],
                    "distance_px": round(dist, 1),
                    "travel": travel_label(ov, od),
                    "vertical": bool(other.vertical),
                    "direction": int(other.direction),
                    "current_speed": round(float(getattr(other, "current_speed", 0.0)), 3),
                }
            )
        out.sort(key=lambda item: item["distance_px"])
        return out[:12]

    def _in_intersection(self, car, intersection_zones) -> bool:
        if not intersection_zones:
            return False
        if hasattr(car, "_rect_in_intersection"):
            return bool(car._rect_in_intersection(car.rect, intersection_zones))
        shell = getattr(car, "_collision_shell", car.rect)
        return any(z.colliderect(shell) for z in intersection_zones)

    @staticmethod
    def _shell_gap_px(a: Rect, b: Rect) -> float:
        dx = max(0, max(a.left - b.right, b.left - a.right))
        dy = max(0, max(a.top - b.bottom, b.top - a.bottom))
        return (dx * dx + dy * dy) ** 0.5

    def _shells_in_proximity(self, a: Rect, b: Rect) -> bool:
        from pathwise.geom import collide

        if collide(a, b):
            return False
        return self._shell_gap_px(a, b) <= PROXIMITY_THRESH_PX

    def _lawful_queue_pair(self, car, other) -> bool:
        if float(getattr(car, "current_speed", 0.0)) > 0.35:
            return False
        if float(getattr(other, "current_speed", 0.0)) > 0.35:
            return False
        if car.road_index is None or other.road_index is None:
            return False
        if car.road_index != other.road_index:
            return False
        if bool(car.vertical) != bool(other.vertical):
            return False
        if int(car.direction) != int(other.direction):
            return False
        direction = 1 if int(car.direction) >= 0 else -1
        if bool(car.vertical):
            ahead = (other.rect.centery - car.rect.centery) * direction
            lane_gap = abs(other.rect.centerx - car.rect.centerx)
        else:
            ahead = (other.rect.centerx - car.rect.centerx) * direction
            lane_gap = abs(other.rect.centery - car.rect.centery)
        if ahead <= 0 or lane_gap > 28:
            return False
        return True

    def _stopped_before_intersection(self, car, intersection_zones) -> bool:
        if float(getattr(car, "current_speed", 0.0)) > 0.2:
            return False
        if self._in_intersection(car, intersection_zones):
            return False
        return int(getattr(car, "_stopped_frames", 0)) >= 12

    def _lawful_turn_peer_proximity(self, car, other) -> bool:
        del car, other
        return False

    def _proximity_pair_lawful(
        self, car, other, intersection_zones, move_peers
    ) -> bool:
        if self._lawful_queue_pair(car, other):
            return True
        if self._lawful_queue_pair(other, car):
            return True
        if self._stopped_before_intersection(car, intersection_zones):
            return True
        if self._stopped_before_intersection(other, intersection_zones):
            return True
        if self._lawful_turn_peer_proximity(car, other):
            return True
        return False

    def _observe_proximity_streaks(
        self,
        car,
        *,
        my_shell,
        game_time: float,
        round_frame: int,
        dx: float,
        dy: float,
        along: float,
        moved: float,
        intersection_zones,
        move_peers: list,
        player_center: tuple[float, float] | None,
    ) -> None:
        spawn_id = int(getattr(car, "spawn_id", 0))
        active_pairs: set[tuple[int, int]] = set()
        for other in move_peers:
            if other is car or not getattr(other, "alive", lambda: True)():
                continue
            other_shell = getattr(other, "_collision_shell", other.rect)
            if not self._shells_in_proximity(my_shell, other_shell):
                continue
            if self._proximity_pair_lawful(car, other, intersection_zones, move_peers):
                continue
            oid = int(getattr(other, "spawn_id", 0))
            pair = (min(spawn_id, oid), max(spawn_id, oid))
            active_pairs.add(pair)
            streak = self._proximity_pair_streak.get(pair, 0) + 1
            self._proximity_pair_streak[pair] = streak
            if (
                streak >= PROXIMITY_STREAK_FRAMES
                and pair not in self._proximity_logged_pairs
            ):
                track = self._tracks.get(spawn_id)
                if (
                    track is not None
                    and game_time - track.proximity_streak_logged_at
                    >= PROXIMITY_STREAK_COOLDOWN_S
                ):
                    track.proximity_streak_logged_at = game_time
                    self._proximity_logged_pairs.add(pair)
                    self._log_anomaly(
                        car,
                        kind="proximity_streak",
                        game_time=game_time,
                        round_frame=round_frame,
                        dx=dx,
                        dy=dy,
                        along_travel=along,
                        moved=moved,
                        intersection_zones=intersection_zones,
                        move_peers=move_peers,
                        player_center=player_center,
                        extra={
                            "other_spawn_id": oid,
                            "pair": list(pair),
                            "streak_frames": streak,
                            "gap_px": round(
                                self._shell_gap_px(my_shell, other_shell), 1
                            ),
                            "proximity_thresh_px": PROXIMITY_THRESH_PX,
                        },
                    )
        for pair in list(self._proximity_pair_streak):
            if pair[0] != spawn_id and pair[1] != spawn_id:
                continue
            if pair not in active_pairs:
                self._proximity_pair_streak.pop(pair, None)

    def _log_anomaly(
        self,
        car,
        *,
        kind: str,
        game_time: float,
        round_frame: int,
        dx: float,
        dy: float,
        along_travel: float,
        moved: float,
        intersection_zones,
        move_peers: list,
        player_center: tuple[float, float] | None,
        stall_duration_s: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "event": kind,
            "utc": datetime.now(timezone.utc).isoformat(),
            "game_time_s": round(game_time, 3),
            "round_index": self._round_index,
            "round_frame": round_frame,
            "session_seed": self._session_seed,
            "map_seed": self._map_seed,
            "traffic_map_seed": self._traffic_map_seed,
            "in_intersection": self._in_intersection(car, intersection_zones),
            "player_center": list(player_center) if player_center else None,
            "car": self._car_snapshot(
                car,
                dx=dx,
                dy=dy,
                along_travel=along_travel,
                moved=moved,
                stall_duration_s=stall_duration_s,
            ),
            "nearby_cars": self._nearby_snapshot(car, move_peers, player_center),
        }
        if extra:
            payload.update(extra)
        self._append(payload)

    def _append(self, payload: dict[str, Any]) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


car_diagnostics = CarDiagnosticsLogger()
