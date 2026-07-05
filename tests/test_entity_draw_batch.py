"""Unit tests for entity draw batch."""

import unittest
from unittest.mock import MagicMock, patch

import arcade

from pathwise.entity_draw_batch import EntityDrawBatch
from pathwise.geom import Rect


class _FakeAsset:
    def __init__(self, texture):
        self.texture = texture
        self.width = 40
        self.height = 20


class _FakeEntity:
    def __init__(self, x, y, texture):
        self.rect = Rect(x, y, 40, 20)
        self.image = _FakeAsset(texture)


class TestEntityDrawBatch(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        img = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        self.texture = arcade.Texture(img, hash="entity_batch_test")

    @patch.object(arcade.SpriteList, "draw")
    def test_draw_entities_batches_all_entities(self, draw):
        batch = EntityDrawBatch()
        entities = [
            _FakeEntity(100, 100, self.texture),
            _FakeEntity(200, 200, self.texture),
        ]
        batch.draw_entities(entities, (0, 0), 600)
        draw.assert_called_once()
        self.assertEqual(len(batch._sprites), 2)

    @patch.object(arcade.SpriteList, "draw")
    def test_draw_visible_culls_offscreen(self, draw):
        batch = EntityDrawBatch()
        view_rect = Rect(0, 0, 800, 600)
        entities = [
            _FakeEntity(100, 100, self.texture),
            _FakeEntity(5000, 5000, self.texture),
        ]
        batch.draw_visible(entities, view_rect, (0, 0), 600)
        draw.assert_called_once()
        self.assertEqual(len(batch._sprites), 1)


if __name__ == "__main__":
    unittest.main()
