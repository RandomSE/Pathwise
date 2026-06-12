"""Batched Arcade sprite drawing for entities (cars, player)."""

from __future__ import annotations

import arcade

from .geom import Rect, rects_overlap
from .pathwise_render import sim_y_to_arcade


class EntityDrawBatch:
    """Reuse arcade.Sprite instances; batch draws grouped by texture."""

    def __init__(self) -> None:
        self._pool: list[arcade.Sprite] = []
        self._lists_by_texture: dict[int, arcade.SpriteList] = {}

    def draw_entities(
        self,
        entities,
        camera_offset: tuple[int, int],
        window_height: int,
    ) -> None:
        """Draw a pre-culled entity list (no per-frame visibility scan)."""
        if not entities:
            return

        cam_x, cam_y = camera_offset
        while len(self._pool) < len(entities):
            self._pool.append(arcade.Sprite())

        used_lists: set[arcade.SpriteList] = set()
        for idx, entity in enumerate(entities):
            asset = entity.image
            texture = asset.texture
            texture_key = id(texture)
            sprite_list = self._lists_by_texture.get(texture_key)
            if sprite_list is None:
                sprite_list = arcade.SpriteList()
                self._lists_by_texture[texture_key] = sprite_list
            else:
                sprite_list.clear()

            sprite = self._pool[idx]
            sprite.texture = texture
            sprite.width = asset.width
            sprite.height = asset.height
            sprite.center_x = entity.rect.centerx - cam_x
            sprite.center_y = sim_y_to_arcade(entity.rect.centery - cam_y, window_height)
            sprite_list.append(sprite)
            used_lists.add(sprite_list)

        for sprite_list in used_lists:
            sprite_list.draw()

    def draw_visible(
        self,
        entities,
        view_rect: Rect,
        camera_offset: tuple[int, int],
        window_height: int,
    ) -> None:
        visible = [e for e in entities if rects_overlap(view_rect, e.rect)]
        self.draw_entities(visible, camera_offset, window_height)
