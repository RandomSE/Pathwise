"""Lag modifier: hard-cap presentation at 10 FPS without shrinking wall-time budgets.

Frame-based movement is rescaled by wall_dt relative to a 60Hz baseline so that
60 wall-seconds of round timer still allow the same travel / traffic progress as
an uncapped 60Hz run. Timers already use wall_dt (via sim_elapsed), so they stay
true wall-time under Lag.
"""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

TARGET_FPS = 10.0
BASELINE_FPS = 60.0
_MAX_WALL_DT_S = 0.25

_ctx: ModifierContext | None = None
_active = False
_physics_scale = 1.0


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active, _physics_scale
    _ctx = ctx
    _active = ctx.has("lag")
    _physics_scale = 1.0


def is_active() -> bool:
    return _active


def target_fps() -> float:
    return TARGET_FPS if _active else BASELINE_FPS


def update_period_s() -> float:
    return 1.0 / target_fps()


def begin_frame(wall_dt: float) -> float:
    """Cache and return this frame's physics scale (1.0 when Lag is off)."""
    global _physics_scale
    if not _active:
        _physics_scale = 1.0
        return _physics_scale
    dt = max(0.0, min(float(wall_dt), _MAX_WALL_DT_S))
    _physics_scale = dt * BASELINE_FPS
    return _physics_scale


def physics_scale() -> float:
    """Per-frame multiply for frame-based movement / schedule steps."""
    return float(_physics_scale)


def hud_line() -> str | None:
    if not _active:
        return None
    return f"Lag: {int(TARGET_FPS)} FPS max"
