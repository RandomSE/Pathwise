"""Batched Arcade sprite drawing for entities (cars, player)."""

from __future__ import annotations

import arcade

from .geom import Rect, rects_overlap
from .pathwise_render import sim_y_to_arcade


class EntityDrawBatch:
    """Draw entities with a single SpriteList GPU batch per frame."""

    def __init__(self) -> None:
        self._window_id: int | None = None
        self._rebuild_pool()

    def _rebuild_pool(self) -> None:
        self._sprites = arcade.SpriteList(use_spatial_hash=False)
        self._pool: list[arcade.Sprite] = []

    def _bind_current_window(self) -> None:
        """SpriteList atlases die with the Arcade window; rebuild on a new ctx."""
        try:
            window = arcade.get_window()
        except Exception:
            window = None
        window_id = id(window) if window is not None else None
        if window_id != self._window_id:
            self._rebuild_pool()
            self._window_id = window_id

    def _ensure_pool(self, count: int) -> None:
        while len(self._pool) < count:
            placeholder = arcade.SpriteSolidColor(2, 2, (0, 0, 0, 0))
            placeholder.center_x = 0
            placeholder.center_y = 0
            placeholder.visible = False
            self._pool.append(placeholder)
            self._sprites.append(placeholder)

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
        self._bind_current_window()
        cam_x, cam_y = camera_offset
        count = len(entities)
        self._ensure_pool(count)
        for index, entity in enumerate(entities):
            asset = entity.image
            sprite = self._pool[index]
            if sprite.texture is not asset.texture:
                sprite.texture = asset.texture
            shifted = entity.rect.move(-cam_x, -cam_y)
            sprite.width = shifted.width
            sprite.height = shifted.height
            sprite.center_x = shifted.centerx
            sprite.center_y = sim_y_to_arcade(shifted.centery, sim_height)
            sprite.angle = float(getattr(entity, "draw_angle", 0.0))
            sprite.visible = True
        for index in range(count, len(self._pool)):
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
