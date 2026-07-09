"""FPS tracker HUD helper."""

import unittest

from pathwise.fps_tracker import FpsTracker


class TestFpsTracker(unittest.TestCase):
    def test_smoothed_fps_from_present_intervals(self):
        tracker = FpsTracker(max_samples=5)
        t = 1000.0
        for _ in range(10):
            tracker.note_present(t)
            t += 1.0 / 60.0
        self.assertAlmostEqual(tracker.smoothed_fps, 60.0, delta=1.0)
        self.assertTrue(tracker.hud_line().startswith("FPS:"))

    def test_first_present_does_not_crash(self):
        tracker = FpsTracker()
        tracker.note_present(1.0)
        self.assertEqual(tracker.hud_line(), "FPS: 60")


if __name__ == "__main__":
    unittest.main()
