import unittest

from pathwise.geom import Rect
from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile


class TestReplayCarRecording(unittest.TestCase):
    def test_frame_recorder_uses_all_in_view_not_draw_cap(self):
        import main as game
        from analytics.frame_recorder import _serialize_car

        game.session_base_seed = 1890416619
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        for _ in range(120):
            game.update_round_frame(KeyState())

        alive = [c for c in game.cars if c.alive()]
        last = game.frame_recorder.frames[-1]
        recorded = len(last["cars"])
        expected_cap = min(len(alive), game.REPLAY_MAX_CARS)
        self.assertGreaterEqual(recorded, expected_cap - 3)
        self.assertLessEqual(recorded, expected_cap)
        if len(alive) > game.MAX_DRAW_RECORD_CARS:
            self.assertGreater(recorded, game.MAX_DRAW_RECORD_CARS)

    def test_serialize_car_includes_spawn_id(self):
        import main as game
        from analytics.frame_recorder import _serialize_car

        car = game.Car(10, 20, 3.0, vertical=False, spawn_id=4242)
        payload = _serialize_car(car, 1.0)
        self.assertEqual(payload["id"], 4242)

    def test_serialize_turning_car_uses_body_dimensions(self):
        import main as game
        from analytics.frame_recorder import _serialize_car
        from pathwise import commonUtils

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._turn_phase = "turning"
        car._turn_entry_vertical = False
        car._turn_side = max(commonUtils.CAR_WIDTH, commonUtils.CAR_HEIGHT)
        car._turn_display_angle = 45.0
        car.rect = Rect(0, 0, car._turn_side, car._turn_side)
        car.rect.center = (120, 130)
        car._turn_px = 120.0
        car._turn_py = 130.0
        payload = _serialize_car(car, 1.0)
        self.assertEqual(payload["w"], commonUtils.CAR_WIDTH)
        self.assertEqual(payload["h"], commonUtils.CAR_HEIGHT)
        self.assertIn("ang", payload)
        self.assertEqual(payload["cx"], 120)
        self.assertEqual(payload["cy"], 130)

    def test_serialize_vertical_entry_turn_uses_horizontal_draw_base(self):
        import main as game
        from analytics.frame_recorder import _serialize_car
        from pathwise import commonUtils

        car = game.Car(100, 100, 3.0, vertical=True, spawn_id=2)
        car._turn_phase = "turning"
        car._turn_entry_vertical = True
        car._turn_side = max(commonUtils.CAR_WIDTH, commonUtils.CAR_HEIGHT)
        car._turn_display_angle = -40.0
        car.rect = Rect(0, 0, car._turn_side, car._turn_side)
        car.rect.center = (200, 210)
        car._turn_px = 200.0
        car._turn_py = 210.0
        payload = _serialize_car(car, 1.0)
        self.assertEqual(payload["w"], commonUtils.CAR_WIDTH)
        self.assertEqual(payload["h"], commonUtils.CAR_HEIGHT)
        self.assertEqual(payload["v"], 0)
        self.assertEqual(payload["tv"], 1)


class TestEndFrameRecording(unittest.TestCase):
    def test_capture_end_matches_in_view_not_global_fleet(self):
        import main as game
        from pathwise.input_keys import KeyState

        game.session_base_seed = 1890416619
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        for _ in range(90):
            game.update_round_frame(KeyState())
        alive = [c for c in game.cars if c.alive()]
        camera = (
            game.player.rect.centerx - game.WIDTH // 2,
            game.player.rect.centery - game.HEIGHT // 2,
        )
        replay_fleet = game._cars_for_replay(alive, game.player.rect.center)
        self.assertEqual(replay_fleet, alive)
        game.end_round(True, timed_out=False)
        end = game.frame_recorder.frames[-1]
        self.assertTrue(end.get("is_end"))
        self.assertEqual(len(end.get("cars", [])), len(alive))


class TestTurnStallAbort(unittest.TestCase):
    def test_turning_cars_do_not_freeze_mid_arc(self):
        import main as game

        game.session_base_seed = 1890416619
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        frozen: dict[int, int] = {}
        last_pos: dict[int, tuple[int, int]] = {}
        for _ in range(600):
            game.update_round_frame(KeyState())
            for car in game.cars:
                if not car.alive() or car._turn_phase != "turning":
                    frozen.pop(car.spawn_id, None)
                    last_pos.pop(car.spawn_id, None)
                    continue
                if car._turn_hold_frames > 0:
                    frozen[car.spawn_id] = 0
                    last_pos[car.spawn_id] = pos
                    continue
                pos = (round(car._turn_px), round(car._turn_py))
                if last_pos.get(car.spawn_id) == pos:
                    frozen[car.spawn_id] = frozen.get(car.spawn_id, 0) + 1
                else:
                    frozen[car.spawn_id] = 0
                last_pos[car.spawn_id] = pos
        bad = {sid: n for sid, n in frozen.items() if n >= game.TURN_STALL_ABORT_FRAMES}
        self.assertEqual(bad, {}, msg=f"turn froze mid-arc: {bad}")


class TestSpawnNotStuck(unittest.TestCase):
    def test_opening_spawns_no_persistent_same_lane_overlap(self):
        import main as game

        game.session_base_seed = 1890416619
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        overlap_streak: dict[int, int] = {}
        for _ in range(180):
            game.update_round_frame(KeyState())
            car_list = [c for c in game.cars if c.alive()]
            for car in car_list:
                if car._spawn_age > 120:
                    continue
                overlapped = False
                for other in car_list:
                    if other is car:
                        continue
                    if not car._same_lane(other, game.CAR_FOLLOW_LANE_GAP):
                        continue
                    from pathwise.geom import collide

                    if collide(car._collision_shell, other._collision_shell):
                        overlapped = True
                        break
                if overlapped:
                    overlap_streak[car.spawn_id] = overlap_streak.get(car.spawn_id, 0) + 1
                else:
                    overlap_streak.pop(car.spawn_id, None)
        bad = {sid: frames for sid, frames in overlap_streak.items() if frames >= 20}
        self.assertEqual(
            bad,
            {},
            msg=f"young spawns overlapping same lane 20+ frames: {bad}",
        )


if __name__ == "__main__":
    unittest.main()
