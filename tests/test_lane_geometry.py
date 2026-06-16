import unittest

from map_generation.lane_geometry import (
    LANE_KEEP_LEFT_FRAC,
    clamp_keep_left_xy,
    lane_center_xy,
)
from pathwise.geom import Rect


class _Road:
    def __init__(self, direction: str, rect: Rect):
        self.direction = direction
        self.rect = rect


class TestLaneGeometry(unittest.TestCase):
    def test_lane_center_is_farther_from_centerline(self):
        road = _Road("vertical", Rect(100, 50, 60, 200))
        _, cy = lane_center_xy(road, 1)
        half = max(10, int(200 * LANE_KEEP_LEFT_FRAC))
        self.assertEqual(cy, road.rect.centery - half)
        self.assertGreater(half, int(200 * 0.22))

    def test_clamp_keep_left_nudges_right_lane_encroachment_vertical(self):
        road = _Road("vertical", Rect(100, 50, 60, 200))
        _, cy = clamp_keep_left_xy(road, 1, 130.0, road.rect.centery + 20.0, strength=1.0)
        self.assertLess(cy, road.rect.centery + 20.0)
        self.assertLess(cy, road.rect.centery)

    def test_clamp_keep_left_blocks_right_lane_encroachment_horizontal(self):
        road = _Road("horizontal", Rect(50, 100, 200, 60))
        cx, _ = clamp_keep_left_xy(road, 1, road.rect.centerx - 20.0, 130.0)
        self.assertGreater(cx, road.rect.centerx)


if __name__ == "__main__":
    unittest.main()
