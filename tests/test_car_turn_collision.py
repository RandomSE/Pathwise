import unittest

from pathwise.geom import Rect


class TestTurnCollisionPolicy(unittest.TestCase):
    def test_cap_all_cars_iterations_restored(self):
        import main as game

        self.assertGreaterEqual(game.CAP_ALL_CARS_ITERATIONS, 4)

    def test_road_states_for_turning_car_uses_tagged_subset(self):
        import main as game

        tagged = [{"road_index": 0}]
        game.road_states_by_index = [tagged, []]
        fallback = [{"fallback": True}, {"cross": True}]

        class _CarStub:
            road_index = 0
            turn_signal = 0
            _turn_phase = "turning"

        car = _CarStub()
        states = game._road_states_for_car(car, fallback)
        self.assertEqual(states, tagged)

    def test_shell_blocks_turn_path_uses_full_peer_shell(self):
        import main as game

        blocker = _ShellPeer(Rect(50, 50, 30, 30), turn_phase="none")
        car = game.Car(0, 0, 3.0, vertical=False, spawn_id=99)
        car._turn_phase = "turning"
        car._turn_side = 40
        shell = car._turn_probe_shell(60.0, 60.0)
        self.assertTrue(
            car._shell_blocks_turn_path(shell, [blocker], Rect(0, 0, 1, 1), True)
        )

    def test_turn_speed_constants_faster(self):
        import main as game

        self.assertGreaterEqual(game.TURN_DRIFT_SPEED_FRAC, 0.8)
        self.assertLessEqual(game.TURN_SETTLE_FRAMES, 10)

    def test_straight_car_blocked_by_turning_shell(self):
        import main as game

        straight = game.Car(0, 0, 3.0, vertical=False, spawn_id=1)
        straight._turn_phase = "none"
        straight.turn_signal = 0
        turning = game.Car(40, 0, 3.0, vertical=False, spawn_id=2)
        turning._turn_phase = "turning"
        turning._turn_side = 40
        turning._turn_exit = (0, 1, False)
        turning._turn_hub = (50, 50)
        turning._sync_collision_shell(force=True)
        next_rect = straight.rect.copy()
        next_rect.x += 8
        self.assertTrue(
            straight._planned_move_conflicts_active_turn(
                next_rect, [turning], []
            )
        )
        self.assertEqual(
            straight._soft_overlap_creep_cap(
                next_rect, [turning], [], intersection_zones=[]
            ),
            0.0,
        )

    def test_turn_arc_midpoint_biases_to_tangent_corner(self):
        import main as game

        zone = Rect(100, 100, 120, 120)
        car = game.Car(130, 148, 3.0, vertical=False, spawn_id=11, road_index=0)
        car._turn_hub = (zone.centerx, zone.centery)
        car.rect.center = (190, 156)
        car._turn_phase = "turning"
        # horizontal entry -> vertical exit should bias x toward exit and y toward entry
        mid_x, mid_y = car._turn_arc_midpoint([], zone, 182.0, 210.0)
        self.assertGreater(mid_x, zone.centerx)
        self.assertLess(mid_y, 190.0)


class _ShellPeer:
    def __init__(self, shell: Rect, turn_phase: str = "none"):
        self._collision_shell = shell
        self._turn_phase = turn_phase


if __name__ == "__main__":
    unittest.main()
