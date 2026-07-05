"""Batched Arcade sprite drawing for entities (cars, player)."""

from __future__ import annotations

import arcade

from .geom import Rect, rects_overlap
from .pathwise_render import sim_y_to_arcade


class EntityDrawBatch:
    """Draw entities with a single SpriteList GPU batch per frame."""

    def __init__(self) -> None:
        self._sprites = arcade.SpriteList(use_spatial_hash=False)
        self._pool: list[arcade.Sprite] = []

    def _sprite_at(self, index: int) -> arcade.Sprite:
        while len(self._pool) <= index:
            placeholder = arcade.SpriteSolidColor(2, 2, (0, 0, 0, 0))
            placeholder.visible = False
            self._pool.append(placeholder)
        return self._pool[index]

    def draw_entities(
        self,
        entities,
        camera_offset: tuple[int, int],
        sim_height: int,
        layout=None,
    ) -> None:
        """Draw a pre-culled entity list (no per-frame visibility scan)."""
        _ = layout
        if not entities:
            return
        cam_x, cam_y = camera_offset
        self._sprites.clear()
        for index, entity in enumerate(entities):
            asset = entity.image
            sprite = self._sprite_at(index)
            if sprite.texture is not asset.texture:
                sprite.texture = asset.texture
            shifted = entity.rect.move(-cam_x, -cam_y)
            sprite.width = shifted.width
            sprite.height = shifted.height
            sprite.center_x = shifted.centerx
            sprite.center_y = sim_y_to_arcade(shifted.centery, sim_height)
            sprite.visible = True
            self._sprites.append(sprite)
        for index in range(len(entities), len(self._pool)):
            self._pool[index].visible = False
        self._sprites.draw()

    def draw_visible(
        self,
        entities,
        view_rect: Rect,
        camera_offset: tuple[int, int],
        sim_height: int,
        layout=None,
    ) -> None:
        visible = [e for e in entities if rects_overlap(view_rect, e.rect)]
        self.draw_entities(visible, camera_offset, sim_height, layout)
