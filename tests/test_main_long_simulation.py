"""Long deterministic sim slices to exercise main.py car/spawn branches."""

import unittest
from unittest.mock import MagicMock, patch

from analytics.spectate_round import SyntheticClock, autopilot_keys
from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KeyState


SESSION_SEED = 1890416619


class TestMainLongSimulation(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = SESSION_SEED
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []
        game.ENABLE_CAR_CAR_SOFT_AVOIDANCE = True

    def test_extended_autopilot_simulation(self):
        clock = SyntheticClock(t=3_000_000.0, dt=1 / 60)
        profile = DifficultyProfile.for_menu_preset("hard")
        with patch.object(self.game.time, "time", clock.now):
            self.game.start_round(1, profile, "hard")
            saw_cars = False
            saw_turn = False
            for frame in range(600):
                keys = autopilot_keys(self.game)
                state = self.game.update_round_frame(keys)
                clock.advance()
                cars = [c for c in self.game.cars.sprites() if c.alive()]
                if cars:
                    saw_cars = True
                if any(getattr(c, "_turn_phase", "none") != "none" for c in cars):
                    saw_turn = True
                if not self.game.round_active:
                    break
                if frame % 60 == 0:
                    self.assertIsNotNone(state)
            if self.game.round_active:
                self.game.end_round(False, timed_out=True)
        self.assertTrue(saw_cars)
        self.assertTrue(saw_turn or len(self.game.round_results) > 0)

    def test_car_diagnostics_during_sim(self):
        clock = SyntheticClock(t=4_000_000.0, dt=1 / 60)
        profile = DifficultyProfile.for_menu_preset("normal")
        prev = self.game.ENABLE_CAR_DIAGNOSTICS
        self.game.ENABLE_CAR_DIAGNOSTICS = True
        try:
            with patch.object(self.game.time, "time", clock.now):
                self.game.start_round(1, profile, "normal")
                self.game.car_diagnostics.begin_round(1)
                for _ in range(240):
                    self.game.update_round_frame(KeyState())
                    clock.advance()
        finally:
            self.game.ENABLE_CAR_DIAGNOSTICS = prev

    def test_shell_separation_pass_runs(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        calls = []

        def hook(car_list):
            calls.append(len(car_list))

        for _ in range(120):
            self.game.update_round_frame(KeyState(), before_shell_separation=hook)
        self.assertGreater(len(calls), 0)

    def test_multi_seed_short_sims(self):
        clock = SyntheticClock(t=5_000_000.0, dt=1 / 60)
        profile = DifficultyProfile.for_menu_preset("normal")
        for seed in (42, 99, SESSION_SEED):
            self.game.session_base_seed = seed
            self.game.round_results = []
            with patch.object(self.game.time, "time", clock.now):
                self.game.start_round(1, profile, "normal")
                for _ in range(200):
                    self.game.update_round_frame(autopilot_keys(self.game))
                    clock.advance()
                if self.game.round_active:
                    self.game.end_round(False, timed_out=True)

    def test_main_entry_smoke(self):
        import main as game

        window = MagicMock()
        with patch("pathwise.pathwise_window.PathwiseWindow", return_value=window):
            game.main()
            window.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
