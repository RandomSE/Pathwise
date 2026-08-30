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

    def test_normal_uses_coarser_far_stride_than_easy(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        normal = GameTuning.for_preset("normal", profile)
        easy = GameTuning.for_preset("easy", profile)
        self.assertGreater(normal.OFFSCREEN_FAR_STRIDE, easy.OFFSCREEN_FAR_STRIDE)
        self.assertGreaterEqual(normal.SHELL_SEP_EVERY_N_FRAMES, 3)

    def test_near_stride_is_live_and_not_coarser_than_far(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        hard = GameTuning.for_preset("hard", profile)
        self.assertGreaterEqual(hard.OFFSCREEN_NEAR_STRIDE, 2)
        self.assertLessEqual(hard.OFFSCREEN_NEAR_STRIDE, hard.OFFSCREEN_FAR_STRIDE)
        self.assertEqual(hard.OFFSCREEN_NEAR_STRIDE, hard.OFFSCREEN_UPDATE_STRIDE)

    def test_install_for_round_updates_module(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        install_for_round("hard", profile)
        self.assertEqual(
            sim_constants.OFFSCREEN_FAR_STRIDE,
            GameTuning.for_preset("hard", profile).OFFSCREEN_FAR_STRIDE,
        )


if __name__ == "__main__":
    unittest.main()
