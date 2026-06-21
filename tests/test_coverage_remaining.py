"""Additional coverage for map_generation, analytics, and pathwise gaps."""

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pathwise.geom import Rect
from pathwise.map import Road


class TestIntersectionRouting(unittest.TestCase):
    def test_routing_helpers(self):
        from map_generation.intersection_routing import (
            drive_from_vector,
            left_vector,
            travel_vector,
        )
        vec = travel_vector(True, 1)
        self.assertEqual(len(vec), 2)
        lv = left_vector(False, 1)
        self.assertEqual(len(lv), 2)
        vertical, direction = drive_from_vector(0, 1)
        self.assertTrue(vertical)
        self.assertEqual(direction, 1)


class TestMapGenerator(unittest.TestCase):
    def test_generator_edge_seeds(self):
        from map_generation.difficulty import DifficultyProfile
        from map_generation.generator import generate_map_layout

        for seed in (0, 1, 99, 9999):
            layout = generate_map_layout(seed, difficulty=DifficultyProfile.for_menu_preset("hard"))
            self.assertGreaterEqual(len(layout["roads"]), 12)


class TestSpectateAnalyzerExtended(unittest.TestCase):
    def test_stall_and_frozen_detectors(self):
        import main as game
        from analytics.spectate_analyzer import SpectateTracker

        tracker = SpectateTracker()
        car = game.Car(100, 100, 0.0, vertical=False, spawn_id=1)
        car.current_speed = 0.0
        car._stopped_frames = 400
        car._sync_collision_shell(force=True)
        emitted = tracker.observe(
            frame=1,
            sim_t=1.0,
            cars=[car],
            intersection_zones=[],
        )
        self.assertIsInstance(emitted, list)


class TestTrafficScheduleLanes(unittest.TestCase):
    def test_narrow_road_along_coord(self):
        from map_generation.difficulty import DifficultyProfile
        from map_generation.traffic_schedule import (
            _along_coord,
            build_intersection_rects,
            generate_traffic_schedule,
            pose_overlaps_intersection_rects,
        )

        narrow = Road(Rect(0, 0, 30, 200), "vertical")
        coord = _along_coord(narrow, 0.5)
        self.assertIsInstance(coord, int)
        h = Road(Rect(0, 100, 400, 60), "horizontal")
        roads = [narrow, h]
        ix = build_intersection_rects(roads)
        self.assertFalse(pose_overlaps_intersection_rects(500, 500, False, ix))
        sched = generate_traffic_schedule(7, roads, [1.0, 1.0], DifficultyProfile.default(), 60, fps=60)
        self.assertGreater(len(sched), 0)


class TestSpritesPedestrian(unittest.TestCase):
    def test_pedestrian_and_body_hitbox(self):
        from pathwise.sprites import make_pedestrian_surface, player_body_hitbox

        ped = make_pedestrian_surface(28)
        self.assertGreater(ped.width, 0)
        body = player_body_hitbox(Rect(0, 0, 20, 20))
        self.assertGreater(body.width, 0)


class TestTrafficSignalLayout(unittest.TestCase):
    def test_approach_sign_rects(self):
        from pathwise.traffic_signal_layout import (
            APPROACH_EAST,
            APPROACH_NORTH,
            APPROACH_SOUTH,
            APPROACH_WEST,
            approach_sign_rect,
            bulb_positions,
            housing_as_list,
            traffic_housing_rect,
            turn_bulb_position,
        )

        cw = Rect(100, 100, 14, 80)
        housing = traffic_housing_rect(cw, "vertical", APPROACH_WEST)
        sign = approach_sign_rect(housing, "vertical", APPROACH_WEST)
        self.assertGreater(sign.width, 0)
        bulbs = bulb_positions(housing, "vertical", APPROACH_WEST)
        self.assertEqual(len(bulbs), 3)
        hcw = Rect(200, 200, 80, 14)
        hh = traffic_housing_rect(hcw, "horizontal", APPROACH_NORTH)
        turn = turn_bulb_position(hh, "horizontal", APPROACH_SOUTH)
        self.assertEqual(len(turn), 2)
        self.assertEqual(len(housing_as_list(housing)), 4)
        traffic_housing_rect(cw, "vertical", APPROACH_EAST)
        traffic_housing_rect(hcw, "horizontal", APPROACH_SOUTH)


class TestDashboardLegacyRoundView(unittest.TestCase):
    def test_round_view_plain_session(self):
        from analytics.dashboard import build_dashboard_html

        payload = {
            "round": 2,
            "outcome": "timeout",
            "session": {
                "duration_s": 3,
                "outcome": "timeout",
                "round_index": 2,
                "replay_frames": [],
                "decision_marks": [{"action": "commit", "t": 1}],
                "risk_marks": [],
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"rounds": [payload]}, f)
            path = f.name
        out = build_dashboard_html(path)
        self.assertTrue(out)


class TestEntityDrawBatch(unittest.TestCase):
    def test_draw_entities_empty_list(self):
        from pathwise.entity_draw_batch import EntityDrawBatch

        batch = EntityDrawBatch()
        batch.draw_entities([], 600, (0, 0))


if __name__ == "__main__":
    unittest.main()
