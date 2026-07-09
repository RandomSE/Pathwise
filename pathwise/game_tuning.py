"""Central simulation tuning — one dataclass per difficulty preset."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace

from analytics.traffic_lights import cycle_durations
from map_generation.difficulty import DifficultyProfile
from map_generation.traffic_schedule import INTERSECTION_SPAWN_PAD
from pathwise import commonUtils

_utils = commonUtils
_CAR_W, _CAR_H = _utils.CAR_WIDTH, _utils.CAR_HEIGHT


@dataclass(frozen=True)
class GameTuning:
    """All gameplay tuning constants (lights, cars, spawn, perf)."""

    WIDTH: int = _utils.WIDTH
    HEIGHT: int = _utils.HEIGHT
    ROAD_Y: int = _utils.ROAD_Y
    ROAD_HEIGHT: int = _utils.ROAD_HEIGHT
    CAR_WIDTH: int = _CAR_W
    CAR_HEIGHT: int = _CAR_H
    PEDESTRIAN_SIZE: int = _utils.PEDESTRIAN_SIZE
    PEDESTRIAN_SPEED: float = _utils.PEDESTRIAN_SPEED
    SPRINT_SPEED_MULT: float = 2.0
    CAR_SPEED: float = _utils.CAR_SPEED
    SIM_FPS: float = 60.0
    ROUND_TIME_LIMIT: int = 30
    HUD_TEXT_COLOR: tuple[int, int, int] = (20, 20, 20)
    RISK_COOLDOWN_SECONDS: float = 1.5

    LIGHT_CYCLE_SECONDS: float = 20.0
    YELLOW_COMMIT_DISTANCE: int = 85
    INTERSECTION_CLEAR_BUFFER_S: float = 0.6
    STOP_LINE_GAP: int = 6
    RED_SIGNAL_BRAKE_DIST: int = 96
    RED_SIGNAL_CREEP_DIST: int = 28
    YELLOW_SIGNAL_BRAKE_DIST: int = 72

    CAR_SPAWN_CLEARANCE: int = 20
    CROSSWALK_THICKNESS: int = 22
    INTERSECTION_GAP_MIN: int = 6
    NEAR_MISS_DISTANCE: int = 56
    TOO_CLOSE_DISTANCE: int = 82
    PLAYER_AVOIDANCE_CHANCE: float = 0.8
    CAR_FOLLOW_LANE_GAP: int = 40
    CAR_BLOCK_LANE_GAP: int = 38
    CAR_CREEP_SPEED: float = 1.1
    CAR_FOLLOW_SEP: int = 5
    PERP_OVERLAP_SHRINK: int = 2
    STUCK_BEHIND_FRAMES: int = 240
    INTERSECTION_STUCK_CREEP_FRAMES: int = 45
    INTERSECTION_GRIDLOCK_FRAMES: int = 180
    INTERSECTION_APPROACH_SPAWN_PAD: int = INTERSECTION_SPAWN_PAD
    MAX_DRAW_RECORD_CARS: int = 28
    SIM_UPDATE_VIEW_PAD: int = 280
    OFFSCREEN_UPDATE_STRIDE: int = 3
    OFFSCREEN_FAR_STRIDE: int = 4
    CAR_SPAWN_RAMP_FRAMES: int = 90
    ROAD_EXIT_PAD: int = 28
    PLAYER_SPAWN_PAD: int = 280
    SPAWN_MIN_ROAD_FRAC: float = 0.42
    SPAWN_MAX_BLOCK_FRAC: float = 0.06
    MAX_SPAWN_DEFER_FRAMES: int = 240
    SPAWN_RETRY_SLOTS: int = 48
    EDGE_SPAWN_QUEUE_CAP: int = 2
    RESPAWN_PENDING_CAP: int = 48
    RESPAWN_EVENT_ID_BASE: int = 900_000
    MAX_RESPAWNS_PER_FRAME: int = 4
    RESPAWN_DELAY_FRAMES: int = 36
    RESPAWN_RETRY_FRAMES: int = 20
    RESPAWN_POSE_TRIES: int = 2

    SHELL_PENETRATION_MAX_NUDGE: int = 10
    SHELL_PENETRATION_PASSES: int = 4
    INTERSECTION_SHELL_PAD: int = 32
    ENABLE_CAR_CAR_COLLISION: bool = False
    ENABLE_CAR_CAR_SOFT_AVOIDANCE: bool = True
    CAR_SOFT_FOLLOW_RANGE: int = 150
    CAR_SOFT_STOP_GAP: int = 14
    CAP_ALL_CARS_ITERATIONS: int = 4
    SHELL_SEP_EVERY_N_FRAMES: int = 2
    SHELL_SEP_PEER_PAD: int = 72
    SHELL_SEP_FLEET_THRESHOLD: int = 70

    OFF_ROAD_REMOVE_FRAMES: int = 72
    NETWORK_ROAD_PAD: int = 64
    NETWORK_IX_PAD: int = 32
    STREET_CORRIDOR_PAD: int = 40
    ROAD_SURFACE_PAD: int = 6
    MIN_ON_ROAD_FRAC: float = 0.10
    CAR_EXIT_DESPAWN_MARGIN: int = 36
    EXIT_CORRIDOR_LATERAL: int = 72

    CAR_NEARBY_PAD: int = 96
    SPATIAL_CELL: int = 128
    LANE_BUCKET_SIZE: int = 52
    SURFACE_CHECK_INTERVAL: int = 4
    IX_QUERY_PAD: int = 100
    PLAYER_CAR_QUERY_PAD: int = 220
    FRAME_RECORD_VIEW_PAD: int = 120
    REPLAY_RECORD_EXTRA_PAD: int = 400
    REPLAY_MAX_CARS: int = 56
    HONK_CHECK_INTERVAL: int = 4
    SPAWN_RETRY_BUDGET_PER_FRAME: int = 2
    TRAFFIC_DRAW_TIMER_BAR: bool = False
    HONK_DURATION: float = 0.55
    HONK_COOLDOWN: float = 1.1
    HONK_CLOSE_PAD: int = 72

    def light_durations(self) -> tuple[float, float, float]:
        return cycle_durations(self.LIGHT_CYCLE_SECONDS)

    @property
    def LIGHT_GREEN_DURATION(self) -> float:
        return self.light_durations()[0]

    @property
    def LIGHT_YELLOW_DURATION(self) -> float:
        return self.light_durations()[1]

    @property
    def LIGHT_RED_DURATION(self) -> float:
        return self.light_durations()[2]

    @classmethod
    def default(cls) -> GameTuning:
        return cls()

    @classmethod
    def for_preset(cls, preset_id: str, profile: DifficultyProfile | None = None) -> GameTuning:
        preset = preset_id.lower()
        tuning = cls.default()
        if preset == "easy":
            tuning = replace(tuning, OFFSCREEN_FAR_STRIDE=3, SHELL_SEP_EVERY_N_FRAMES=4)
        elif preset == "hard":
            tuning = replace(
                tuning,
                OFFSCREEN_FAR_STRIDE=6,
                SHELL_SEP_EVERY_N_FRAMES=4,
                SHELL_SEP_FLEET_THRESHOLD=55,
                CAP_ALL_CARS_ITERATIONS=2,
                SIM_UPDATE_VIEW_PAD=240,
            )
        if profile is not None:
            stride = max(
                2,
                min(5, int(round(tuning.OFFSCREEN_UPDATE_STRIDE * profile.stride_scale / 1.4))),
            )
            tuning = replace(tuning, OFFSCREEN_UPDATE_STRIDE=stride)
        return tuning

    def export_scalars(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for f in fields(self):
            out[f.name] = getattr(self, f.name)
        lg, ly, lr = self.light_durations()
        out["LIGHT_GREEN_DURATION"] = lg
        out["LIGHT_YELLOW_DURATION"] = ly
        out["LIGHT_RED_DURATION"] = lr
        out["ENABLE_CAR_DIAGNOSTICS"] = os.environ.get(
            "PATHWISE_CAR_DIAGNOSTICS", ""
        ).lower() in ("1", "true", "yes")
        return out


DEFAULT_TUNING = GameTuning.default()
_active: GameTuning = DEFAULT_TUNING


def active_tuning() -> GameTuning:
    return _active


def install_tuning(tuning: GameTuning) -> GameTuning:
    global _active
    _active = tuning
    import pathwise.sim_constants as sc

    for name, value in tuning.export_scalars().items():
        setattr(sc, name, value)
    return tuning


def install_for_round(preset_id: str, profile: DifficultyProfile) -> GameTuning:
    return install_tuning(GameTuning.for_preset(preset_id, profile))
