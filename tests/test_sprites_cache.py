import unittest

from pathwise import sprites
from pathwise.sprites import (
    SpriteAsset,
    car_box_surface_cache_key,
    car_surface_cache_key,
    clear_texture_caches,
    make_car_rotated_in_box,
    make_car_surface,
)


class TestTextureCacheKeys(unittest.TestCase):
    def setUp(self):
        clear_texture_caches()

    def test_car_surface_cache_key_normalizes_direction(self):
        self.assertEqual(
            car_surface_cache_key(vertical=False, direction=1, archetype_index=3),
            (0, 1, 3),
        )
        self.assertEqual(
            car_surface_cache_key(vertical=False, direction=-2, archetype_index=3),
            (0, -1, 3),
        )
        self.assertEqual(
            car_surface_cache_key(vertical=True, direction=1, archetype_index=999),
            (1, 1, 999 % sprites.ARCHETYPE_COUNT),
        )

    def test_car_box_cache_key_quantizes_angle(self):
        key_a = car_box_surface_cache_key(5, 91.0, 60, 60)
        key_b = car_box_surface_cache_key(5, 92.0, 60, 60)
        self.assertEqual(key_a, key_b)
        self.assertEqual(key_a[1], 92)

    def test_make_car_surface_returns_cached_sprite_asset(self):
        first = make_car_surface(vertical=False, direction=1, archetype_index=0)
        second = make_car_surface(vertical=False, direction=1, archetype_index=0)
        self.assertIsInstance(first, SpriteAsset)
        self.assertIs(first, second)

    def test_make_car_rotated_in_box_cache_isolated_by_box_size(self):
        a = make_car_rotated_in_box(0, 90.0, 60, 60)
        b = make_car_rotated_in_box(0, 90.0, 64, 64)
        self.assertIsNot(a, b)

    def test_make_car_surface_all_archetypes_and_orientations(self):
        for ai in range(sprites.ARCHETYPE_COUNT):
            for vertical in (False, True):
                for direction in (-1, 1):
                    asset = make_car_surface(
                        vertical=vertical, direction=direction, archetype_index=ai
                    )
                    self.assertGreater(asset.width, 0)
                    self.assertGreater(asset.height, 0)


if __name__ == "__main__":
    unittest.main()
