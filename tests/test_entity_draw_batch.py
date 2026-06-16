"""Unit tests for entity draw batch."""

import unittest
from unittest.mock import MagicMock, patch

from pathwise.entity_draw_batch import EntityDrawBatch
from pathwise.geom import Rect


class _FakeAsset:
    def __init__(self):
        self.texture = MagicMock()
        self.width = 40
        self.height = 20


class _FakeEntity:
    def __init__(self, x, y):
        self.rect = Rect(x, y, 40, 20)
        self.image = _FakeAsset()


class TestEntityDrawBatch(unittest.TestCase):
    @patch("pathwise.entity_draw_batch.draw_sprite_asset")
    def test_draw_entities_calls_sprite_asset_per_entity(self, draw_asset):
        batch = EntityDrawBatch()
        entities = [_FakeEntity(100, 100), _FakeEntity(200, 200)]
        batch.draw_entities(entities, (0, 0), 600)
        self.assertEqual(draw_asset.call_count, 2)

    @patch("pathwise.entity_draw_batch.draw_sprite_asset")
    def test_draw_visible_culls_offscreen(self, draw_asset):
        batch = EntityDrawBatch()
        view_rect = Rect(0, 0, 800, 600)
        entities = [_FakeEntity(100, 100), _FakeEntity(5000, 5000)]
        batch.draw_visible(entities, view_rect, (0, 0), 600)
        self.assertEqual(draw_asset.call_count, 1)


if __name__ == "__main__":
    unittest.main()
