"""Sprint movement: toggle speed boost; risky on roads/crosswalks."""

from __future__ import annotations

SPRINT_SPEED_MULT = 2.0


def effective_pedestrian_speed(
    base_speed: float,
    sprinting: bool,
    *,
    time_scale: float = 1.0,
    physics_scale: float = 1.0,
    player_speed_mult: float = 1.0,
) -> float:
    sprint_mult = SPRINT_SPEED_MULT if sprinting else 1.0
    return (
        float(base_speed)
        * sprint_mult
        * float(time_scale)
        * float(physics_scale)
        * float(player_speed_mult)
    )


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
