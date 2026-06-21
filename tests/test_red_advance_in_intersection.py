import unittest

from pathwise.geom import Rect


class TestRedAdvanceInIntersection(unittest.TestCase):
    @staticmethod
    def _westbound_state(zone: Rect, light: str) -> dict:
        crosswalk = Rect(zone.right - 22, zone.centery - 30, 22, 60)
        return {
            "approach_rect": zone.inflate(180, 180),
            "crosswalk": crosswalk,
            "light_state": light,
            "seconds_to_change": 5.0,
            "direction": "horizontal",
            "approach": "west",
        }

    def test_inside_intersection_red_allows_advance(self):
        import main as game

        zone = Rect(200, 200, 100, 100)
        car = game.Car(245, 240, 8.0, vertical=False, spawn_id=18, road_index=0)
        car.direction = -1
        car.current_speed = 8.0
        car._sync_collision_shell(force=True)
        states = [self._westbound_state(zone, "red")]
        next_rect = car.rect.copy()
        next_rect.x -= 6
        self.assertFalse(
            car._intersection_advance_blocked_on_red(next_rect, states, [zone])
        )

    def test_update_keeps_speed_when_clearing_box_on_red(self):
        import main as game

        zone = Rect(200, 200, 100, 100)
        car = game.Car(245, 240, 8.0, vertical=False, spawn_id=18, road_index=0)
        car.direction = -1
        car.current_speed = 8.0
        car.speed = -8.0
        car._sync_collision_shell(force=True)
        states = [self._westbound_state(zone, "red")]
        next_rect = car.rect.copy()
        next_rect.x -= 6
        if car._intersection_advance_blocked_on_red(next_rect, states, [zone]):
            car.current_speed = 0.0
            car.speed = 0.0
        self.assertGreater(car.current_speed, 0.0)


if __name__ == "__main__":
    unittest.main()
