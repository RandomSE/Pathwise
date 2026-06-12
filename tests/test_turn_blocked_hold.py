import unittest

from pathwise.geom import Rect


class TestTurnBlockedHold(unittest.TestCase):
    def test_hold_turn_and_replan_stops_without_clearing_signal(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=7)
        car.turn_signal = -1
        car._turn_exit = (0, 1, True)
        car._turn_hub = (120, 120)
        car.current_speed = 2.5
        car.speed = 2.5
        zone = Rect(90, 90, 60, 60)
        car._hold_turn_and_replan([zone], [])

        self.assertEqual(car.current_speed, 0.0)
        self.assertEqual(car.speed, 0.0)
        self.assertEqual(car.turn_signal, -1)
        self.assertIsNotNone(car._turn_exit)
        self.assertGreater(car._turn_hold_frames, 0)

    def test_hold_keeps_turn_signal_after_many_frames(self):
        import main as game

        zone = Rect(90, 90, 60, 60)
        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=7)
        car.turn_signal = 1
        car._turn_exit = (0, 1, True)
        car._turn_hub = (120, 120)
        for _ in range(game.TURN_HOLD_RETRY_FRAMES + 5):
            car._hold_turn_and_replan([zone], [])
        self.assertEqual(car.turn_signal, 1)
        self.assertIsNotNone(car._turn_exit)
        self.assertEqual(car.current_speed, 0.0)

    def test_turn_side_candidates_try_opposite_before_straight(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=3)
        self.assertEqual(car._turn_side_candidates(1), [1, -1, 0])
        self.assertEqual(car._turn_side_candidates(-1), [-1, 1, 0])
        self.assertEqual(car._turn_side_candidates(0), [0, -1, 1])

    def test_hold_blocks_rearm_to_hub(self):
        import main as game

        zone = Rect(90, 90, 60, 60)
        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=8)
        car.turn_signal = -1
        car._turn_exit = (0, -1, True)
        car._turn_hold_frames = 1
        car._turn_phase = "none"
        car.rect.center = (zone.centerx - 6, zone.centery)
        car._sync_collision_shell(force=True)
        car._arm_turn_through_hub([], [zone])
        self.assertEqual(car._turn_phase, "none")
        self.assertIsNone(car._turn_hub)


if __name__ == "__main__":
    unittest.main()
