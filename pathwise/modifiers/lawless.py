"""Lawless modifier: crossings remain, traffic signals do not."""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

_ctx: ModifierContext | None = None
_active = False


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active
    _ctx = ctx
    _active = ctx.has("lawless")


def is_active() -> bool:
    return _active


def signals_enabled() -> bool:
    """False when lawless: cars and UI must not treat lights as controlling traffic."""
    return not _active


def should_emit_against_light_risk() -> bool:
    return not _active


def should_emit_uncontrolled_crosswalk_risk(
    *, on_crosswalk: bool, approaching_traffic: bool
) -> bool:
    """Risk when entering/using a painted crosswalk with approaching same-plane traffic."""
    return _active and on_crosswalk and approaching_traffic
