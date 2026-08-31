"""Pedestrian entity."""

from __future__ import annotations

from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP
from pathwise.sim_constants import PEDESTRIAN_SIZE, PEDESTRIAN_SPEED


class Pedestrian(Entity):
    def __init__(self, start_pos):
        super().__init__()
        self.image = sprites.make_pedestrian_surface(PEDESTRIAN_SIZE)
        self.rect = Rect(0, 0, self.image.get_width(), self.image.get_height())
        self.rect.center = start_pos
        self.sprint_enabled = False
        self.draw_angle = 0.0
        self._slip_stun_until = 0.0
        self._last_dx = 0.0
        self._last_dy = 0.0
        # Sub-pixel carry so fractional speeds (e.g. Old 0.5x walk) still advance.
        self._move_carry_x = 0.0
        self._move_carry_y = 0.0

    def toggle_sprint(self) -> None:
        self.sprint_enabled = not self.sprint_enabled

    def is_slip_stunned(self, elapsed: float) -> bool:
        return elapsed < self._slip_stun_until

    def last_move_direction(self) -> tuple[float, float]:
        return (self._last_dx, self._last_dy)

    def begin_slip_stun(
        self,
        *,
        elapsed: float,
        impulse_dx: int,
        impulse_dy: int,
        duration: float | None = None,
    ) -> None:
        from pathwise.modifiers.rainy_roads import SLIP_SPRITE_ANGLE, SLIP_STUN_SECONDS

        stun_s = SLIP_STUN_SECONDS if duration is None else float(duration)
        self._slip_stun_until = elapsed + stun_s
        self.draw_angle = float(SLIP_SPRITE_ANGLE)
        self.rect.x += impulse_dx
        self.rect.y += impulse_dy

    def clear_slip_stun(self, elapsed: float) -> None:
        if self.is_slip_stunned(elapsed):
            return
        self.draw_angle = 0.0

    def _move_speed(self) -> float:
        from pathwise.modifiers import high_speed, lag, old
        from pathwise.sprint import effective_pedestrian_speed

        return effective_pedestrian_speed(
            PEDESTRIAN_SPEED,
            self.sprint_enabled,
            time_scale=high_speed.time_scale(),
            physics_scale=lag.physics_scale(),
            player_speed_mult=old.player_speed_mult(),
        )

    def update(self, keys, *, elapsed: float = 0.0):
        if self.is_slip_stunned(elapsed):
            self.clear_slip_stun(elapsed)
            return
        self.draw_angle = 0.0
        speed = self._move_speed()
        dx = dy = 0.0
        if keys.pressed(KEY_LEFT):
            dx -= speed
        if keys.pressed(KEY_RIGHT):
            dx += speed
        if keys.pressed(KEY_UP):
            dy -= speed
        if keys.pressed(KEY_DOWN):
            dy += speed
        if dx != 0 or dy != 0:
            self._last_dx = dx
            self._last_dy = dy
        self._move_carry_x += dx
        self._move_carry_y += dy
        step_x = int(self._move_carry_x)
        step_y = int(self._move_carry_y)
        self._move_carry_x -= step_x
        self._move_carry_y -= step_y
        self.rect.x += step_x
        self.rect.y += step_y