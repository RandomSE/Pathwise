"""High speed modifier: everything runs at 2x vs wall clock.

Sim model (multiplicative with other modifiers):
  - sim elapsed advances at wall_dt * TIME_SCALE (timers, lights, exposure, slip)
  - player movement * TIME_SCALE
  - car desired speed * car_speed_scale() (TIME_SCALE, or HIGHWAY_CAR_SCALE on Highway)
  - traffic schedule advances TIME_SCALE frames per wall frame

Compose order for car cruise desired_speed:
  base_speed * variable_speed_zones * high_speed.car_speed_scale()
  (* lag.physics_scale when Lag is active)
"""

from __future__ import annotations

from pathwise.modifiers.registry import ModifierContext

TIME_SCALE = 2.0
# Highway at full 2x exceeds human reaction at hard densities; cars stay 1.5x there.
HIGHWAY_CAR_SCALE = 1.5

_ctx: ModifierContext | None = None
_active = False


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active
    _ctx = ctx
    _active = ctx.has("high_speed")


def is_active() -> bool:
    return _active


def time_scale() -> float:
    """Wall-to-sim multiplier for timers / player (1.0 when inactive)."""
    return TIME_SCALE if _active else 1.0


def car_speed_scale() -> float:
    """Car cruise multiplier; Highway uses a softer 1.5x when High speed is on."""
    if not _active:
        return 1.0
    from pathwise.modifiers import highway

    if highway.is_active():
        return HIGHWAY_CAR_SCALE
    return TIME_SCALE


def frame_steps() -> int:
    """Traffic-schedule / round_frame steps per wall frame."""
    return 2 if _active else 1
