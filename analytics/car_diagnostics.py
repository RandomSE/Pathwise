"""Detect and log abnormal car motion (backward travel, long stalls) for debugging."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_DIAG_PATH = "car_diagnostics.jsonl"
STALL_SECONDS = 10.0
STALL_MOVE_EPS = 1.5
BACKWARD_ALONG_EPS = 2.5
BACKWARD_COOLDOWN_S = 3.0


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


@dataclass
class CarDiagnosticsLogger:
    path: str = DEFAULT_DIAG_PATH
    stall_seconds: float = STALL_SECONDS
    _tracks: dict[int, _CarTrack] = field(default_factory=dict)
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
        phase = getattr(car, "_turn_phase", "none")
        backward = phase not in ("turning", "settling") and is_backward_along_travel(
            along
        )

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
        phase = getattr(car, "_turn_phase", "none")
        if phase in ("to_hub", "turning", "settling") and getattr(car, "_turn_exit", None):
            return (
                bool(getattr(car, "_turn_entry_vertical", car.vertical)),
                int(getattr(car, "_turn_entry_direction", car.direction)),
            )
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
        turn_exit = getattr(car, "_turn_exit", None)
        turn_hub = getattr(car, "_turn_hub", None)
        hub_off = None
        if turn_hub is not None and hasattr(car, "_hub_travel_offset"):
            try:
                hub_off = round(float(car._hub_travel_offset()), 2)
            except Exception:
                hub_off = None
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
            "turn_phase": getattr(car, "_turn_phase", "none"),
            "turn_signal": int(getattr(car, "turn_signal", 0)),
            "turn_exit": (
                {"road_index": turn_exit[0], "direction": turn_exit[1], "vertical": turn_exit[2]}
                if turn_exit
                else None
            ),
            "turn_hub": list(turn_hub) if turn_hub else None,
            "hub_travel_offset": hub_off,
            "turn_arc_travel": round(float(getattr(car, "_turn_arc_travel", 0.0)), 2),
            "turn_arc_len": round(float(getattr(car, "_turn_arc_len", 0.0)), 2),
            "turn_blocked_frames": int(getattr(car, "_turn_blocked_frames", 0)),
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
                    "turn_phase": getattr(other, "_turn_phase", "none"),
                    "turn_signal": int(getattr(other, "turn_signal", 0)),
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
        self._append(payload)

    def _append(self, payload: dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


car_diagnostics = CarDiagnosticsLogger()
