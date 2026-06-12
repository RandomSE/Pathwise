"""Coverage for map_generation.difficulty profiles and adaptive scaling."""

import unittest

from map_generation.difficulty import DifficultyProfile, adaptive_difficulty


class TestDifficultyProfile(unittest.TestCase):
    def test_default_and_to_dict(self):
        profile = DifficultyProfile.default()
        d = profile.to_dict()
        self.assertIn("level", d)
        self.assertEqual(d["level"], profile.level)

    def test_for_menu_presets(self):
        for preset in ("easy", "normal", "hard", "unknown"):
            profile = DifficultyProfile.for_menu_preset(preset)
            self.assertGreater(profile.min_crossings, 0)

    def test_for_round_single_round(self):
        base = DifficultyProfile.for_menu_preset("normal")
        profile = DifficultyProfile.for_round(base, 0, total_rounds=1)
        self.assertEqual(profile.round_escalation, 0.0)

    def test_for_round_escalates(self):
        base = DifficultyProfile.for_menu_preset("hard")
        first = DifficultyProfile.for_round(base, 0, total_rounds=3)
        last = DifficultyProfile.for_round(base, 2, total_rounds=3)
        self.assertLessEqual(first.car_speed_mult, last.car_speed_mult)
        self.assertGreaterEqual(last.round_escalation, first.round_escalation)

    def test_from_level_clamps(self):
        low = DifficultyProfile.from_level(-1)
        high = DifficultyProfile.from_level(99)
        self.assertGreaterEqual(low.level, 0.0)
        self.assertLessEqual(high.level, 1.0)


class TestAdaptiveDifficulty(unittest.TestCase):
    def test_no_prior_session(self):
        self.assertEqual(adaptive_difficulty(None).level, DifficultyProfile.default().level)

    def test_success_fast_low_risk(self):
        profile = adaptive_difficulty(
            {"outcome": "success", "duration_s": 10, "time_limit": 30, "risk_events": 0, "collisions": 0}
        )
        self.assertGreater(profile.level, 0.6)

    def test_success_slow(self):
        profile = adaptive_difficulty(
            {"outcome": "success", "duration_s": 25, "time_limit": 30, "risk_events": 3, "collisions": 0}
        )
        self.assertLess(profile.level, 0.6)

    def test_timeout_and_collision(self):
        timeout = adaptive_difficulty({"outcome": "timeout"})
        collision = adaptive_difficulty({"outcome": "collision", "collisions": 2, "risk_events": 6})
        self.assertLess(timeout.level, 0.4)
        self.assertLess(collision.level, 0.35)

    def test_unknown_outcome(self):
        profile = adaptive_difficulty({"outcome": "quit"})
        self.assertAlmostEqual(profile.level, 0.4, places=2)


if __name__ == "__main__":
    unittest.main()
