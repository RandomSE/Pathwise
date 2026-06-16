"""GameTuning centralizes literals and installs per preset."""

import unittest

from map_generation.difficulty import DifficultyProfile
from pathwise import sim_constants
from pathwise.game_tuning import GameTuning, install_for_round, install_tuning


class TestGameTuning(unittest.TestCase):
    def test_default_exports_to_sim_constants(self):
        tuning = GameTuning.default()
        install_tuning(tuning)
        self.assertEqual(sim_constants.CAR_CREEP_SPEED, tuning.CAR_CREEP_SPEED)
        self.assertEqual(sim_constants.STOP_LINE_GAP, tuning.STOP_LINE_GAP)
        lg, ly, lr = tuning.light_durations()
        self.assertEqual(sim_constants.LIGHT_GREEN_DURATION, lg)

    def test_hard_preset_increases_far_stride(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        hard = GameTuning.for_preset("hard", profile)
        easy = GameTuning.for_preset("easy", profile)
        self.assertGreater(hard.OFFSCREEN_FAR_STRIDE, easy.OFFSCREEN_FAR_STRIDE)

    def test_install_for_round_updates_module(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        install_for_round("hard", profile)
        self.assertEqual(
            sim_constants.OFFSCREEN_FAR_STRIDE,
            GameTuning.for_preset("hard", profile).OFFSCREEN_FAR_STRIDE,
        )


if __name__ == "__main__":
    unittest.main()
