import unittest

from pathwise.geom import Rect


class TestTurnStuckFixes(unittest.TestCase):
    def test_can_resume_snapped_arc_when_on_hold(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=5)
        car._turn_exit = (0, 1, True)
        car._turn_phase = "none"
        car._turn_hold_frames = 8
        car._turn_snap_travel = 40.0
        car._turn_arc_len = 80.0
        car._turn_arc_start = (100.0, 100.0)
        car._turn_arc_mid = (120.0, 110.0)
        car._turn_arc_end = (130.0, 140.0)
        car._turn_entry_vertical = False
        car._turn_entry_direction = 1
        car._turn_path_clear = (lambda *a, **k: True).__get__(car, type(car))

        self.assertTrue(
            car._can_resume_turn_arc(
                [],
                Rect(0, 0, 1, 1),
                True,
                [],
            )
        )

    def test_blinker_only_not_committed_turn(self):
        import main as game

        zone = Rect(80, 80, 80, 80)
        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car.turn_signal = -1
        car._turn_exit = (0, 1, True)
        car._turn_phase = "none"
        car.rect.center = (zone.centerx, zone.centery)
        car._sync_collision_shell(force=True)

        self.assertFalse(car._committed_intersection_turn([zone]))

    def test_to_hub_with_signal_is_committed_in_intersection(self):
        import main as game

        zone = Rect(80, 80, 80, 80)
        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car.turn_signal = -1
        car._turn_exit = (0, 1, True)
        car._turn_phase = "to_hub"
        car._turn_hub = (zone.centerx, zone.centery)
        car.current_speed = 1.0
        car.rect.center = (zone.centerx, zone.centery)
        car._sync_collision_shell(force=True)

        self.assertTrue(car._committed_intersection_turn([zone]))

    def test_replan_preserves_exit_turn_side(self):
        from map_generation.intersection_routing import turn_side_from_exit
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=2)
        exit_plan = (0, 1, True)
        side = car._turn_side_for_exit_plan(exit_plan)
        expected = turn_side_from_exit(False, 1, True, 1)
        self.assertEqual(side, expected)

    def test_right_turn_arc_rotates_with_blinker_not_shortest_path(self):
        from pathwise.car import _lerp_turn_angle_deg

        # Eastbound right turn (south exit angle -90): mid-arc must not swing north (-45).
        mid = _lerp_turn_angle_deg(0.0, -90.0, 0.5, 1)
        self.assertGreater(mid, 0.0)
        self.assertAlmostEqual(mid, 135.0, places=1)

    def test_replan_locked_during_active_arc(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=3)
        zone = Rect(80, 80, 80, 80)
        car._turn_phase = "turning"
        car._turn_exit = (0, 1, True)
        car.turn_signal = 1
        applied = car._replan_turn_at_zone(
            [],
            zone,
            (zone.x, zone.y, zone.w, zone.h),
            [],
            Rect(0, 0, 1, 1),
            True,
            intended_exit=(1, -1, True),
            intended_signal=1,
        )
        self.assertFalse(applied)
        self.assertEqual(car._turn_exit, (0, 1, True))

    def test_steering_checks_overlap_before_advancing_arc(self):
        import main as game

        turner = game.Car(100, 100, 3.0, vertical=False, spawn_id=10)
        turner._turn_phase = "turning"
        turner._turn_exit = (0, 1, True)
        turner._turn_entry_vertical = False
        turner._turn_entry_direction = 1
        turner._turn_arc_start = (100.0, 100.0)
        turner._turn_arc_mid = (120.0, 110.0)
        turner._turn_arc_end = (130.0, 140.0)
        turner._turn_arc_len = 80.0
        turner._turn_arc_travel = 10.0
        turner._turn_angle_start = 0.0
        turner._turn_angle_end = 90.0
        turner._turn_arc_side = -1
        turner._turn_px = 105.0
        turner._turn_py = 102.0
        turner._turn_side = 40
        turner._sync_collision_shell(force=True)
        travel_before = turner._turn_arc_travel

        blocker = game.Car(108, 104, 3.0, vertical=False, spawn_id=1)
        blocker._turn_phase = "none"
        blocker._sync_collision_shell(force=True)
        turner._turn_segment_clear = (lambda *a, **k: True).__get__(turner, type(turner))
        turner._stopped_car_blocks_turn_exit = (lambda *a, **k: False).__get__(
            turner, type(turner)
        )

        turner._steer_through_turn(
            [],
            [],
            [blocker],
            Rect(0, 0, 1, 1),
            True,
        )
        self.assertEqual(turner._turn_arc_travel, travel_before)


if __name__ == "__main__":
    unittest.main()
