"""Unit tests for pathwise.car_viewport (direct module import)."""

import unittest

from pathwise.car import Car, CarSpatialIndex
from pathwise.car_viewport import (
    _cap_cars_near_player,
    _cars_for_replay,
    _cars_in_view,
    _replay_view_rect_for_camera,
    _view_rect_for_camera,
)
from pathwise.geom import Rect
from pathwise.sim_constants import REPLAY_MAX_CARS


class TestCarViewport(unittest.TestCase):
    def test_view_rect_for_camera_returns_rect(self):
        view = _view_rect_for_camera((0, 0), 800, 600)
        self.assertIsInstance(view, Rect)
        self.assertGreater(view.width, 0)
        self.assertGreater(view.height, 0)

    def test_replay_view_wider_than_draw_view(self):
        view = _view_rect_for_camera((10, 20), 800, 600)
        replay = _replay_view_rect_for_camera((10, 20), 800, 600)
        self.assertGreaterEqual(replay.width, view.width)
        self.assertGreaterEqual(replay.height, view.height)

    def test_cars_in_view_filters_dead_and_outside(self):
        car_alive = Car(100, 100, 2.0, vertical=False, spawn_id=1)
        car_dead = Car(200, 200, 2.0, vertical=False, spawn_id=2)
        car_dead.kill()
        car_far = Car(5000, 5000, 2.0, vertical=False, spawn_id=3)
        view = Rect(0, 0, 400, 400)
        visible = _cars_in_view([car_alive, car_dead, car_far], view)
        self.assertEqual(visible, [car_alive])

    def test_cars_for_replay_caps_by_distance(self):
        cars = [
            Car(100 + i * 5, 100, 2.0, vertical=False, spawn_id=i) for i in range(REPLAY_MAX_CARS + 5)
        ]
        replay = _cars_for_replay(cars, (100, 100))
        self.assertEqual(len(replay), REPLAY_MAX_CARS)

    def test_cap_cars_near_player_prefers_nearest(self):
        cars = [Car(100 + i * 20, 100, 2.0, vertical=False, spawn_id=i) for i in range(8)]
        view = Rect(-9999, -9999, 20000, 20000)
        capped = _cap_cars_near_player(cars, view, (100, 100), max_cars=3)
        self.assertEqual(len(capped), 3)
        self.assertEqual(capped[0].spawn_id, 0)

    def test_cars_near_player_uses_spatial_index(self):
        from pathwise.car_viewport import _cars_near_player

        car = Car(100, 100, 2.0, vertical=False, spawn_id=1)
        idx = CarSpatialIndex()
        idx.rebuild([car])
        scratch: list = []
        nearby = _cars_near_player(Rect(95, 95, 20, 20), idx, scratch)
        self.assertIn(car, nearby)


if __name__ == "__main__":
    unittest.main()
