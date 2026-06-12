import unittest

from pathwise.geom import Rect, rect_overlap_area


class TestRectOverlapArea(unittest.TestCase):
    def test_disjoint_is_zero(self):
        self.assertEqual(rect_overlap_area(Rect(0, 0, 10, 10), Rect(20, 0, 10, 10)), 0)

    def test_partial_overlap(self):
        self.assertEqual(rect_overlap_area(Rect(0, 0, 10, 10), Rect(5, 5, 10, 10)), 25)


class TestSpawnProbe(unittest.TestCase):
    def test_spawn_probe_blocks_without_car_init(self):
        import main as game

        rect, shell = game._spawn_probe_geometry(100, 100, vertical=False)
        self.assertIsInstance(rect, Rect)
        self.assertGreater(shell.width, 0)
        self.assertGreater(shell.height, 0)

    def test_spawn_pose_valid_uses_road_index(self):
        import main as game
        from pathwise.map import Road

        roads = [
            Road(Rect(0, 0, 90, 400), "vertical"),
            Road(Rect(0, 0, 400, 90), "horizontal"),
        ]
        rect, shell = game._spawn_probe_geometry(10, 120, vertical=False)
        self.assertTrue(
            game._spawn_probe_pose_valid(
                shell,
                rect,
                False,
                roads,
                road_index=0,
                block_rects=(),
            )
        )


if __name__ == "__main__":
    unittest.main()
