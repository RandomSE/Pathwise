import unittest

from pathwise.geom import Rect


class TestCrosswalkBlocking(unittest.TestCase):
    def test_red_blocks_crosswalk_entry(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=1)
        car.direction = 1
        car.rect.right = crosswalk.left - 2
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 4
        self.assertTrue(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )

    def test_red_braking_zeros_speed_past_stop_line(self):
        import main as game

        car = game.Car(100, 100, 3.0, vertical=False, spawn_id=2)
        state = {"light_state": "red"}
        speed = car._apply_approach_signal_braking(
            state,
            stop_distance=-6.0,
            desired_speed=3.0,
            blocking_controls=[],
            brake_dist=80.0,
            creep_dist=12.0,
        )
        self.assertEqual(speed, 0.0)

    def test_retreat_clamps_car_off_crosswalk_on_red(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=3)
        car.direction = 1
        car.rect.right = crosswalk.left + 4
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "approach_rect": zone.inflate(200, 200),
        }
        self.assertTrue(
            car._retreat_from_crosswalk_on_red(
                state, inside_intersection=False, intersection_zones=[zone]
            )
        )
        self.assertLess(car.rect.right, crosswalk.left)

    def test_green_never_blocks_crosswalk_or_retreats(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=4)
        car.direction = 1
        car.current_speed = 0.0
        car.rect.right = crosswalk.left + 4
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "green",
            "seconds_to_change": 0.2,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 3
        self.assertFalse(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )
        self.assertFalse(
            car._retreat_from_crosswalk_on_red(
                state, inside_intersection=False, intersection_zones=[zone]
            )
        )

    def test_yellow_blocks_crosswalk_when_cannot_clear(self):
        import main as game

        zone = Rect(200, 300, 100, 100)
        crosswalk = Rect(zone.left, zone.bottom + 6, zone.w, 22)
        car = game.Car(zone.centerx, 440, 3.0, vertical=True, spawn_id=7)
        car.direction = -1
        car.current_speed = 0.0
        car.rect.top = crosswalk.bottom + 8
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "yellow",
            "seconds_to_change": 0.2,
            "direction": "vertical",
            "approach": "south",
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.y -= 20
        self.assertTrue(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )

    def test_red_blocks_further_crosswalk_travel_when_already_on_strip(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=10)
        car.direction = 1
        car.rect.right = crosswalk.left + 4
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 3
        self.assertTrue(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )

    def test_yellow_allows_crosswalk_when_committed_past_stop(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=9)
        car.direction = 1
        car.current_speed = 0.0
        car.rect.right = crosswalk.left + 4
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "yellow",
            "seconds_to_change": 0.2,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 3
        self.assertFalse(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )

    def test_green_allows_ix_entry_when_committed_past_stop_line(self):
        import main as game

        zone = Rect(100, 100, 80, 80)
        crosswalk = Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=6)
        car.direction = 1
        car.current_speed = 0.0
        car.rect.right = 99
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "green",
            "seconds_to_change": 0.2,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 4
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )

    def test_green_blocks_ix_entry_before_stop_when_cannot_clear(self):
        import main as game

        zone = Rect(200, 300, 100, 100)
        crosswalk = Rect(zone.left, zone.bottom + 6, zone.w, 22)
        car = game.Car(zone.centerx, 440, 3.0, vertical=True, spawn_id=8)
        car.direction = -1
        car.current_speed = 0.0
        car.rect.top = crosswalk.bottom + 8
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "green",
            "seconds_to_change": 0.2,
            "direction": "vertical",
            "approach": "south",
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.y -= 40
        self.assertTrue(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )


if __name__ == "__main__":
    unittest.main()
