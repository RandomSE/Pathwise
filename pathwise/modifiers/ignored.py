"""Ignored modifier: cars never slow or stop for the player."""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

_ctx: ModifierContext | None = None
_active = False


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active
    _ctx = ctx
    _active = ctx.has("ignored")


def is_active() -> bool:
    return _active


def should_disable_player_yield() -> bool:
    return _active


def should_skip_player_body_block() -> bool:
    """Cars keep driving into the player; collision still ends the round."""
    return _active


def should_suppress_honk() -> bool:
    """Cars that ignore the player also stay silent."""
    return _active
