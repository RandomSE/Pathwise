"""Pedestrian entity."""

from __future__ import annotations

from pathwise import sprites
from pathwise.entity_group import Entity
from pathwise.geom import Rect
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP
from pathwise.sim_constants import PEDESTRIAN_SIZE, PEDESTRIAN_SPEED, SPRINT_SPEED_MULT


class Pedestrian(Entity):
    def __init__(self, start_pos):
        super().__init__()
        self.image = sprites.make_pedestrian_surface(PEDESTRIAN_SIZE)
        self.rect = Rect(0, 0, self.image.get_width(), self.image.get_height())
        self.rect.center = start_pos
        self.sprint_enabled = False
        self.sprint_suppressed_on_surface = False
        self.was_on_road_or_crosswalk = False

    def toggle_sprint(self) -> None:
        self.sprint_enabled = not self.sprint_enabled

    def _move_speed(self) -> float:
        if self.sprint_enabled:
            return PEDESTRIAN_SPEED * SPRINT_SPEED_MULT
        return PEDESTRIAN_SPEED

    def update(self, keys):
        speed = self._move_speed()
        dx = dy = 0
        if keys.pressed(KEY_LEFT):
            dx -= speed
        if keys.pressed(KEY_RIGHT):
            dx += speed
        if keys.pressed(KEY_UP):
            dy -= speed
        if keys.pressed(KEY_DOWN):
            dy += speed
        self.rect.x += dx
        self.rect.y += dy

