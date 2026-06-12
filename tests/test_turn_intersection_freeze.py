import unittest

from pathwise.geom import Rect


class TestTurnIntersectionFreeze(unittest.TestCase):
    def test_hold_in_intersection_preserves_arc_position(self):
        import main as game

        zone = Rect(200, 200, 80, 80)
        car = game.Car(240, 230, 3.0, vertical=False, spawn_id=3)
        car._turn_phase = "turning"
        car._turn_exit = (0, 1, True)
        car.turn_signal = 1
        car._turn_px = 238.0
        car._turn_py = 228.0
        car._turn_arc_travel = 24.0
        car._turn_arc_len = 80.0
        car._turn_angle_start = 0.0
        car._turn_angle_end = 90.0
        car._set_turn_visual(35.0, car._turn_px, car._turn_py)
        before = (car._turn_px, car._turn_py, car._turn_phase)
        car.rect.center = (int(car._turn_px), int(car._turn_py))

        blocker = game.Car(250, 225, 0.0, vertical=True, spawn_id=4)
        blocker._sync_collision_shell(force=True)

        car._hold_turn_and_replan(
            [zone],
            [],
            [blocker],
            Rect(0, 0, 1, 1),
            True,
        )

        self.assertEqual(car._turn_phase, "turning")
        self.assertAlmostEqual(car._turn_px, before[0])
        self.assertAlmostEqual(car._turn_py, before[1])
        self.assertEqual(car.turn_signal, 1)
        self.assertGreater(car._turn_hold_frames, 0)
        self.assertFalse(
            car.rect.right <= zone.left - 30,
            msg="car was clamped back outside the intersection",
        )

    def test_static_traffic_bake_has_no_sign_or_turn_bulb_draw(self):
        import inspect

        from pathwise import map_visuals

        source = inspect.getsource(map_visuals._draw_traffic_static_pil)
        self.assertNotIn("sign_color", source)
        self.assertNotIn("turn_fill", source)


if __name__ == "__main__":
    unittest.main()
