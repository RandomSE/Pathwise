"""Coverage for small main.py helpers not hit by integration tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pathwise.geom import Rect
from pathwise.input_keys import KeyState


class TestMainHelpers(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game

    def test_player_crosswalk_helpers(self):
        body = Rect(10, 10, 20, 20)
        states = [
            {
                "crosswalk": Rect(0, 0, 100, 100),
                "light_state": "red",
            }
        ]
        self.assertTrue(self.game.player_on_car_red_crosswalk_body(body, states))
        self.assertTrue(self.game.player_mostly_on_legal_crosswalk(body, states))
        empty = Rect(0, 0, 0, 0)
        self.assertFalse(self.game.player_mostly_on_legal_crosswalk(empty, states))

    def test_player_hits_car_spatial_and_group(self):
        import main as game

        player = MagicMock()
        player.rect = Rect(0, 0, 20, 20)
        car = MagicMock()
        car._collision_shell = Rect(0, 0, 30, 30)
        car.alive = lambda: True
        group = game.EntityGroup(car)
        self.assertTrue(game.player_hits_any_car(player, group))
        spatial = game.CarSpatialIndex()
        spatial.rebuild([car])
        scratch = []
        self.assertTrue(game.player_hits_any_car(player, group, spatial=spatial, scratch=scratch))

    def test_view_and_replay_car_selection(self):
        import main as game

        cars = []
        for i in range(5):
            c = game.Car(100 + i * 10, 100, 3.0, vertical=False, spawn_id=i)
            cars.append(c)
        view = game._view_rect_for_camera((0, 0))
        self.assertIsInstance(view, Rect)
        replay_view = game._replay_view_rect_for_camera((0, 0))
        self.assertGreater(replay_view.width, view.width)
        in_view = game._cars_in_view(cars, Rect(-9999, -9999, 20000, 20000))
        self.assertEqual(len(in_view), 5)
        capped = game._cap_cars_near_player(
            cars, Rect(-9999, -9999, 20000, 20000), (100, 100), max_cars=2
        )
        self.assertEqual(len(capped), 2)
        replay = game._cars_for_replay(cars * 10, (100, 100))
        self.assertLessEqual(len(replay), game.REPLAY_MAX_CARS)

    def test_cars_should_respect_player(self):
        import main as game

        self.assertTrue(game.cars_should_respect_player(True, False, False))
        self.assertFalse(game.cars_should_respect_player(False, False, True))

    def test_is_car_approaching_player(self):
        import main as game

        player_rect = Rect(100, 100, 20, 20)
        car = game.Car(100, 40, 3.0, vertical=True, spawn_id=1)
        car.direction = 1
        car.current_speed = 3.0
        self.assertTrue(game.is_car_approaching_player(car, player_rect))
        car.rect.y = 500
        self.assertFalse(game.is_car_approaching_player(car, player_rect))

    def test_serialize_lights_and_lane_buckets(self):
        import main as game

        car = game.Car(50, 50, 2.0, vertical=False, spawn_id=1)
        buckets = game._build_lane_buckets([car])
        peers = []
        game._lane_peers_for(car, buckets, peers)
        self.assertIn(car, peers)

    def test_car_spatial_index_rebuild_and_gather(self):
        import main as game

        idx = game.CarSpatialIndex()
        car = game.Car(100, 100, 2.0, vertical=False, spawn_id=1)
        idx.rebuild([car])
        scratch = []
        nearby = idx.nearby(car.rect, 50, scratch)
        self.assertIn(car, nearby)
        idx.clear()
        car.kill()
        idx.relocate_car(car)

    def test_resolve_shell_overlaps_disabled(self):
        import main as game

        prev = game.ENABLE_CAR_CAR_SOFT_AVOIDANCE
        game.ENABLE_CAR_CAR_SOFT_AVOIDANCE = False
        try:
            game._resolve_all_shell_overlaps([])
        finally:
            game.ENABLE_CAR_CAR_SOFT_AVOIDANCE = prev

    def test_record_risk_and_save_session(self):
        import main as game

        with tempfile.TemporaryDirectory() as tmp:
            orig_cwd = Path.cwd()
            try:
                import os

                os.chdir(tmp)
                game.round_results = [
                    {
                        "duration_s": 5,
                        "crossings": 1,
                        "collisions": 0,
                        "risk_events": 0,
                        "outcome": "success",
                        "session": {"failure_reason": "none", "map_layout": {"roads": [1, 2]}},
                        "archetypes": {},
                    }
                ]
                game.session_num_rounds = 1
                game.session_base_seed = 9
                game.session_seed_source = "test"
                game.session_use_adaptive_map = False
                game.base_preset_id = "normal"
                game.decision_logger = MagicMock()
                game.last_risk_time = 0
                game.record_risk("test", cooldown=0)
                self.assertGreaterEqual(game.risk_events, 1)
                with patch("main.build_dashboard_html", return_value="dash.html"):
                    path = game.save_session_log()
                self.assertEqual(path, "dash.html")
                self.assertTrue(Path("logs.json").is_file())
            finally:
                os.chdir(orig_cwd)

    def test_load_prior_session_and_map_seed(self):
        import main as game

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"session_seed": 1}, f)
            path = f.name
        with patch("main.os.path.isfile", return_value=True), patch(
            "builtins.open", unittest.mock.mock_open(read_data='{"session_seed": 1}')
        ):
            data = game._load_prior_session()
        self.assertIsNotNone(data)
        seed = game._map_seed_for_round(100, 2)
        self.assertIsInstance(seed, int)

    def test_pedestrian_entity(self):
        import main as game

        from pathwise.input_keys import KEY_RIGHT, KeyState

        ped = game.Pedestrian((100, 100))
        keys = KeyState()
        keys.press(KEY_RIGHT)
        before = ped.rect.x
        ped.update(keys)
        self.assertGreater(ped.rect.x, before)
        self.assertTrue(ped.alive())

    def test_get_pressed_keys(self):
        import main as game

        keys = KeyState()
        keys.press("left")
        pressed = game.get_pressed_keys(keys)
        self.assertIn("left", pressed)


if __name__ == "__main__":
    unittest.main()
