"""Traffic signal timing: 4-phase perpendicular pairs (no green+yellow conflicts)."""

from __future__ import annotations

GREEN_FRAC = 0.45
YELLOW_FRAC = 0.10
RED_FRAC = 0.45

FORBIDDEN_PERPENDICULAR_PAIRS = frozenset(
    {
        ("green", "green"),
        ("green", "yellow"),
        ("yellow", "green"),
        ("yellow", "yellow"),
    }
)


def cycle_durations(
    cycle_seconds: float,
    *,
    green_frac: float = GREEN_FRAC,
    yellow_frac: float = YELLOW_FRAC,
    red_frac: float = RED_FRAC,
) -> tuple[float, float, float]:
    total = green_frac + yellow_frac + red_frac
    if abs(total - 1.0) > 1e-6:
        green_frac /= total
        yellow_frac /= total
        red_frac /= total
    return (
        cycle_seconds * green_frac,
        cycle_seconds * yellow_frac,
        cycle_seconds * red_frac,
    )


def alternation_cycle_length(green_s: float, yellow_s: float) -> float:
    """One green+yellow burst per arm; perpendicular arms alternate."""
    return 2.0 * (green_s + yellow_s)


def light_state_at(
    elapsed_seconds: float,
    green_s: float,
    yellow_s: float,
    red_s: float,
) -> str:
    """Legacy single-arm timeline (green → yellow → red)."""
    cycle = green_s + yellow_s + red_s
    if cycle <= 0:
        return "green"
    t = elapsed_seconds % cycle
    if t < green_s:
        return "green"
    if t < green_s + yellow_s:
        return "yellow"
    return "red"


def perpendicular_light_states_at(
    elapsed_seconds: float,
    phase_offset: float,
    green_s: float,
    yellow_s: float,
) -> tuple[str, str]:
    """
    4-phase intersection timing:
      V green / H red → V yellow / H red → H green / V red → H yellow / V red
    Yellow on one arm always implies the other arm is red.
    """
    alt = alternation_cycle_length(green_s, yellow_s)
    if alt <= 0:
        return "red", "red"
    t = (elapsed_seconds + phase_offset) % alt
    if t < green_s:
        return "green", "red"
    if t < green_s + yellow_s:
        return "yellow", "red"
    if t < 2.0 * green_s + yellow_s:
        return "red", "green"
    return "red", "yellow"


def arm_light_state_at(
    elapsed_seconds: float,
    phase_offset: float,
    *,
    arm_vertical: bool,
    green_s: float,
    yellow_s: float,
) -> str:
    vertical, horizontal = perpendicular_light_states_at(
        elapsed_seconds, phase_offset, green_s, yellow_s
    )
    return vertical if arm_vertical else horizontal


def perpendicular_pair_legal(vertical_state: str, horizontal_state: str) -> bool:
    return (vertical_state, horizontal_state) not in FORBIDDEN_PERPENDICULAR_PAIRS


def seconds_to_change(
    elapsed_seconds: float,
    phase_offset: float,
    green_s: float,
    yellow_s: float,
    red_s: float,
) -> tuple[str, float, str]:
    cycle = green_s + yellow_s + red_s
    t = (elapsed_seconds + phase_offset) % cycle
    state = light_state_at(t, green_s, yellow_s, red_s)
    if state == "green":
        return state, green_s - t, "yellow"
    if state == "yellow":
        return state, green_s + yellow_s - t, "red"
    return state, cycle - t, "green"


def seconds_to_change_arm(
    elapsed_seconds: float,
    phase_offset: float,
    *,
    arm_vertical: bool,
    green_s: float,
    yellow_s: float,
) -> tuple[str, float, str]:
    alt = alternation_cycle_length(green_s, yellow_s)
    t = (elapsed_seconds + phase_offset) % alt
    state = arm_light_state_at(
        elapsed_seconds,
        phase_offset,
        arm_vertical=arm_vertical,
        green_s=green_s,
        yellow_s=yellow_s,
    )
    if state == "green":
        return state, green_s - t, "yellow"
    if state == "yellow":
        if t < green_s + yellow_s:
            return state, (green_s + yellow_s) - t, "red"
        return state, alt - t, "green"
    if t < green_s + yellow_s:
        return state, (green_s + yellow_s) - t, "green"
    if t < 2.0 * green_s + yellow_s:
        return state, (2.0 * green_s + yellow_s) - t, "yellow"
    return state, alt - t, "green"


def perpendicular_arm_offset(
    approach_offset: float,
    green_s: float,
    yellow_s: float,
) -> float:
    """Kept for API compat; 4-phase timing uses direction, not perpendicular offset."""
    return approach_offset


def protected_turn_light_at(
    elapsed_seconds: float,
    approach_phase_offset: float,
    green_s: float,
    yellow_s: float,
    red_s: float,
    *,
    arm_vertical: bool = True,
) -> tuple[str, float]:
    """Turn arrow follows the approach straight signal (no protected green on red)."""
    state, secs, _nxt = seconds_to_change_arm(
        elapsed_seconds,
        approach_phase_offset,
        arm_vertical=arm_vertical,
        green_s=green_s,
        yellow_s=yellow_s,
    )
    return state, secs


def perpendicular_phase_offsets(
    base_offset: float,
    green_s: float,
    yellow_s: float,
) -> tuple[float, float]:
    """Both arms share the same elapsed clock; direction picks the active phase."""
    return base_offset, base_offset
