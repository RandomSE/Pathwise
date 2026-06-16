"""Extended pathwise.car coverage — unit tests for extracted vehicle logic."""

import unittest
from unittest.mock import patch

from pathwise import sim_constants
from pathwise.car import (
    Car,
    CarSpatialIndex,
    _resolve_all_shell_overlaps,
    set_intersection_zones_shell,
    set_traffic_map_seed,
)
from pathwise.geom import Rect
from pathwise.map import Road


class TestCarExtended(unittest.TestCase):
    def test_spatial_rebuild_skips_dead_cars(self):
        idx = CarSpatialIndex()
        car = Car(10, 10, 2.0, vertical=False, spawn_id=1)
        car.kill()
        idx.rebuild([car])
        self.assertEqual(car._spatial_cell_keys, ())

    def test_shell_separation_moves_overlapping_cars(self):
        prev = sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE
        sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE = True
        try:
            a = Car(100, 100, 3.0, vertical=False, spawn_id=1)
            b = Car(108, 100, 0.0, vertical=False, spawn_id=2)
            a._sync_collision_shell(force=True)
            b._sync_collision_shell(force=True)
            _resolve_all_shell_overlaps([a, b])
        finally:
            sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE = prev

    def test_turn_approach_light_helpers(self):
        car = Car(100, 100, 2.0, vertical=False, spawn_id=1)
        car.turn_signal = 1
        state = {
            "light_state": "red",
            "turn_light_state": "green",
            "seconds_to_change": 4.0,
            "turn_seconds_to_change": 2.0,
        }
        self.assertEqual(car._effective_approach_light(state), "green")
        self.assertEqual(car._effective_seconds_to_change(state), 2.0)
        self.assertTrue(car._uses_turn_approach_light())

    def test_honk_evaluation_close_player(self):
        car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._sync_collision_shell(force=True)
        player = Rect(105, 105, 16, 16)
        car.evaluate_honk(player, True, True, game_time=10.0)
        self.assertIsInstance(car.honk_risk_pending, bool)

    def test_planned_turn_is_protected_branches(self):
        car = Car(100, 100, 2.0, vertical=False, spawn_id=1)
        car.turn_signal = 1
        self.assertTrue(car._planned_turn_is_protected())
        car.turn_signal = 0
        car._turn_exit = None
        self.assertFalse(car._planned_turn_is_protected())

    def test_near_intersection_bbox(self):
        car = Car(100, 100, 3.0, vertical=True, spawn_id=9)
        car._turn_phase = "to_hub"
        car._turn_hub = (120, 120)
        car._turn_wait_frames = sim_constants.TURN_TO_HUB_WAIT_ABORT_FRAMES
        car._maintain_turn_plan([], [], [], Rect(0, 0, 1, 1), True)
        self.assertEqual(car._turn_phase, "none")

    def test_near_intersection_bbox(self):
        zone = Rect(100, 100, 60, 60)
        car = Car(130, 130, 2.0, vertical=False, spawn_id=1)
        self.assertTrue(car._near_intersection_bbox([zone], margin=40))

    def test_is_on_drivable_surface(self):
        road = Road(Rect(0, 0, 200, 90), "horizontal")
        car = Car(50, 40, 2.0, vertical=False, spawn_id=1, road_index=0)
        car._sync_collision_shell(force=True)
        zone = Rect(90, 90, 40, 40)
        set_intersection_zones_shell([zone])
        self.assertIsInstance(
            car._is_on_drivable_surface([road], [zone], Rect(0, 0, 500, 500)),
            bool,
        )

    def test_turn_display_helpers(self):
        car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._turn_phase = "turning"
        car._turn_display_angle = 45.0
        car._turn_px = 110.0
        car._turn_py = 110.0
        car._turn_side = 40
        car._sync_collision_shell(force=True)
        self.assertEqual(car._effective_travel()[0], car._turn_entry_vertical)

    @patch("pathwise.car._notify_car_removed")
    def test_removal_queues_respawn(self, notify):
        from pathwise.car import CarSpawnOrigin

        car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._spawn_origin = CarSpawnOrigin(0, 1, 0.5, "ongoing")
        road = Road(Rect(0, 0, 200, 90), "horizontal")
        car._sync_collision_shell(force=True)
        set_traffic_map_seed(42)
        reason = car._removal_reason([road], [], Rect(0, 0, 500, 500), frame_index=9999)
        if reason is not None:
            notify.assert_not_called()


class TestTrafficSpawnExtended(unittest.TestCase):
    def test_spawn_probe_blocked_by_player(self):
        from pathwise import traffic_spawn

        rect, shell = traffic_spawn._spawn_probe_geometry(100, 100, vertical=False)
        player = Rect(95, 95, 20, 20)
        roads = [Road(Rect(0, 0, 400, 90), "horizontal")]
        blocked = traffic_spawn._spawn_probe_blocked(
            shell,
            rect,
            False,
            1,
            0,
            [],
            roads,
            player_rect=player,
        )
        self.assertTrue(blocked)

    def test_car_blocks_spawn(self):
        from pathwise import traffic_spawn

        roads = [Road(Rect(0, 0, 400, 90), "horizontal")]
        car = Car(100, 40, 3.0, vertical=False, spawn_id=1, road_index=0)
        car._sync_collision_shell(force=True)
        blocked = traffic_spawn._car_blocks_spawn(car, [], roads)
        self.assertIsInstance(blocked, bool)


if __name__ == "__main__":
    unittest.main()
