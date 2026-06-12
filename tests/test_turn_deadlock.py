import unittest

from pathwise.geom import Rect, rects_overlap
from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile


SESSION_SEED = 1890416619
ONCOMING_FREEZE_FRAMES = 180


class TestTurnCorridorBlocking(unittest.TestCase):
    def test_to_hub_does_not_publish_reserved_corridor(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._turn_phase = "to_hub"
        car._turn_exit = (0, 1, True)
        car._turn_hub = (120, 120)
        car._turn_arc_start = (100.0, 100.0)
        car._turn_arc_mid = (110.0, 110.0)
        car._turn_arc_end = (120.0, 140.0)
        self.assertIsNone(car._turn_reserved_rect([Rect(90, 90, 60, 60)]))

    def test_perpendicular_not_blocked_by_turn_corridor_without_shell_touch(self):
        import main as game

        turner = game.Car(200, 200, 3.0, vertical=False, spawn_id=1)
        turner._turn_phase = "turning"
        turner._turn_side = 40
        turner._turn_exit = (0, 1, True)
        turner._turn_hub = (220, 220)
        turner._turn_arc_start = (200.0, 200.0)
        turner._turn_arc_mid = (210.0, 210.0)
        turner._turn_arc_end = (220.0, 260.0)
        turner._set_turn_visual(90.0, 200.0, 200.0)
        turner._sync_collision_shell(force=True)

        zones = [Rect(180, 180, 80, 80)]
        reserved = turner._turn_reserved_rect(zones)
        self.assertIsNotNone(reserved)

        oncoming = game.Car(100, 220, 3.0, vertical=True, spawn_id=2)
        oncoming._turn_phase = "none"
        oncoming.turn_signal = 0
        next_rect = oncoming.rect.copy()
        next_rect.y += 12
        self.assertFalse(
            rects_overlap(
                game.sprites.car_collision_rect_into(
                    next_rect, oncoming.vertical, oncoming._body_rect_scratch
                ),
                turner._collision_shell,
            )
        )
        self.assertFalse(
            oncoming._planned_move_conflicts_active_turn(
                next_rect, [turner], zones
            )
        )

    def test_turning_shell_overlap_still_blocks_straight_traffic(self):
        import main as game

        turning = game.Car(40, 0, 3.0, vertical=False, spawn_id=2)
        turning._turn_phase = "turning"
        turning._turn_side = 40
        turning._turn_exit = (0, 1, False)
        turning._turn_hub = (50, 50)
        turning._sync_collision_shell(force=True)

        straight = game.Car(0, 0, 3.0, vertical=False, spawn_id=1)
        straight._turn_phase = "none"
        next_rect = straight.rect.copy()
        next_rect.x += 8
        self.assertTrue(
            straight._planned_move_conflicts_active_turn(
                next_rect, [turning], []
            )
        )


class TestTurnDeadlockHeadless(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = SESSION_SEED
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")

    def test_no_oncoming_frozen_adjacent_to_turner_over_three_seconds(self):
        frozen: dict[int, int] = {}
        max_frozen: dict[int, int] = {}

        for _ in range(ONCOMING_FREEZE_FRAMES + 240):
            self.game.update_round_frame(KeyState())
            seen: set[int] = set()
            car_list = [c for c in self.game.cars if c.alive()]
            turners = [
                c
                for c in car_list
                if c.turn_signal != 0 or c._turn_phase in ("to_hub", "turning", "settling")
            ]
            for car in car_list:
                if car in turners:
                    continue
                if car.current_speed >= 0.15:
                    continue
                if car.turn_signal != 0 or car._turn_phase != "none":
                    continue
                near_turner = False
                for other in turners:
                    if (
                        abs(car.rect.centerx - other.rect.centerx) < 72
                        and abs(car.rect.centery - other.rect.centery) < 72
                    ):
                        near_turner = True
                        break
                if not near_turner:
                    continue
                sid = car.spawn_id
                seen.add(sid)
                frozen[sid] = frozen.get(sid, 0) + 1
                max_frozen[sid] = max(max_frozen.get(sid, 0), frozen[sid])
            for sid in list(frozen):
                if sid not in seen:
                    frozen[sid] = 0

        offenders = [
            (sid, streak)
            for sid, streak in max_frozen.items()
            if streak > ONCOMING_FREEZE_FRAMES
        ]
        self.assertEqual(
            offenders,
            [],
            msg=f"oncoming cars frozen near turners >3s: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
