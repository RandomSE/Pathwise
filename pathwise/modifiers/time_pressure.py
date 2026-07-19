"""Time pressure modifier: short start timer, bonus seconds from crossings."""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

START_SECONDS = 10.0
START_SECONDS_WITH_RAIN = 20.0
RAIN_BONUS_MULT = 1.75
# Across-the-board bump vs the prior table (stacking still capped below).
BONUS_GAIN_MULT = 1.25
# Remaining timer may not exceed this many "max single crossing" rewards.
MAX_TIMER_CROSSING_MULT = 2.0
BONUS_POPUP_DURATION_S = 1.4

TIER_UNSAFE_ROAD = "unsafe_road"
TIER_UNSAFE_CROSSWALK = "unsafe_crosswalk"
TIER_SAFE_CROSSWALK = "safe_crosswalk"

RAIN_TIME_PRESSURE_COMBO_NOTE = (
    " Combined with Rainy roads: the timer starts at 20 seconds and crossing "
    "bonuses are 75% larger."
)

# Tuned vs menu crossing bands and target_play_time_s (difficulty.py):
# easy 4-6 (~5 mid) / 50s, normal 5-7 (~6) / 65s, hard 6-9 (~7.5) / 80s.
# Goal: START + mid_crossings * safe ≈ 0.65-0.95 of target when crossings are safe
# (bonuses are 20% below the prior table), with hard still granting the largest
# per-crossing bonuses so denser routes stay finishable.
_BONUS_SECONDS: dict[str, dict[str, float]] = {
    "easy": {
        TIER_UNSAFE_ROAD: 2.0,
        TIER_UNSAFE_CROSSWALK: 3.2,
        TIER_SAFE_CROSSWALK: 4.8,
    },
    "normal": {
        TIER_UNSAFE_ROAD: 2.4,
        TIER_UNSAFE_CROSSWALK: 4.0,
        TIER_SAFE_CROSSWALK: 6.0,
    },
    "hard": {
        TIER_UNSAFE_ROAD: 3.2,
        TIER_UNSAFE_CROSSWALK: 5.6,
        TIER_SAFE_CROSSWALK: 8.0,
    },
}

# Mid crossing counts used for budget checks / docs (menu presets).
_MID_CROSSINGS: dict[str, int] = {"easy": 5, "normal": 6, "hard": 8}
_TARGET_PLAY_S: dict[str, int] = {"easy": 50, "normal": 65, "hard": 80}

_ctx: ModifierContext | None = None
_active = False
_rain_combo = False
_preset_id = "normal"
_last_bonus_seconds = 0.0
_last_bonus_tier: str | None = None
_bonus_events: list[dict] = []
_bonus_total_s = 0.0
_popup_text: str | None = None
_popup_until_elapsed = -1.0


def install_for_round(ctx: ModifierContext, *, preset_id: str = "normal") -> None:
    global _ctx, _active, _rain_combo, _preset_id, _last_bonus_seconds, _last_bonus_tier
    global _bonus_events, _bonus_total_s, _popup_text, _popup_until_elapsed
    _ctx = ctx
    _active = ctx.has("time_pressure")
    _rain_combo = _active and ctx.has("rainy_roads")
    _preset_id = preset_id if preset_id in _BONUS_SECONDS else "normal"
    _last_bonus_seconds = 0.0
    _last_bonus_tier = None
    _bonus_events = []
    _bonus_total_s = 0.0
    _popup_text = None
    _popup_until_elapsed = -1.0


def is_active() -> bool:
    return _active


def rain_combo_active() -> bool:
    return _rain_combo


def start_seconds() -> float:
    if not _active:
        return 0.0
    return START_SECONDS_WITH_RAIN if _rain_combo else START_SECONDS


def initial_time_limit(base_seconds: float) -> float:
    """Replace map timer with a short start clock when active."""
    if not _active:
        return base_seconds
    return start_seconds()


def classify_crossing(*, on_crosswalk: bool, legal_crossing: bool) -> str:
    if on_crosswalk and legal_crossing:
        return TIER_SAFE_CROSSWALK
    if on_crosswalk:
        return TIER_UNSAFE_CROSSWALK
    return TIER_UNSAFE_ROAD


def legal_crossing_for_bonus(
    *,
    on_crosswalk: bool,
    cars_have_red: bool,
    legal_commit_active: bool,
    unsignalized: bool,
) -> bool:
    """Safe painted crossing: car-red/commit, or any crosswalk under lawless."""
    if not on_crosswalk:
        return False
    if unsignalized:
        return True
    return bool(cars_have_red or legal_commit_active)


def bonus_seconds_for(tier: str, *, preset_id: str | None = None) -> float:
    preset = preset_id or _preset_id
    table = _BONUS_SECONDS.get(preset, _BONUS_SECONDS["normal"])
    base = float(table.get(tier, 0.0)) * BONUS_GAIN_MULT
    if _rain_combo:
        return base * RAIN_BONUS_MULT
    return base


def max_single_crossing_bonus_s(*, extra_mult: float = 1.0) -> float:
    """Largest one-crossing grant, including optional Old (or similar) multiplier."""
    if not _active:
        return 0.0
    return bonus_seconds_for(TIER_SAFE_CROSSWALK) * float(extra_mult)


def max_time_bank_seconds(*, extra_mult: float = 1.0) -> float:
    """Max remaining time allowed under Time pressure."""
    return MAX_TIMER_CROSSING_MULT * max_single_crossing_bonus_s(extra_mult=extra_mult)


def clamp_timer_limit(
    limit: float, *, elapsed: float = 0.0, extra_mult: float = 1.0
) -> float:
    """Clamp absolute timer so remaining time cannot exceed the bank cap."""
    if not _active:
        return float(limit)
    cap = max_time_bank_seconds(extra_mult=extra_mult)
    return min(float(limit), float(elapsed) + cap)


def expected_safe_budget_seconds(preset_id: str, *, crossings: int | None = None) -> float:
    """START + crossings * safe bonus (finishability estimate, no rain combo)."""
    n = int(crossings if crossings is not None else _MID_CROSSINGS.get(preset_id, 6))
    table = _BONUS_SECONDS.get(preset_id, _BONUS_SECONDS["normal"])
    safe = float(table[TIER_SAFE_CROSSWALK]) * BONUS_GAIN_MULT
    return START_SECONDS + n * safe


def apply_crossing_bonus(tier: str, *, elapsed: float | None = None) -> float:
    """Record and return seconds to add to ROUND_TIME_LIMIT (0 when inactive)."""
    global _last_bonus_seconds, _last_bonus_tier, _bonus_total_s
    if not _active:
        return 0.0
    bonus = bonus_seconds_for(tier)
    _last_bonus_seconds = bonus
    _last_bonus_tier = tier
    _bonus_total_s += bonus
    _bonus_events.append({"tier": tier, "bonus_s": bonus})
    if elapsed is not None and bonus > 0:
        arm_bonus_popup(bonus, elapsed)
    return bonus


def arm_bonus_popup(bonus_s: float, elapsed: float) -> None:
    global _popup_text, _popup_until_elapsed
    if bonus_s <= 0:
        return
    if float(bonus_s).is_integer():
        _popup_text = f"+{int(bonus_s)}s"
    else:
        _popup_text = f"+{bonus_s:.1f}s"
    _popup_until_elapsed = float(elapsed) + BONUS_POPUP_DURATION_S


def active_bonus_popup_text(elapsed: float) -> str | None:
    if _popup_text is None or elapsed > _popup_until_elapsed:
        return None
    return _popup_text


def last_bonus_seconds() -> float:
    return _last_bonus_seconds


def last_bonus_tier() -> str | None:
    return _last_bonus_tier


def bonus_table_for_preset(preset_id: str) -> dict[str, float]:
    return dict(_BONUS_SECONDS.get(preset_id, _BONUS_SECONDS["normal"]))


def bonus_summary() -> dict:
    return {
        "preset": _preset_id,
        "start_seconds": start_seconds(),
        "rain_combo": _rain_combo,
        "total_bonus_s": round(_bonus_total_s, 2),
        "events": list(_bonus_events),
    }
