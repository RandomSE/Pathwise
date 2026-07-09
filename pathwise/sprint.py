"""Sprint movement — toggle speed boost; risky on roads/crosswalks.

Future: when rain is added, sprinting may introduce a slip chance and may
change auto-cancel-on-surface behavior (not implemented).
"""

from __future__ import annotations

SPRINT_SPEED_MULT = 2.0


def effective_pedestrian_speed(base_speed: float, sprinting: bool) -> float:
    if not sprinting:
        return base_speed
    return base_speed * SPRINT_SPEED_MULT


def sprint_risk_reason(
    *,
    sprinting: bool,
    moved: bool,
    feet_on_road: bool,
    on_crosswalk: bool,
) -> str | None:
    """Risky-tier reason while sprinting, or None. Road takes priority over crosswalk."""
    if not sprinting or not moved:
        return None
    if feet_on_road:
        return "sprint_on_road"
    if on_crosswalk:
        return "sprint_on_crosswalk"
    return None


def on_road_or_crosswalk(*, on_road: bool, on_crosswalk: bool) -> bool:
    return on_road or on_crosswalk


def should_cancel_sprint_on_surface_entry(
    *,
    sprinting: bool,
    on_surface: bool,
    was_on_surface: bool,
    suppressed_this_visit: bool,
    raining: bool = False,
) -> bool:
    """Auto-disable sprint when newly stepping onto road/crosswalk (not when re-toggling)."""
    if raining:
        return False
    if not sprinting or suppressed_this_visit:
        return False
    return on_surface and not was_on_surface
