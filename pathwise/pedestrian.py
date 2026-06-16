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

    def update(self, keys):
        dx = dy = 0
        if keys.pressed(KEY_LEFT):
            dx -= PEDESTRIAN_SPEED
        if keys.pressed(KEY_RIGHT):
            dx += PEDESTRIAN_SPEED
        if keys.pressed(KEY_UP):
            dy -= PEDESTRIAN_SPEED
        if keys.pressed(KEY_DOWN):
            dy += PEDESTRIAN_SPEED
        self.rect.x += dx
        self.rect.y += dy

