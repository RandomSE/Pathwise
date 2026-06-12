import unittest

from analytics.replay_playback import (
    MAX_PLAYBACK_GAP_S,
    MIN_PLAYBACK_GAP_S,
    REPLAY_STEP_S,
    replay_frame_delay_seconds,
)


class TestReplayPlaybackTiming(unittest.TestCase):
    def test_delay_uses_sim_time_delta(self):
        current = {"seq": 0, "t": 0.687}
        nxt = {"seq": 53, "t": 0.937}
        self.assertAlmostEqual(
            replay_frame_delay_seconds(current, nxt),
            0.25,
            places=3,
        )

    def test_delay_caps_large_sparse_gaps(self):
        current = {"seq": 0, "t": 0.687}
        nxt = {"seq": 53, "t": 5.084}
        self.assertEqual(
            replay_frame_delay_seconds(current, nxt),
            MAX_PLAYBACK_GAP_S,
        )

    def test_delay_ignores_capture_seq_gaps(self):
        current = {"seq": 0, "t": 1.0}
        nxt = {"seq": 200, "t": 1.2}
        self.assertAlmostEqual(
            replay_frame_delay_seconds(current, nxt),
            0.2,
            places=3,
        )

    def test_delay_floors_tiny_gaps(self):
        current = {"t": 1.0}
        nxt = {"t": 1.01}
        self.assertEqual(
            replay_frame_delay_seconds(current, nxt),
            MIN_PLAYBACK_GAP_S,
        )

    def test_delay_fallback_without_times(self):
        self.assertEqual(
            replay_frame_delay_seconds({}, {}),
            REPLAY_STEP_S,
        )


if __name__ == "__main__":
    unittest.main()
