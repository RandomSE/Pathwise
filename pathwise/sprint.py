"""Sprint movement: toggle speed boost; risky on roads/crosswalks."""

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
