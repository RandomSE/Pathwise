"""Direct Car and main helper unit tests for uncovered branches."""

import unittest
from unittest.mock import MagicMock, patch

from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect, rects_overlap
from pathwise.input_keys import KEY_RIGHT, KeyState


class TestMainCarUnit(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []

    def _started(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        return profile

    def test_player_hits_car_spatial_miss(self):
        self._started()
        player = self.game.player
        spatial = self.game.CarSpatialIndex()
        car = self.game.Car(5000, 5000, 3.0, vertical=False, spawn_id=1)
        car._sync_collision_shell(force=True)
        spatial.rebuild([car])
        scratch = []
        self.assertFalse(
            self.game.player_hits_any_car(player, self.game.cars, spatial=spatial, scratch=scratch)
        )

    def test_spatial_index_stamp_rollover(self):
        idx = self.game.CarSpatialIndex()
        idx._stamp = 1_000_000_001
        car = self.game.Car(10, 10, 2.0, vertical=False, spawn_id=1)
        idx.rebuild([car])
        scratch = []
        idx.nearby(car.rect, 10, scratch)

    def test_offscreen_stride_update(self):
        self._started()
        car = self.game.Car(-5000, -5000, 4.0, vertical=False, spawn_id=7)
        car._sync_collision_shell(force=True)
        self.game.cars.add(car)
        self.game.round_frame = 1
        self.game.update_round_frame(KeyState())

    def test_player_clamped_to_world_bounds(self):
        self._started()
        self.game.player.rect.topleft = (-99999, -99999)
        self.game.update_round_frame(KeyState())

    def test_soft_overlap_creep_cap_branches(self):
        car = self.game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        blocker = self.game.Car(130, 100, 0.0, vertical=False, spawn_id=2)
        car._sync_collision_shell(force=True)
        blocker._sync_collision_shell(force=True)
        next_rect = car.rect.move(5, 0)
        cap = car._soft_overlap_creep_cap(next_rect, [blocker], [blocker], [])
        self.assertIsNotNone(cap)

    def test_save_session_log_empty(self):
        self.game.round_results = []
        self.assertIsNone(self.game.save_session_log())

    def test_spawn_car_from_event_integration(self):
        self._started()
        if not self.game.traffic_schedule:
            self.skipTest("no traffic schedule")
        event = self.game.traffic_schedule[0]
        scratch = []
        ok = self.game._spawn_car_from_event(
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
        )
        self.assertIsInstance(ok, bool)

    def test_lane_center_and_road_state_lookup(self):
        self._started()
        car = self.game.Car(50, 50, 2.0, vertical=False, spawn_id=1, road_index=0)
        road = self.game.current_map.roads[0]
        self.game.lane_center_for_road(road, 1, car.vertical)
        self.game._road_states_for_car(car, self.game.road_states)
        car.road_index = 9999
        self.game._road_states_for_car(car, self.game.road_states)

    def test_build_road_states_by_index(self):
        self._started()
        by_idx = self.game._build_road_states_by_index(self.game.road_states, len(self.game.current_map.roads))
        self.assertEqual(len(by_idx), len(self.game.current_map.roads))

    @patch("pathwise.game_draw.draw_round_scene")
    def test_draw_round_frame_path(self, _draw):
        self._started()
        state = self.game.update_round_frame(KeyState())
        self.game.draw_round_frame(600, state)


class TestSpritesHonk(unittest.TestCase):
    @patch("pathwise.sprites.arcade.draw_arc_outline")
    @patch("pathwise.sprites.arcade.draw_lbwh_rectangle_outline")
    @patch("pathwise.sprites.arcade.draw_lbwh_rectangle_filled")
    @patch("pathwise.sprites.arcade.Text")
    def test_draw_honk_bubble(self, text_cls, *_mocks):
        from pathwise.sprites import draw_honk_bubble

        label = MagicMock()
        label.content_width = 40
        label.content_height = 16
        text_cls.return_value = label
        draw_honk_bubble(600, Rect(100, 100, 60, 30), (0, 0))
        draw_honk_bubble(600, Rect(100, 100, 60, 30), (0, 0))


class TestDecisionLoggerHesitation(unittest.TestCase):
    def test_hesitation_and_backtrack(self):
        import time
        from analytics.decision_logger import DecisionLogger

        logger = DecisionLogger((0, 0), (500, 500), "m", 3)
        logger.update((0, 0), [], False, False, "red", False)
        time.sleep(0.5)
        logger.update((0, 0), ["left"], False, True, "green", False)
        logger.update((-20, 0), [], True, True, "green", False)
        logger.finalize("success", 2.0, 1, 0, 0, "none")


if __name__ == "__main__":
    unittest.main()
