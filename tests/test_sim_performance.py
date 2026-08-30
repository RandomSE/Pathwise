import unittest

from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile


class TestSimPerformanceHooks(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 12345
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game._frame_car_spatial._rebuild_counter = 0

    def test_update_round_frame_exposes_preculled_draw_sprites(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = self.game.update_round_frame(KeyState())
        self.assertIsNotNone(draw_state)
        self.assertIn("draw_sprites", draw_state)
        self.assertGreaterEqual(len(draw_state["draw_sprites"]), 1)
        self.assertIs(draw_state["draw_sprites"][0], self.game.player)

    def test_spatial_index_rebuilds_once_per_update_frame(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.game._frame_car_spatial._rebuild_counter = 0
        self.game.update_round_frame(KeyState())
        self.assertEqual(self.game._frame_car_spatial._rebuild_counter, 1)

    def test_car_diagnostics_disabled_by_default(self):
        import main as game

        self.assertFalse(game.ENABLE_CAR_DIAGNOSTICS)

    def test_perf_profile_disabled_by_default(self):
        import importlib
        import os

        import main as game

        saved = os.environ.pop("PATHWISE_PERF_PROFILE", None)
        try:
            importlib.reload(game)
            self.assertFalse(game.ENABLE_PERF_PROFILE)
        finally:
            if saved is not None:
                os.environ["PATHWISE_PERF_PROFILE"] = saved
            importlib.reload(game)
            self.game = game

    def test_update_round_frame_stays_under_spawn_budget(self):
        import time

        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        for _ in range(24):
            self.game.update_round_frame(KeyState())
        t0 = time.perf_counter()
        frames = 36
        for _ in range(frames):
            self.game.update_round_frame(KeyState())
        elapsed = time.perf_counter() - t0
        per_frame_ms = (elapsed / frames) * 1000.0
        self.assertLess(per_frame_ms, 25.0, f"update too slow: {per_frame_ms:.1f}ms/frame")


if __name__ == "__main__":
    unittest.main()
