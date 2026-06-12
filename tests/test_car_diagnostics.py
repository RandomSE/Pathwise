import unittest

from analytics.car_diagnostics import (
    BACKWARD_ALONG_EPS,
    displacement_along_travel,
    is_backward_along_travel,
    travel_label,
)


class TestDisplacementAlongTravel(unittest.TestCase):
    def test_south_forward(self):
        self.assertGreater(displacement_along_travel(0, 5, True, 1), 0)

    def test_south_backward(self):
        along = displacement_along_travel(0, -6, True, 1)
        self.assertTrue(is_backward_along_travel(along))

    def test_east_backward(self):
        along = displacement_along_travel(-7, 0, False, 1)
        self.assertLess(along, -BACKWARD_ALONG_EPS)

    def test_small_jitter_not_backward(self):
        along = displacement_along_travel(0, -1, True, 1)
        self.assertFalse(is_backward_along_travel(along))


class TestTravelLabel(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(travel_label(True, 1), "south")
        self.assertEqual(travel_label(True, -1), "north")
        self.assertEqual(travel_label(False, 1), "east")
        self.assertEqual(travel_label(False, -1), "west")


if __name__ == "__main__":
    unittest.main()
