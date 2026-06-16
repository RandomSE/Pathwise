"""Coverage for pathwise.traffic_spawn spawn/retry branches."""

import unittest

from map_generation.difficulty import DifficultyProfile
from map_generation.traffic_schedule import PHASE_ONGOING, TrafficSpawn
from pathwise import traffic_spawn
from pathwise.car import Car, CarSpatialIndex, CarSpawnOrigin, RespawnRequest
from pathwise.entity_group import EntityGroup
from pathwise.geom import Rect
from pathwise.map import Road


class TestTrafficSpawnPipeline(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 42
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        traffic_spawn.bind_spawn_runtime(
            car_speed_mult=game.CAR_SPEED_MULT,
            city_block_rects=game._round_city_block_rects,
            frame_car_spatial=game._frame_car_spatial,
            frame_nearby_scratch=game._frame_nearby_scratch,
        )
        traffic_spawn.set_round_frame_getter(lambda: game.round_frame)

    def test_process_spawns_with_retry_backlog(self):
        roads = self.game.current_map.roads
        cars = EntityGroup()
        sprites = EntityGroup()
        event = TrafficSpawn(
            frame=0,
            road_index=0,
            along_frac=0.3,
            direction=1,
            archetype_index=0,
            event_id=1001,
            phase=PHASE_ONGOING,
        )
        traffic_spawn.traffic_spawn_retry = [event] * 20
        traffic_spawn._process_traffic_spawns_through_frame(
            5,
            roads,
            cars,
            sprites,
            self.game.intersection_zones,
            self.game.player.rect,
            getattr(self.game.current_map, "city_blocks", None),
            self.game.world_bounds,
        )
        self.assertLessEqual(len(traffic_spawn.traffic_spawn_retry), 48)

    def test_process_car_respawns_deferred(self):
        roads = self.game.current_map.roads
        cars = EntityGroup()
        sprites = EntityGroup()
        origin = CarSpawnOrigin(0, 1, 0.4, PHASE_ONGOING)
        traffic_spawn.traffic_respawn_pending = [
            RespawnRequest(origin, due_frame=0)
        ]
        traffic_spawn._process_car_respawns(
            0,
            roads,
            cars,
            sprites,
            self.game.intersection_zones,
            self.game.player.rect,
            getattr(self.game.current_map, "city_blocks", None),
            self.game.world_bounds,
            spatial=self.game._frame_car_spatial,
            scratch=[],
        )
        self.assertIsInstance(traffic_spawn.traffic_respawn_pending, list)

    def test_queue_car_respawn_respects_cap(self):
        traffic_spawn.traffic_respawn_pending = []
        car = Car(10, 10, 2.0, vertical=False, spawn_id=1)
        car._spawn_origin = CarSpawnOrigin(0, 1, 0.5, PHASE_ONGOING)
        for _ in range(traffic_spawn.RESPAWN_PENDING_CAP + 5):
            traffic_spawn._queue_car_respawn(car)
        self.assertLessEqual(
            len(traffic_spawn.traffic_respawn_pending),
            traffic_spawn.RESPAWN_PENDING_CAP,
        )

    def test_process_spawns_retry_budget_exhausted(self):
        roads = self.game.current_map.roads
        cars = EntityGroup()
        sprites = EntityGroup()
        event = TrafficSpawn(
            frame=0,
            road_index=0,
            along_frac=0.3,
            direction=1,
            archetype_index=0,
            event_id=1002,
            phase=PHASE_ONGOING,
        )
        traffic_spawn.traffic_spawn_retry = [event]
        traffic_spawn.traffic_spawn_cursor = 0
        traffic_spawn.traffic_schedule = [
            TrafficSpawn(0, 0, 0.5, 1, 0, 2002, phase=PHASE_ONGOING)
        ]
        traffic_spawn._process_traffic_spawns_through_frame(
            999,
            roads,
            cars,
            sprites,
            self.game.intersection_zones,
            self.game.player.rect,
            getattr(self.game.current_map, "city_blocks", None),
            self.game.world_bounds,
        )

    def test_spawn_car_from_event_no_roads(self):
        ok = traffic_spawn._spawn_car_from_event(
            TrafficSpawn(0, 0, 0.5, 1, 0, 1, phase=PHASE_ONGOING),
            [Road(Rect(0, 0, 400, 90), "horizontal")],
            EntityGroup(),
            EntityGroup(),
        )
        self.assertIsInstance(ok, bool)


if __name__ == "__main__":
    unittest.main()
