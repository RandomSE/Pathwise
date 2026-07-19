"""Exposure modifier: cumulative on-road time budget.

Budget starts at 50% of the round timer (after rainy / time-pressure clock
setup). Spending happens only while the player body overlaps a road. With
Time pressure, each crossing bonus also grants 50% of that bonus to the
exposure limit. Exhausted budget ends the round like a timeout.
Incompatible with Highway (no asphalt budget on a full-width strip fight).
"""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

ROAD_BUDGET_FRAC = 0.5
TIME_BONUS_TO_EXPOSURE_FRAC = 0.5

_ctx: ModifierContext | None = None
_active = False
_limit_s = 0.0
_spent_s = 0.0
_last_elapsed: float | None = None


def install_for_round(
    ctx: ModifierContext, *, round_time_limit: float = 0.0
) -> None:
    global _ctx, _active, _limit_s, _spent_s, _last_elapsed
    _ctx = ctx
    _active = ctx.has("exposure")
    _spent_s = 0.0
    _last_elapsed = None
    if _active:
        _limit_s = max(0.0, float(round_time_limit) * ROAD_BUDGET_FRAC)
    else:
        _limit_s = 0.0


def is_active() -> bool:
    return _active


def limit_seconds() -> float:
    return float(_limit_s)


def spent_seconds() -> float:
    return float(_spent_s)


def remaining_seconds() -> float:
    if not _active:
        return 0.0
    return max(0.0, float(_limit_s) - float(_spent_s))


def grant_from_time_bonus(bonus_seconds: float) -> float:
    """Add TIME_BONUS_TO_EXPOSURE_FRAC of a Time pressure gain to the limit."""
    global _limit_s
    if not _active:
        return 0.0
    grant = max(0.0, float(bonus_seconds)) * TIME_BONUS_TO_EXPOSURE_FRAC
    if grant > 0:
        _limit_s += grant
    return grant


def tick(*, on_road: bool, elapsed: float) -> bool:
    """Accumulate on-road time. Returns True when the budget is exhausted."""
    global _spent_s, _last_elapsed
    if not _active:
        _last_elapsed = float(elapsed)
        return False
    if _last_elapsed is None:
        _last_elapsed = float(elapsed)
        return remaining_seconds() <= 0.0 and _limit_s <= 0.0
    dt = max(0.0, float(elapsed) - float(_last_elapsed))
    _last_elapsed = float(elapsed)
    if on_road and dt > 0:
        _spent_s += dt
    return remaining_seconds() <= 0.0


def hud_line() -> str | None:
    if not _active:
        return None
    return f"Exposure: {remaining_seconds():05.1f}s / {limit_seconds():05.1f}s"


def summary() -> dict:
    return {
        "limit_s": round(_limit_s, 3),
        "spent_s": round(_spent_s, 3),
        "remaining_s": round(remaining_seconds(), 3),
        "budget_frac": ROAD_BUDGET_FRAC,
        "bonus_frac": TIME_BONUS_TO_EXPOSURE_FRAC,
    }
