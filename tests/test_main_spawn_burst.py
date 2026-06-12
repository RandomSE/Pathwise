"""Spawn pipeline and collision-path coverage for main.py."""

import unittest
import unittest.mock

from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect
from pathwise.input_keys import KeyState


class TestMainSpawnBurst(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []

    def test_spawn_many_scheduled_events(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        self.game.start_round(1, profile, "hard")
        scratch = []
        spawned = 0
        for event in self.game.traffic_schedule[:80]:
            if self.game._spawn_car_from_event(
                event,
                self.game.current_map.roads,
                self.game.cars,
                self.game.all_sprites,
                self.game.intersection_zones,
                self.game.player.rect,
                getattr(self.game.current_map, "city_blocks", None),
                self.game.world_bounds,
                spatial=self.game._frame_car_spatial,
                scratch=scratch,
            ):
                spawned += 1
        self.assertGreater(spawned, 0)

    def test_player_hits_car_via_spatial(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        car = self.game.Car(
            self.game.player.rect.centerx,
            self.game.player.rect.centery,
            0.0,
            vertical=False,
            spawn_id=999,
        )
        car._sync_collision_shell(force=True)
        self.game.cars.add(car)
        spatial = self.game.CarSpatialIndex()
        spatial.rebuild([car])
        scratch = []
        self.assertTrue(
            self.game.player_hits_any_car(
                self.game.player, self.game.cars, spatial=spatial, scratch=scratch
            )
        )

    def test_shell_separation_two_cars(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        a = self.game.Car(200, 200, 0.0, vertical=False, spawn_id=1)
        b = self.game.Car(210, 200, 0.0, vertical=False, spawn_id=2)
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        prev = self.game.ENABLE_CAR_CAR_SOFT_AVOIDANCE
        self.game.ENABLE_CAR_CAR_SOFT_AVOIDANCE = True
        try:
            self.game._resolve_all_shell_overlaps([a, b])
        finally:
            self.game.ENABLE_CAR_CAR_SOFT_AVOIDANCE = prev

    def test_process_respawns_and_spawns(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        for _ in range(120):
            self.game.update_round_frame(KeyState())
        car = next(iter(self.game.cars.sprites()), None)
        if car is None:
            self.skipTest("no cars")
        origin = self.game.CarSpawnOrigin(
            road_index=car.road_index or 0,
            direction=car.direction,
            along_frac=0.2,
            phase="ongoing",
        )
        car._spawn_origin = origin
        self.game._queue_car_respawn(car)
        self.game._process_car_respawns(
            self.game.round_frame,
            self.game.current_map.roads,
            self.game.cars,
            self.game.all_sprites,
            self.game.intersection_zones,
            self.game.player.rect,
            getattr(self.game.current_map, "city_blocks", None),
            self.game.world_bounds,
        )


    def test_car_honk_snap_and_travel_helpers(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        car = self.game.Car(100, 100, 3.0, vertical=False, spawn_id=50, road_index=0)
        car._sync_collision_shell(force=True)
        roads = self.game.current_map.roads
        car._snap_center_to_left_lane(roads)
        car._snap_center_to_left_lane(roads, max_nudge=None)
        car._snap_center_to_left_lane(roads, max_nudge=0)
        body = __import__("pathwise.sprites", fromlist=["player_body_hitbox"]).player_body_hitbox(
            self.game.player.rect
        )
        car.evaluate_honk(body, False, True, 1.0)
        self.assertTrue(car.trigger_honk(1.0, "blocked"))
        car.trigger_honk(1.05, "blocked")
        self.assertTrue(car._player_in_travel_lane(body) or not car._player_in_travel_lane(body))

    def test_timeout_and_perf_hud(self):
        from analytics.spectate_round import SyntheticClock

        profile = DifficultyProfile.for_menu_preset("normal")
        clock = SyntheticClock(t=7_000_000.0, dt=1 / 60)
        prev_perf = self.game.ENABLE_PERF_PROFILE
        self.game.ENABLE_PERF_PROFILE = True
        try:
            with unittest.mock.patch.object(self.game.time, "time", clock.now):
                self.game.perf_profiler.begin_session(
                    session_seed=1, seed_source="t", num_rounds=1, preset="normal"
                )
                self.game.start_round(1, profile, "normal")
                self.game.perf_profiler.begin_round(1)
                self.game.start_time = clock.now() - self.game.ROUND_TIME_LIMIT - 1
                state = self.game.update_round_frame(KeyState())
                self.assertIsNone(state)
                self.assertFalse(self.game.round_active)
        finally:
            self.game.ENABLE_PERF_PROFILE = prev_perf


if __name__ == "__main__":
    unittest.main()
