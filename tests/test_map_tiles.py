import unittest
from unittest.mock import patch

import arcade
from PIL import Image

from pathwise.geom import Rect
from pathwise.map_visuals import MAP_TILE_SIZE, BakedMapLayer, MapTile, _tile_baked_image, draw_baked_map


class TestMapTiles(unittest.TestCase):
    def test_tile_baked_image_covers_world_bounds(self):
        world_bounds = Rect(100, 200, 900, 700)
        img = Image.new("RGBA", (world_bounds.width, world_bounds.height), (10, 20, 30, 255))
        tiles = _tile_baked_image(img, world_bounds, "test_map")

        self.assertGreater(len(tiles), 1)
        for tile in tiles:
            self.assertIsInstance(tile, MapTile)
            self.assertGreater(tile.texture.width, 0)
            self.assertGreater(tile.texture.height, 0)
            self.assertGreaterEqual(tile.world_rect.width, 1)
            self.assertGreaterEqual(tile.world_rect.height, 1)
            self.assertGreaterEqual(tile.world_rect.left, world_bounds.left)
            self.assertLessEqual(tile.world_rect.right, world_bounds.right)
            self.assertGreaterEqual(tile.world_rect.top, world_bounds.top)
            self.assertLessEqual(tile.world_rect.bottom, world_bounds.bottom)

        covered = sum(t.world_rect.width * t.world_rect.height for t in tiles)
        self.assertEqual(covered, world_bounds.width * world_bounds.height)

    def test_tile_size_constant_is_reasonable(self):
        self.assertGreaterEqual(MAP_TILE_SIZE, 256)

    @patch("pathwise.pathwise_render.draw_sim_texture_rect")
    def test_draw_baked_map_tile_culling_runs(self, mock_draw):
        world_bounds = Rect(0, 0, 600, 400)
        img = Image.new("RGBA", (world_bounds.width, world_bounds.height), (40, 80, 40, 255))
        tiles = _tile_baked_image(img, world_bounds, "draw_test")
        baked = BakedMapLayer(
            texture=arcade.Texture(img, hash="draw_test_full"),
            world_bounds=world_bounds,
            tiles=tiles,
        )
        view_rect = Rect(0, 0, 800, 600)

        draw_baked_map(baked, (0, 0), 600, view_rect)

        self.assertGreater(mock_draw.call_count, 0)


if __name__ == "__main__":
    unittest.main()
