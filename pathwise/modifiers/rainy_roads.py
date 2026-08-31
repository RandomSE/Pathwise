"""Rainy roads modifier: braking, overshoot stops, slip hazard."""

from __future__ import annotations

import math

from pathwise.modifiers.registry import ModifierContext

BRAKE_STRENGTH_MULT = 0.55
CROSSWALK_OVERSHOOT_CHANCE = 0.12
SLIP_CHANCE_BASE = 0.05
SLIP_CHANCE_GROWTH_PER_SECOND = 0.001
SLIP_CHANCE_MAX = 0.15
# Kept as alias for older tests / call sites that expect a single rate name.
SLIP_CHANCE_PER_SECOND = SLIP_CHANCE_BASE
SLIP_STUN_SECONDS = 2.5
SLIP_TRIP_MESSAGE = "you tripped while running."
TIME_LIMIT_MULT = 1.5
SLIP_SPRITE_ANGLE = 90
SLIP_IMPULSE_PX = 22

_OVERSHOOT_SALT = 0xA11C
_SLIP_SALT = 0x511C

_ctx: ModifierContext | None = None
_active = False


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active
    _ctx = ctx
    _active = ctx.has("rainy_roads")


def is_active() -> bool:
    return _active


def slip_chance_for_second(second_index: int) -> float:
    """Per-second sprint slip chance: 5% base, +0.1%/s, capped at 15%."""
    chance = SLIP_CHANCE_BASE + max(0, int(second_index)) * SLIP_CHANCE_GROWTH_PER_SECOND
    return min(SLIP_CHANCE_MAX, chance)


def scaled_time_limit(base_seconds: float) -> float:
    if not _active:
        return base_seconds
    return base_seconds * TIME_LIMIT_MULT


def effective_brake_strength(base: float) -> float:
    if not _active:
        return base
    return base * BRAKE_STRENGTH_MULT


def crosswalk_overshoot_enabled(*, spawn_id: int, crosswalk_key: int) -> bool:
    if not _active or _ctx is None:
        return False
    roll = _ctx.rng(_OVERSHOOT_SALT, spawn_id, crosswalk_key).random()
    return roll < CROSSWALK_OVERSHOOT_CHANCE


def crosswalk_overshoot_distance_px(*, spawn_id: int, crosswalk_key: int) -> int:
    if _ctx is None:
        return 0
    rng = _ctx.rng(_OVERSHOOT_SALT + 1, spawn_id, crosswalk_key)
    return int(6 + rng.random() * 10)


def should_disable_player_yield(*, slip_stunned: bool) -> bool:
    return _active and slip_stunned


def slip_impulse_delta(dx: float, dy: float, *, impulse_px: int | None = None) -> tuple[int, int]:
    """Knockback along facing. Magnitude is fixed so faster sprint does not launch farther."""
    px = SLIP_IMPULSE_PX if impulse_px is None else int(impulse_px)
    if dx == 0 and dy == 0:
        dx, dy = 0.0, 1.0
    mag = math.hypot(float(dx), float(dy))
    if mag <= 0:
        return 0, px
    return int(round(dx / mag * px)), int(round(dy / mag * px))


class RainSlipTracker:
    """Track sprint activity per elapsed-second bucket and roll slip chance."""

    def __init__(self) -> None:
        self._sprinted_in_bucket: dict[int, bool] = {}
        self._resolved_buckets: set[int] = set()

    def note_sprint_activity(self, elapsed: float) -> None:
        bucket = int(elapsed)
        self._sprinted_in_bucket[bucket] = True

    def _slip_roll_for_bucket(self, bucket: int) -> bool:
        if _ctx is None or not _active:
            return False
        roll = _ctx.rng(_SLIP_SALT, bucket).random()
        return roll < slip_chance_for_second(bucket)

    def update(self, elapsed: float, player) -> bool:
        """Resolve sprint slips. Returns True if a new slip stun began this call."""
        if not _active:
            return False
        slipped = False
        current_bucket = int(elapsed)
        for bucket in range(len(self._resolved_buckets), current_bucket):
            if bucket in self._resolved_buckets:
                continue
            if not self._sprinted_in_bucket.get(bucket):
                self._resolved_buckets.add(bucket)
                continue
            if self._slip_roll_for_bucket(bucket) and not player.is_slip_stunned(elapsed):
                from pathwise.modifiers import old

                dx, dy = player.last_move_direction()
                impulse_dx, impulse_dy = slip_impulse_delta(dx, dy)
                duration = old.fatal_slip_duration() if old.trip_is_fatal() else None
                player.begin_slip_stun(
                    elapsed=elapsed,
                    impulse_dx=impulse_dx,
                    impulse_dy=impulse_dy,
                    duration=duration,
                )
                slipped = True
            self._resolved_buckets.add(bucket)
        return slipped

    def reset(self) -> None:
        self._sprinted_in_bucket.clear()
        self._resolved_buckets.clear()
