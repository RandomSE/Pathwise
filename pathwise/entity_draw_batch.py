"""Batched Arcade sprite drawing for entities (cars, player)."""

from __future__ import annotations

from .geom import Rect, rects_overlap
from .pathwise_render import draw_sprite_asset


class EntityDrawBatch:
    """Draw entities via cached SpriteAsset textures (no per-frame SpriteList churn)."""

    def draw_entities(
        self,
        entities,
        camera_offset: tuple[int, int],
        window_height: int,
    ) -> None:
        """Draw a pre-culled entity list (no per-frame visibility scan)."""
        if not entities:
            return
        for entity in entities:
            draw_sprite_asset(
                entity.image,
                entity.rect,
                camera_offset,
                window_height,
            )

    def draw_visible(
        self,
        entities,
        view_rect: Rect,
        camera_offset: tuple[int, int],
        window_height: int,
    ) -> None:
        visible = [e for e in entities if rects_overlap(view_rect, e.rect)]
        self.draw_entities(visible, camera_offset, window_height)
