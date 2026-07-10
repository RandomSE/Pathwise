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


def should_cancel_sprint_on_crosswalk_entry(
    *,
    sprinting: bool,
    on_crosswalk: bool,
    was_on_crosswalk: bool,
    suppressed_this_visit: bool,
    raining: bool = False,
) -> bool:
    """Auto-disable sprint when newly stepping onto a crosswalk (not road-only)."""
    if raining:
        return False
    if not sprinting or suppressed_this_visit:
        return False
    return on_crosswalk and not was_on_crosswalk


def apply_sprint_crosswalk_frame(
    player,
    *,
    on_crosswalk: bool,
    on_road: bool,
) -> None:
    """Apply crosswalk sprint auto-cancel and per-visit suppression in one atomic step."""
    if should_cancel_sprint_on_crosswalk_entry(
        sprinting=player.sprint_enabled,
        on_crosswalk=on_crosswalk,
        was_on_crosswalk=player.was_on_crosswalk,
        suppressed_this_visit=player.sprint_suppressed_on_crosswalk,
    ):
        player.sprint_enabled = False
        player.sprint_suppressed_on_crosswalk = True

    if player.was_on_crosswalk and not on_crosswalk:
        player.sprint_suppressed_on_crosswalk = False
    elif not on_crosswalk and not on_road:
        player.sprint_suppressed_on_crosswalk = False

    player.was_on_crosswalk = on_crosswalk
    player.was_on_road = on_road


def should_cancel_sprint_on_surface_entry(
    *,
    sprinting: bool,
    on_surface: bool,
    was_on_surface: bool,
    suppressed_this_visit: bool,
    raining: bool = False,
) -> bool:
    """Backward-compatible alias — only crosswalk entry cancels sprint (not road)."""
    return should_cancel_sprint_on_crosswalk_entry(
        sprinting=sprinting,
        on_crosswalk=on_surface,
        was_on_crosswalk=was_on_surface,
        suppressed_this_visit=suppressed_this_visit,
        raining=raining,
    )
