import unittest

from map_generation.turn_clearance import bezier_point, corridor_bounds, sample_bezier


class TestBezier(unittest.TestCase):
    def test_endpoints(self):
        start, mid, end = (0.0, 0.0), (50.0, 50.0), (100.0, 0.0)
        self.assertEqual(bezier_point(0.0, start, mid, end), start)
        self.assertEqual(bezier_point(1.0, start, mid, end), end)

    def test_corridor_includes_arc(self):
        start, mid, end = (0.0, 100.0), (50.0, 50.0), (100.0, 100.0)
        pts = sample_bezier(start, mid, end)
        left, top, right, bottom = corridor_bounds(pts, pad=10.0)
        for px, py in pts:
            self.assertGreaterEqual(px, left)
            self.assertLessEqual(px, right)
            self.assertGreaterEqual(py, top)
            self.assertLessEqual(py, bottom)


if __name__ == "__main__":
    unittest.main()
