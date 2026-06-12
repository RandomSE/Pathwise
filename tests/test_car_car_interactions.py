import unittest

from pathwise.geom import Rect, rects_overlap
from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile


SESSION_SEED = 1890416619


class TestCommittedTurnScope(unittest.TestCase):
    def test_to_hub_outside_box_not_committed(self):
        import main as game

        zone = Rect(536, 1005, 90, 90)
        car = game.Car(450, 1031, 3.0, vertical=False, spawn_id=8)
        car._turn_phase = "to_hub"
        car.turn_signal = 1
        car._turn_exit = (14, 1, True)
        car._turn_hub = (zone.centerx, zone.centery)
        car._sync_collision_shell(force=True)

        self.assertFalse(car._rect_in_intersection(car.rect, [zone]))
        self.assertFalse(car._committed_intersection_turn([zone]))

    def test_blinker_approach_outside_box_not_committed(self):
        import main as game

        zone = Rect(536, 1005, 90, 90)
        car = game.Car(450, 1031, 3.0, vertical=False, spawn_id=9)
        car.turn_signal = 1
        car._turn_phase = "none"
        car._sync_collision_shell(force=True)

        self.assertTrue(car._approaching_or_in_intersection([zone]))
        self.assertFalse(car._committed_intersection_turn([zone]))

    def test_stuck_to_hub_not_committed(self):
        import main as game

        zone = Rect(536, 1005, 90, 90)
        car = game.Car(450, 1031, 3.0, vertical=False, spawn_id=8)
        car._turn_phase = "to_hub"
        car.turn_signal = 1
        car.current_speed = 0.0
        car._turn_exit = (14, 1, True)
        car._turn_hub = (zone.centerx, zone.centery)
        car._sync_collision_shell(force=True)

        self.assertFalse(car._committed_intersection_turn([zone]))

    def test_straight_not_frozen_by_distant_to_hub(self):
        import main as game

        zone = Rect(536, 1005, 90, 90)
        turner = game.Car(450, 1031, 3.0, vertical=False, spawn_id=8)
        turner._turn_phase = "to_hub"
        turner.turn_signal = 1
        turner._turn_exit = (14, 1, True)
        turner._turn_hub = (zone.centerx, zone.centery)
        turner._sync_collision_shell(force=True)

        northbound = game.Car(zone.centerx, zone.bottom + 40, 3.0, vertical=True, spawn_id=3)
        northbound.direction = -1
        northbound._turn_phase = "none"
        northbound.turn_signal = 0
        northbound._sync_collision_shell(force=True)

        self.assertFalse(
            northbound._conflicts_with_committed_turner(turner, [zone])
        )


class TestShellPenetration(unittest.TestCase):
    def test_resolve_shell_penetration_separates_overlap(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        b = game.Car(118, 100, 3.0, vertical=False, spawn_id=2)
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        self.assertTrue(rects_overlap(a._collision_shell, b._collision_shell))

        for _ in range(4):
            a._resolve_shell_penetration([b])
            b._resolve_shell_penetration([a])
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        self.assertFalse(rects_overlap(a._collision_shell, b._collision_shell))


class TestToHubYield(unittest.TestCase):
    def test_to_hub_brakes_for_turning_shell(self):
        import main as game

        zone = Rect(536, 1005, 90, 90)
        turner = game.Car(1519, 1015, 3.0, vertical=True, spawn_id=42)
        turner._turn_phase = "turning"
        turner._turn_side = 40
        turner._turn_exit = (14, 1, False)
        turner._turn_hub = (zone.centerx, zone.centery)
        turner._set_turn_visual(45.0, 1519.0, 1015.0)
        turner._sync_collision_shell(force=True)

        waiter = game.Car(1456, 1031, 3.0, vertical=False, spawn_id=12)
        waiter._turn_phase = "to_hub"
        waiter.turn_signal = -1
        waiter._turn_exit = (14, -1, True)
        waiter._turn_hub = (zone.centerx, zone.centery)
        waiter._sync_collision_shell(force=True)

        desired = waiter.base_speed
        for other in [turner]:
            if other._turn_phase in ("turning", "settling") and rects_overlap(
                waiter._collision_shell.inflate(32, 32),
                other._collision_shell,
            ):
                desired = 0.0
        self.assertEqual(desired, 0.0)


class TestCarCarInteractionHeadless(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = SESSION_SEED
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")

    def test_overlap_pairs_bounded_on_seed_session(self):
        overlap_frames = 0
        max_pairs = 0

        for _ in range(820):
            self.game.update_round_frame(KeyState())
            alive = [c for c in self.game.cars if c.alive()]
            pairs = 0
            for i in range(len(alive)):
                for j in range(i + 1, len(alive)):
                    if rects_overlap(alive[i]._collision_shell, alive[j]._collision_shell):
                        pairs += 1
            if pairs:
                overlap_frames += 1
                max_pairs = max(max_pairs, pairs)

        self.assertLessEqual(max_pairs, 3, msg=f"max_pairs={max_pairs}")
        self.assertLess(overlap_frames, 180, msg=f"overlap_frames={overlap_frames}")


if __name__ == "__main__":
    unittest.main()
