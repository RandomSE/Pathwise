import tempfile
import unittest

from analytics.spectate_round import run_spectate_round
from pathwise.geom import Rect


SESSION_SEED = 1890416619


class TestTurnWaitBehavior(unittest.TestCase):
    def test_blocked_signaled_car_holds_instead_of_clearing_signal(self):
        import main as game

        zone = Rect(200, 200, 80, 80)
        car = game.Car(180, 220, 3.0, vertical=False, spawn_id=5)
        car.turn_signal = -1
        car._turn_exit = (0, 1, True)
        car._turn_zone_key = (zone.x, zone.y, zone.w, zone.h)
        car._turn_phase = "none"
        car.current_speed = 0.0
        car._turn_wait_frames = game.TURN_SIGNAL_STUCK_FRAMES
        blocker = game.Car(220, 218, 0.0, vertical=False, spawn_id=6)
        blocker._sync_collision_shell(force=True)
        car._sync_collision_shell(force=True)

        car._maintain_turn_plan(
            [],
            [zone],
            [blocker],
            Rect(0, 0, 1, 1),
            True,
            road_states=[],
        )

        self.assertEqual(car.turn_signal, -1)
        self.assertGreater(car._turn_hold_frames, 0)
        self.assertEqual(car.current_speed, 0.0)

    def test_spectate_seed_still_clean_after_wait_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_spectate_round(
                seed=SESSION_SEED,
                autopilot=True,
                output_dir=tmp,
            )
            metrics = result.report["metrics"]
            self.assertEqual(metrics["anomaly_count"], 0)
            self.assertEqual(metrics["by_kind"].get("turn_arc_overlap", 0), 0)


if __name__ == "__main__":
    unittest.main()
