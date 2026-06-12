import unittest
from unittest.mock import MagicMock, patch

from pathwise.entity_draw_batch import EntityDrawBatch
from pathwise.geom import Rect


class _FakeAsset:
    def __init__(self, w=60, h=30):
        self.texture = object()
        self.width = w
        self.height = h


class _FakeEntity:
    def __init__(self, left, top, w=60, h=30):
        self.rect = Rect(left, top, w, h)
        self.image = _FakeAsset(w, h)


class TestEntityDrawBatch(unittest.TestCase):
    @patch("pathwise.entity_draw_batch.arcade.SpriteList")
    @patch("pathwise.entity_draw_batch.arcade.Sprite")
    def test_draw_visible_batches_only_in_view(self, sprite_cls, sprite_list_cls):
        sprite = MagicMock()
        sprite_cls.return_value = sprite
        sprite_list = MagicMock()
        sprite_list_cls.return_value = sprite_list

        batch = EntityDrawBatch()
        view_rect = Rect(0, 0, 800, 600)
        entities = [
            _FakeEntity(100, 100),
            _FakeEntity(5000, 5000),
        ]

        batch.draw_entities([entities[0]], (0, 0), 600)

        self.assertEqual(len(batch._lists_by_texture), 1)
        only_list = next(iter(batch._lists_by_texture.values()))
        only_list.append.assert_called_once()
        only_list.draw.assert_called_once()

    @patch("pathwise.entity_draw_batch.arcade.SpriteList")
    @patch("pathwise.entity_draw_batch.arcade.Sprite")
    def test_draw_visible_filters_before_batch(self, sprite_cls, sprite_list_cls):
        sprite_cls.return_value = MagicMock()
        sprite_list = MagicMock()
        sprite_list_cls.return_value = sprite_list

        batch = EntityDrawBatch()
        view_rect = Rect(0, 0, 800, 600)
        entities = [_FakeEntity(100, 100), _FakeEntity(5000, 5000)]

        batch.draw_visible(entities, view_rect, (0, 0), 600)

        self.assertEqual(sprite_list.append.call_count, 1)

    @patch("pathwise.entity_draw_batch.arcade.SpriteList")
    @patch("pathwise.entity_draw_batch.arcade.Sprite")
    def test_draw_entities_clears_only_used_texture_lists(self, sprite_cls, sprite_list_cls):
        sprite_cls.return_value = MagicMock()
        used_list = MagicMock()
        unused_list = MagicMock()
        batch = EntityDrawBatch()
        batch._lists_by_texture = {111: used_list, 222: unused_list}
        entity = _FakeEntity(100, 100)
        batch._lists_by_texture[id(entity.image.texture)] = used_list

        batch.draw_entities([entity], (0, 0), 600)

        used_list.clear.assert_called_once()
        unused_list.clear.assert_not_called()
        used_list.draw.assert_called_once()
        unused_list.draw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
