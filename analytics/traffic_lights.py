"""Traffic signal timing helpers (45% green / 10% yellow / 45% red, perpendicular phases)."""

from __future__ import annotations

GREEN_FRAC = 0.45
YELLOW_FRAC = 0.10
RED_FRAC = 0.45


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


def light_state_at(
    elapsed_seconds: float,
    green_s: float,
    yellow_s: float,
    red_s: float,
) -> str:
    cycle = green_s + yellow_s + red_s
    if cycle <= 0:
        return "green"
    t = elapsed_seconds % cycle
    if t < green_s:
        return "green"
    if t < green_s + yellow_s:
        return "yellow"
    return "red"


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


def perpendicular_arm_offset(
    approach_offset: float,
    green_s: float,
    yellow_s: float,
) -> float:
    """Phase offset of the perpendicular through-arm at the same intersection."""
    return approach_offset + green_s + yellow_s


def protected_turn_light_at(
    elapsed_seconds: float,
    approach_phase_offset: float,
    green_s: float,
    yellow_s: float,
    red_s: float,
) -> tuple[str, float]:
    """
    Protected turn signal: green while perpendicular through-traffic is red.

    Returns (turn_light_state, seconds_to_change).
    """
    cycle = green_s + yellow_s + red_s
    if cycle <= 0:
        return "green", 0.0
    perp_off = perpendicular_arm_offset(approach_phase_offset, green_s, yellow_s)
    perp_t = (elapsed_seconds + perp_off) % cycle
    perp_state = light_state_at(elapsed_seconds + perp_off, green_s, yellow_s, red_s)
    if perp_state == "red":
        return "green", cycle - perp_t
    if perp_state == "green":
        return "red", (green_s - perp_t) + yellow_s
    return "red", green_s + yellow_s - perp_t


def perpendicular_phase_offsets(
    base_offset: float,
    green_s: float,
    yellow_s: float,
) -> tuple[float, float]:
    """
    Vertical-arm and horizontal-arm offsets for one intersection.

    When the vertical arm is green, the horizontal arm is in its red interval.
    """
    half = green_s + yellow_s
    return base_offset, base_offset + half
