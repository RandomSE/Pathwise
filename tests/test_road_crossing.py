"""Direction-agnostic road crossing detection."""

import unittest

import main as game
from pathwise.map import Road, make_rectangle
from pathwise import commonUtils


class TestRoadCrossing(unittest.TestCase):
    def test_vertical_road_counts_crossing_from_bottom(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (155, 500)
        curr = (155, 300)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_vertical_road_counts_crossing_from_top(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (155, 300)
        curr = (155, 500)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_vertical_road_ignores_parallel_motion(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        prev = (120, 300)
        curr = (180, 300)
        self.assertFalse(game.road_midline_crossed(prev, curr, road))

    def test_horizontal_road_counts_crossing_from_left(self):
        road = Road(make_rectangle(200, 100, 400, 110), commonUtils.HORIZONTAL)
        prev = (300, 155)
        curr = (500, 155)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))

    def test_horizontal_road_counts_crossing_from_right(self):
        road = Road(make_rectangle(200, 100, 400, 110), commonUtils.HORIZONTAL)
        prev = (450, 155)
        curr = (350, 155)
        self.assertTrue(game.road_midline_crossed(prev, curr, road))


if __name__ == "__main__":
    unittest.main()
