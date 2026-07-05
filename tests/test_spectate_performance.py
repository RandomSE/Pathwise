"""Performance regression: 30fps update budget with 90+ cars after 40s hard traffic."""

import os
import time
import unittest
from unittest.mock import patch

from analytics.spectate_round import SyntheticClock
from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KeyState

P95_UPDATE_BUDGET_MS = 45.0


class TestSpectatePerformance(unittest.TestCase):
    def _warm_hard_traffic(self) -> tuple[list[float], object]:
        import main as game

        clock = SyntheticClock(t=1_000_000.0)
        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []
        profile = DifficultyProfile.for_menu_preset("hard")

        with patch.object(game.time, "time", clock.now):
            with patch.object(game, "player_hits_any_car", return_value=False):
                game.start_round(1, profile, "hard")
                for _ in range(2400):
                    game.update_round_frame(KeyState())
                    clock.advance()

                alive = sum(1 for c in game.cars if c.alive())
                self.assertGreaterEqual(alive, 60, f"expected heavy traffic, got {alive}")

                for _ in range(60):
                    game.update_round_frame(KeyState())
                    clock.advance()

                samples_ms = []
                for _ in range(180):
                    t0 = time.perf_counter()
                    game.update_round_frame(KeyState())
                    samples_ms.append((time.perf_counter() - t0) * 1000.0)
                    clock.advance()
        return samples_ms, game

    def test_update_avg_stays_under_30fps_budget_at_40s_hard(self):
        samples_ms, _game = self._warm_hard_traffic()
        avg_ms = sum(samples_ms) / len(samples_ms)
        self.assertLess(avg_ms, 33.0, f"avg update {avg_ms:.1f}ms exceeds 30fps budget")

    @unittest.skipUnless(
        os.environ.get("PATHWISE_STRICT_PERF") == "1",
        "p95 spike budget is machine-load sensitive; set PATHWISE_STRICT_PERF=1 to enforce",
    )
    def test_update_p95_spike_budget_strict(self):
        samples_ms, _game = self._warm_hard_traffic()
        p95_ms = sorted(samples_ms)[int(len(samples_ms) * 0.95)]
        self.assertLess(
            p95_ms,
            P95_UPDATE_BUDGET_MS,
            f"p95 update {p95_ms:.1f}ms too spiky (budget {P95_UPDATE_BUDGET_MS}ms)",
        )

    def test_end_round_runs_once_after_collision(self):
        import main as game

        from analytics.spectate_round import SyntheticClock, autopilot_keys

        clock = SyntheticClock(t=2_000_000.0)
        game.session_base_seed = 42
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")

        with patch.object(game.time, "time", clock.now):
            game.start_round(1, profile, "normal")
            game.end_round(True, timed_out=False)
            before = len(game.round_results)
            game.end_round(True, timed_out=False)
            game.end_round(True, timed_out=False)
            self.assertEqual(len(game.round_results), before)
            self.assertFalse(game.round_active)

            # update should no-op once round ended
            t0 = time.perf_counter()
            for _ in range(60):
                state = game.update_round_frame(autopilot_keys(game))
                clock.advance()
                self.assertIsNone(state)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertLess(elapsed_ms, 50.0, "post-round updates should be near-free")


class TestRedLightStopDistance(unittest.TestCase):
    def test_car_creeps_to_stop_line_not_far_behind(self):
        from pathwise.car import Car
        from pathwise.sim_constants import RED_SIGNAL_CREEP_DIST, STOP_LINE_GAP

        car = Car(100, 200, 3.0, vertical=False, spawn_id=1)
        car.current_speed = 3.0
        car.direction = 1
        crosswalk = __import__("pathwise.geom", fromlist=["Rect"]).Rect(280, 190, 14, 90)
        stop_axis = car._signal_stop_axis(crosswalk)
        blocking: list = []
        # Start ~60px before line — old code froze here; should still allow creep.
        car.rect.right = stop_axis - 60
        speed = car._apply_approach_signal_braking(
            {"crosswalk": crosswalk},
            car._distance_to_signal_stop(stop_axis),
            car.base_speed,
            blocking,
            brake_dist=96,
            creep_dist=RED_SIGNAL_CREEP_DIST,
        )
        self.assertGreater(speed, 0.0)

        # Within creep zone — capped but non-zero until at line.
        car.rect.right = stop_axis - RED_SIGNAL_CREEP_DIST + 4
        creep_speed = car._apply_approach_signal_braking(
            {"crosswalk": crosswalk},
            car._distance_to_signal_stop(stop_axis),
            car.base_speed,
            blocking,
            brake_dist=96,
            creep_dist=RED_SIGNAL_CREEP_DIST,
        )
        self.assertLessEqual(creep_speed, 1.2)
        self.assertGreater(creep_speed, 0.0)

        # At the line — hard hold.
        car.rect.right = stop_axis - STOP_LINE_GAP
        hold_speed = car._apply_approach_signal_braking(
            {"crosswalk": crosswalk},
            car._distance_to_signal_stop(stop_axis),
            car.base_speed,
            blocking,
            brake_dist=96,
            creep_dist=RED_SIGNAL_CREEP_DIST,
        )
        self.assertEqual(hold_speed, 0.0)

    def test_stop_line_clamp_recovers_small_overshoot(self):
        from pathwise.car import Car
        from pathwise.sim_constants import STOP_LINE_GAP

        car = Car(100, 200, 3.0, vertical=False, spawn_id=2)
        car.direction = 1
        crosswalk = __import__("pathwise.geom", fromlist=["Rect"]).Rect(280, 190, 14, 90)
        stop_axis = car._signal_stop_axis(crosswalk)

        # Simulate tiny overshoot while nearly stopped.
        car.rect.right = stop_axis - STOP_LINE_GAP + 3
        self.assertTrue(car._enforce_signal_stop_line(stop_axis))
        self.assertEqual(car.rect.right, stop_axis - STOP_LINE_GAP)


if __name__ == "__main__":
    unittest.main()
