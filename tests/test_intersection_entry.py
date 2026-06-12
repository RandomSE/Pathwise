import unittest

from pathwise.geom import Rect


class TestIntersectionEntryGate(unittest.TestCase):
    def test_red_blocks_entry_before_stop_line(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=1)
        car.direction = 1
        car.current_speed = 2.0
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": Rect(90, 123, 14, 14),
            "stop_axis": 95,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 8
        self.assertTrue(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )

    def test_green_allows_entry_when_clearable(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=2)
        car.direction = 1
        car.current_speed = 3.0
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": Rect(90, 123, 14, 14),
            "stop_axis": 95,
            "light_state": "green",
            "seconds_to_change": 30.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 4
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )

    def test_yellow_blocks_if_cannot_clear_in_time(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=3)
        car.direction = 1
        car.current_speed = 0.5
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": Rect(90, 123, 14, 14),
            "stop_axis": 95,
            "light_state": "yellow",
            "seconds_to_change": 0.4,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 2
        self.assertTrue(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )
        self.assertEqual(car._clear_distance_through_zone(zone), 85.0)

    def test_can_clear_converts_frame_speed_to_seconds(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=4)
        car.direction = 1
        car.current_speed = 3.0
        car._sync_collision_shell(force=True)
        state = {
            "light_state": "green",
            "seconds_to_change": game._LIGHT_GREEN,
        }
        clear_dist = car._clear_distance_through_zone(zone)
        self.assertGreater(clear_dist, 80.0)
        self.assertTrue(car._can_clear_signal_in_time(state, zone))

    def test_green_allows_approach_with_typical_green_window(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=5)
        car.direction = 1
        car.current_speed = 3.0
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": Rect(90, 123, 14, 14),
            "stop_axis": 95,
            "light_state": "green",
            "seconds_to_change": game._LIGHT_GREEN,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 4
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )

    def test_turning_car_proceeds_on_turn_light_while_straight_red(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=6)
        car.direction = 1
        car.current_speed = 3.0
        car.turn_signal = -1
        car._turn_exit = (0, -1, True)
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": Rect(90, 123, 14, 14),
            "stop_axis": 95,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "turn_light_state": "green",
            "turn_seconds_to_change": 6.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 8
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )


if __name__ == "__main__":
    unittest.main()
