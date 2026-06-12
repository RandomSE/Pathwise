"""Headless replay checks for turn-path overlap and motion continuity."""

from __future__ import annotations

import math
from typing import Any

from pathwise.geom import Rect, rects_overlap


ARC_TURN_PHASES = frozenset({"turning", "settling"})
# Replay is ~12 Hz; allow ~7 px/sim-frame at 60 fps between consecutive samples.
TURN_JUMP_PX_PER_SIM_FRAME = 7.0
SIM_FPS = 60.0
TURN_JUMP_EXTRA_PAD_PX = 12.0
MAX_CONTINUOUS_REPLAY_GAP_S = 0.2


def replay_car_rect(car: dict[str, Any]) -> Rect:
    return Rect(int(car["x"]), int(car["y"]), int(car["w"]), int(car["h"]))


def turn_arc_pairs_in_replay_frame(cars: list[dict[str, Any]]) -> list[tuple[int, int]]:
    arc = [c for c in cars if c.get("tp") in ARC_TURN_PHASES]
    pairs: list[tuple[int, int]] = []
    for i in range(len(arc)):
        for j in range(i + 1, len(arc)):
            if rects_overlap(replay_car_rect(arc[i]), replay_car_rect(arc[j])):
                a = int(arc[i]["id"])
                b = int(arc[j]["id"])
                pairs.append((min(a, b), max(a, b)))
    return pairs


def audit_replay_turn_pair_overlaps(frames: list[dict[str, Any]]) -> dict[str, int]:
    max_streak = 0
    streak = 0
    overlap_frames = 0
    max_pairs = 0
    for frame in frames:
        pairs = turn_arc_pairs_in_replay_frame(frame.get("cars", []))
        if pairs:
            overlap_frames += 1
            streak += 1
            max_streak = max(max_streak, streak)
            max_pairs = max(max_pairs, len(pairs))
        else:
            streak = 0
    return {
        "overlap_frames": overlap_frames,
        "max_streak": max_streak,
        "max_pairs": max_pairs,
    }


def audit_turn_position_jumps(
    frames: list[dict[str, Any]],
) -> dict[str, float]:
    """Flag arc motion jumps larger than turn speed allows between replay samples."""
    last: dict[int, tuple[float, float, float]] = {}
    max_overshoot = 0.0
    for frame in frames:
        t = float(frame["t"])
        for car in frame.get("cars", []):
            if car.get("tp") not in ARC_TURN_PHASES:
                continue
            cid = int(car["id"])
            cx = float(car.get("cx", car["x"] + car["w"] / 2))
            cy = float(car.get("cy", car["y"] + car["h"] / 2))
            if cid in last:
                lx, ly, lt = last[cid]
                dt = t - lt
                if 0.0 < dt <= MAX_CONTINUOUS_REPLAY_GAP_S:
                    jump = math.hypot(cx - lx, cy - ly)
                    allowed = (
                        dt * SIM_FPS * TURN_JUMP_PX_PER_SIM_FRAME
                        + TURN_JUMP_EXTRA_PAD_PX
                    )
                    if jump > allowed:
                        max_overshoot = max(max_overshoot, jump - allowed)
            last[cid] = (cx, cy, t)
    return {"max_overshoot_px": max_overshoot}
