import unittest

from analytics.replay_interpolation import frame_at_time, frame_pair_at_time, lerp_replay_frame


class TestReplayInterpolation(unittest.TestCase):
    def test_lerp_player_and_car_midpoint(self):
        left = {
            "t": 0.0,
            "player": {"x": 0, "y": 0, "s": 28},
            "cars": [{"id": 1, "x": 100, "y": 200, "w": 40, "h": 20}],
            "lights": [],
        }
        right = {
            "t": 1.0,
            "player": {"x": 100, "y": 50, "s": 28},
            "cars": [{"id": 1, "x": 200, "y": 300, "w": 40, "h": 20}],
            "lights": [],
        }
        mid = lerp_replay_frame(left, right, 0.5, t=0.5)
        self.assertEqual(mid["player"]["x"], 50)
        self.assertEqual(mid["player"]["y"], 25)
        self.assertEqual(mid["cars"][0]["x"], 150)
        self.assertEqual(mid["cars"][0]["y"], 250)

    def test_frame_at_time_between_keyframes(self):
        frames = [
            {"t": 0.0, "player": {"x": 0, "y": 0, "s": 28}, "cars": [], "lights": []},
            {"t": 0.2, "player": {"x": 20, "y": 0, "s": 28}, "cars": [], "lights": []},
        ]
        lo, hi, alpha = frame_pair_at_time(frames, 0.1)
        self.assertEqual((lo, hi), (0, 1))
        self.assertAlmostEqual(alpha, 0.5, places=3)
        at = frame_at_time(frames, 0.1)
        self.assertEqual(at["player"]["x"], 10)

    def test_car_fades_in_after_half(self):
        left = {"t": 0.0, "player": {"x": 0, "y": 0, "s": 28}, "cars": [], "lights": []}
        right = {
            "t": 1.0,
            "player": {"x": 0, "y": 0, "s": 28},
            "cars": [{"id": 9, "x": 50, "y": 50}],
            "lights": [],
        }
        early = lerp_replay_frame(left, right, 0.25)
        late = lerp_replay_frame(left, right, 0.75)
        self.assertEqual(early["cars"], [])
        self.assertEqual(len(late["cars"]), 1)


if __name__ == "__main__":
    unittest.main()
