"""Interpolate replay keyframes for smooth dashboard playback."""

from __future__ import annotations

import math


def _lerp(a: float, b: float, alpha: float) -> float:
    return a + (b - a) * alpha


def _lerp_angle(a: float, b: float, alpha: float) -> float:
    delta = (b - a + 180.0) % 360.0 - 180.0
    return a + delta * alpha


def frame_pair_at_time(frames: list[dict], t: float) -> tuple[int, int, float]:
    """Return left index, right index, and alpha in [0, 1] for sim time t."""
    if not frames:
        return 0, 0, 0.0
    if t <= frames[0]["t"]:
        return 0, 0, 0.0
    if t >= frames[-1]["t"]:
        last = len(frames) - 1
        return last, last, 0.0
    lo = 0
    hi = len(frames) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if frames[mid]["t"] <= t:
            lo = mid
        else:
            hi = mid
    left = frames[lo]
    right = frames[hi]
    span = right["t"] - left["t"]
    alpha = 0.0 if span <= 1e-9 else (t - left["t"]) / span
    return lo, hi, max(0.0, min(1.0, alpha))


def interpolate_car(left: dict, right: dict, alpha: float) -> dict:
    out = dict(left)
    for key in ("x", "y", "cx", "cy"):
        if key in left and key in right:
            out[key] = round(_lerp(float(left[key]), float(right[key]), alpha))
    if "ang" in left and "ang" in right:
        out["ang"] = round(_lerp_angle(float(left["ang"]), float(right["ang"]), alpha), 1)
    if "sp" in left and "sp" in right:
        out["sp"] = round(_lerp(float(left["sp"]), float(right["sp"]), alpha), 2)
    return out


def lerp_replay_frame(left: dict, right: dict, alpha: float, t: float | None = None) -> dict:
    """Blend two stored replay frames for smooth playback."""
    if alpha <= 0.0:
        return dict(left)
    if alpha >= 1.0:
        return dict(right)
    sim_t = t if t is not None else _lerp(left["t"], right["t"], alpha)
    lp = left.get("player") or {}
    rp = right.get("player") or {}
    player = {
        "x": round(_lerp(lp.get("x", 0), rp.get("x", 0), alpha)),
        "y": round(_lerp(lp.get("y", 0), rp.get("y", 0), alpha)),
        "s": lp.get("s", rp.get("s", 28)),
    }
    left_cars = {c["id"]: c for c in left.get("cars", [])}
    right_cars = {c["id"]: c for c in right.get("cars", [])}
    cars: list[dict] = []
    for cid in sorted(set(left_cars) | set(right_cars)):
        lc = left_cars.get(cid)
        rc = right_cars.get(cid)
        if lc and rc:
            cars.append(interpolate_car(lc, rc, alpha))
        elif lc and alpha < 0.5:
            cars.append(dict(lc))
        elif rc and alpha >= 0.5:
            cars.append(dict(rc))
    out = {
        "id": left.get("id", "interp"),
        "seq": left.get("seq", 0),
        "t": round(sim_t, 3),
        "player": player,
        "cars": cars,
        "lights": left.get("lights", right.get("lights", [])),
        "interpolated": True,
    }
    if alpha >= 0.5 and right.get("decision"):
        out["decision"] = dict(right["decision"])
        out["is_decision"] = bool(right.get("is_decision"))
    elif left.get("decision") and alpha < 0.5:
        out["decision"] = dict(left["decision"])
        out["is_decision"] = bool(left.get("is_decision"))
    return out


def frame_at_time(frames: list[dict], t: float) -> dict:
    lo, hi, alpha = frame_pair_at_time(frames, t)
    if lo == hi:
        return dict(frames[lo])
    return lerp_replay_frame(frames[lo], frames[hi], alpha, t=t)
