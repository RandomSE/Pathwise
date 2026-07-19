"""Old modifier: half movement speed; doubled timers and time gains.

Multiplies with rainy roads route scaling (1.5x rain * 2x old = 3x base) and with
Time pressure crossing bonuses. Combined with Rainy roads, a sprint trip is
fatal after a short on-map slip, then the normal trip / round-over screens.
"""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

MOVE_SPEED_MULT = 0.5
TIME_LIMIT_MULT = 2.0
TIME_BONUS_MULT = 2.0
FATAL_TRIP_SLIP_SECONDS = 2.0

_ctx: ModifierContext | None = None
_active = False
_rain_combo = False
_fatal_phase = "idle"
_fatal_phase_until = 0.0


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active, _rain_combo, _fatal_phase, _fatal_phase_until
    _ctx = ctx
    _active = ctx.has("old")
    _rain_combo = _active and ctx.has("rainy_roads")
    _fatal_phase = "idle"
    _fatal_phase_until = 0.0


def is_active() -> bool:
    return _active


def player_speed_mult() -> float:
    return MOVE_SPEED_MULT if _active else 1.0


def scaled_time_limit(base_seconds: float) -> float:
    if not _active:
        return base_seconds
    return float(base_seconds) * TIME_LIMIT_MULT


def time_bonus_mult() -> float:
    """Multiplier for Time pressure (and similar) granted seconds."""
    return TIME_BONUS_MULT if _active else 1.0


def trip_is_fatal() -> bool:
    """True when Old + Rainy roads: slipping while sprinting ends the round."""
    return _rain_combo


def fatal_slip_duration() -> float:
    return FATAL_TRIP_SLIP_SECONDS


def begin_fatal_trip(elapsed: float) -> None:
    """Start slip-then-fail sequence (idempotent once started)."""
    global _fatal_phase, _fatal_phase_until
    if not _rain_combo or _fatal_phase != "idle":
        return
    _fatal_phase = "slipping"
    _fatal_phase_until = float(elapsed) + FATAL_TRIP_SLIP_SECONDS


def is_fatal_trip_active() -> bool:
    return _fatal_phase == "slipping"


def should_blackout() -> bool:
    """Deprecated: fatal trips no longer use a black screen."""
    return False


def update_fatal_trip(elapsed: float) -> str:
    """Advance fatal trip phases. Returns idle|continue|fail."""
    global _fatal_phase, _fatal_phase_until
    if _fatal_phase == "idle":
        return "idle"
    if _fatal_phase == "done":
        return "fail"
    if _fatal_phase == "slipping" and float(elapsed) >= _fatal_phase_until:
        _fatal_phase = "done"
        return "fail"
    return "continue"


def hud_line() -> str | None:
    if not _active:
        return None
    if _rain_combo:
        return "Old: 0.5x move · 2x time · rain trip is fatal"
    return "Old: 0.5x move · 2x time"
