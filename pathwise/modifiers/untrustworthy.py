"""Untrustworthy modifier: some cars run reds and ignore the player."""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

RUN_RED_CHANCE = 0.25
CONTAGION_RANGE_PX = 150
_UNLAWFUL_SALT = 0xA771

_ctx: ModifierContext | None = None
_active = False
_infected: set[int] = set()


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active, _infected
    _ctx = ctx
    _active = ctx.has("untrustworthy")
    _infected = set()


def is_active() -> bool:
    return _active


def mark_unlawful(spawn_id: int) -> None:
    if not _active:
        return
    _infected.add(int(spawn_id))


def is_unlawful(*, spawn_id: int) -> bool:
    if not _active or _ctx is None:
        return False
    sid = int(spawn_id)
    if sid in _infected:
        return True
    return _ctx.rng(_UNLAWFUL_SALT, sid).random() < RUN_RED_CHANCE


def should_skip_red_stop(*, spawn_id: int) -> bool:
    return is_unlawful(spawn_id=spawn_id)


def should_disable_player_yield(*, spawn_id: int) -> bool:
    return is_unlawful(spawn_id=spawn_id)


def should_skip_player_body_block(*, spawn_id: int) -> bool:
    return is_unlawful(spawn_id=spawn_id)
