"""Safe-crossing time estimates using traffic-light cycles."""

import math

LIGHT_GREEN_S = 10.0
LIGHT_YELLOW_S = 2.5
LIGHT_RED_S = 7.0
PED_CROSSING_S = 2.0
PED_WAIT_BUFFER_S = 0.8


def light_cycle_seconds(scale: float = 1.0) -> float:
    return (LIGHT_GREEN_S + LIGHT_YELLOW_S + LIGHT_RED_S) * scale


def expected_wait_for_safe_crossing(scale: float = 1.0) -> float:
    """
    Average wait before cars have red (ped can cross safely).
    Pedestrian should not enter when cars have green/yellow.
    """
    cycle = light_cycle_seconds(scale)
    unsafe_fraction = (LIGHT_GREEN_S + LIGHT_YELLOW_S) * scale / cycle
    avg_unsafe_wait = (LIGHT_GREEN_S + LIGHT_YELLOW_S) * scale * 0.5
    return PED_CROSSING_S + PED_WAIT_BUFFER_S + unsafe_fraction * avg_unsafe_wait


def min_time_limit_for_route(
    travel_time_s: float,
    road_crossings: int,
    light_scale: float = 1.0,
    safety_margin: float = 1.18,
) -> int:
    wait = expected_wait_for_safe_crossing(light_scale)
    total = (travel_time_s + road_crossings * wait) * safety_margin
    return max(24, int(math.ceil(total)))
