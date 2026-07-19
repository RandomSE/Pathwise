"""Safe-crossing time estimates using traffic-light cycles."""

# Match main.py: long green, short yellow, red ~= cross time + ~2s
LIGHT_GREEN_S = 20.0
LIGHT_YELLOW_S = 1.0
LIGHT_RED_S = 4.5
PED_CROSSING_S = 2.0
PED_WAIT_BUFFER_S = 0.8


def light_cycle_seconds(scale: float = 1.0) -> float:
    green = LIGHT_GREEN_S * max(0.88, scale)
    yellow = max(0.7, LIGHT_YELLOW_S * scale)
    red = LIGHT_RED_S + max(0.0, (1.0 - scale) * 1.5)
    return green + yellow + red


def expected_wait_for_safe_crossing(scale: float = 1.0) -> float:
    """
    Average wait before cars have red (ped can cross safely).
    Pedestrian should not enter when cars have green/yellow.
    """
    green = LIGHT_GREEN_S * max(0.88, scale)
    yellow = max(0.7, LIGHT_YELLOW_S * scale)
    cycle = light_cycle_seconds(scale)
    unsafe_fraction = (green + yellow) / cycle
    avg_unsafe_wait = (green + yellow) * 0.5
    return PED_CROSSING_S + PED_WAIT_BUFFER_S + unsafe_fraction * avg_unsafe_wait
