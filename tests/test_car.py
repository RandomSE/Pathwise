"""Unit tests for pathwise.car (extracted vehicle module)."""

import unittest

from pathwise.car import (
    Car,
    CarSpatialIndex,
    _build_lane_buckets,
    _lane_peers_for,
    _resolve_all_shell_overlaps,
    set_intersection_zones_shell,
    set_traffic_map_seed,
)
from pathwise.geom import Rect


class TestCarModule(unittest.TestCase):
    def test_collision_shell_sync_idempotent(self):
        car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
        car._sync_collision_shell(force=True)
        shell = car._collision_shell
        car._sync_collision_shell()
        self.assertIs(car._collision_shell, shell)

    def test_spatial_index_nearby_dedupes(self):
        idx = CarSpatialIndex(cell_size=64)
        car = Car(10, 10, 2.0, vertical=False, spawn_id=1)
        car._sync_collision_shell(force=True)
        idx.rebuild([car])
        scratch: list = []
        peers = idx.nearby(car.rect, 32, scratch)
        self.assertEqual(len(peers), 1)

    def test_lane_buckets_group_same_lane(self):
        a = Car(100, 100, 2.0, vertical=False, spawn_id=1)
        b = Car(130, 100, 2.0, vertical=False, spawn_id=2)
        buckets = _build_lane_buckets([a, b])
        scratch: list = []
        peers = _lane_peers_for(a, buckets, scratch)
        self.assertIn(b, peers)

    def test_shell_separation_noop_when_disabled(self):
        from pathwise import sim_constants

        prev = sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE
        sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE = False
        try:
            car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
            car._sync_collision_shell(force=True)
            before = car.rect.topleft
            _resolve_all_shell_overlaps([car])
            self.assertEqual(car.rect.topleft, before)
        finally:
            sim_constants.ENABLE_CAR_CAR_SOFT_AVOIDANCE = prev

    def test_intersection_shell_runtime_binding(self):
        zone = Rect(0, 0, 200, 200)
        set_intersection_zones_shell([zone])
        car = Car(50, 50, 1.0, vertical=False, spawn_id=3)
        car._sync_collision_shell(force=True)
        from pathwise.sim_constants import INTERSECTION_SHELL_PAD

        self.assertTrue(
            car._shell_overlaps_intersection([zone], pad=INTERSECTION_SHELL_PAD)
        )

    def test_traffic_map_seed_affects_turn_rng(self):
        set_traffic_map_seed(42)
        car = Car(200, 200, 3.0, vertical=True, spawn_id=7, road_index=0)
        car._sync_collision_shell(force=True)
        set_traffic_map_seed(99)
        car2 = Car(200, 200, 3.0, vertical=True, spawn_id=7, road_index=0)
        car2._sync_collision_shell(force=True)
        self.assertIsNotNone(car.spawn_id)
        self.assertIsNotNone(car2.spawn_id)

    def test_approaching_gate_true_near_entry_false_when_far(self):
        from pathwise.sim_constants import IX_QUERY_PAD

        zone = Rect(400, 100, 80, 80)
        car = Car(0, 120, 3.0, vertical=False, spawn_id=8)
        car.direction = 1
        car.rect.centery = zone.centery
        car.rect.right = zone.left - 10
        self.assertTrue(car._approaching_or_in_intersection([zone]))
        car.rect.right = zone.left - IX_QUERY_PAD - car.rect.width - 20
        self.assertFalse(car._approaching_or_in_intersection([zone]))


if __name__ == "__main__":
    unittest.main()
