"""Final coverage gaps: analytics, map_generation, pathwise misc."""

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect
from pathwise.input_keys import KeyState


class TestReplayInterpolationBinarySearch(unittest.TestCase):
    def test_many_keyframe_binary_search(self):
        from analytics.replay_interpolation import frame_at_time

        frames = [{"t": float(i), "player": {"x": i, "y": 0}, "cars": [], "lights": []} for i in range(20)]
        mid = frame_at_time(frames, 9.5)
        self.assertIn("player", mid)


class TestArchetypeScoringBranches(unittest.TestCase):
    def test_role_scores(self):
        from analytics.archetype_scoring import score_session

        base = {
            "outcome": "collision",
            "duration_s": 40,
            "time_limit": 30,
            "crossings": 0,
            "risk_events": 8,
            "collisions": 2,
            "decision_marks": [{"action": "risk_event", "risk": "near_miss"}] * 3,
            "summary": {"total_hesitation_s": 12, "hesitation_count": 4, "total_backtracks": 5},
        }
        scores = score_session(base)
        self.assertGreater(len(scores), 0)


class TestFrameRecorderEdgeCases(unittest.TestCase):
    def test_queue_ignored_action_and_trim(self):
        from analytics.frame_recorder import FrameRecorder

        rec = FrameRecorder(28)
        rec.queue_decision("not_a_real_action")
        player = Rect(0, 0, 20, 20)
        states = [
            {
                "crosswalk": Rect(0, 0, 40, 12),
                "direction": "horizontal",
                "light_state": "green",
                "turn_light_state": "red",
                "seconds_to_change": 1.0,
                "turn_seconds_to_change": 1.0,
                "next_light": "yellow",
                "next_turn_light": "red",
            }
        ]
        for i in range(500):
            rec.capture(float(i) * 0.05, player, [], states, force=(i % 50 == 0))


class TestPerfProfilerBranches(unittest.TestCase):
    def test_disabled_and_sections(self):
        import os
        from analytics.perf_profiler import PerfProfiler, perf_profile_enabled

        saved = os.environ.pop("PATHWISE_PERF_PROFILE", None)
        try:
            self.assertFalse(perf_profile_enabled())
        finally:
            if saved:
                os.environ["PATHWISE_PERF_PROFILE"] = saved
        p = PerfProfiler(enabled=False)
        with p.section("noop"):
            pass


class TestPathfindingAndNoise(unittest.TestCase):
    def test_pathfinding_edges(self):
        from map_generation.pathfinding import Cell, astar_travel_time, bfs_solvable, walk_cell_cost_s

        self.assertGreater(walk_cell_cost_s(60), 0)
        self.assertTrue(bfs_solvable(Cell(0, 0), Cell(2, 2), 5, 5))
        astar_travel_time(Cell(0, 0), Cell(2, 2), 5, 5, stride_px=60.0, crossing_wait_s=1.0)

    def test_noise_edges(self):
        from map_generation.noise import fbm, simplex2

        self.assertIsInstance(simplex2(1.0, 2.0, seed=3), float)
        self.assertIsInstance(fbm(1.0, 2.0, seed=3), float)


class TestGeneratorBranches(unittest.TestCase):
    def test_adaptive_and_layout_variants(self):
        from map_generation.difficulty import adaptive_difficulty
        from map_generation.generator import ProceduralMap, generate_map, generate_map_layout

        layout = generate_map_layout(1, difficulty=DifficultyProfile.default())
        pmap = generate_map(1, difficulty=DifficultyProfile.for_menu_preset("easy"))
        self.assertIsInstance(pmap, ProceduralMap)
        self.assertIn("roads", layout)
        adaptive_difficulty({"outcome": "success", "duration_s": 5, "time_limit": 30})


class TestGameDrawGaps(unittest.TestCase):
    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw._entity_batch.draw_entities")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    def test_traffic_light_timer_colors(self, *_mocks):
        from pathwise.game_draw import draw_traffic_light_overlays

        crosswalk = Rect(100, 200, 14, 90)
        states = [
            {
                "road_rect": crosswalk.inflate(40, 40),
                "direction": "vertical",
                "crosswalk": crosswalk,
                "sign_rect": Rect(80, 180, 18, 18),
                "light_state": "yellow",
                "seconds_to_change": 3.5,
                "next_light": "red",
                "turn_light_state": "green",
                "turn_seconds_to_change": 2.0,
                "next_turn_light": "red",
            },
            {
                "road_rect": Rect(80, 300, 120, 40),
                "direction": "horizontal",
                "crosswalk": Rect(80, 300, 120, 14),
                "sign_rect": Rect(70, 290, 18, 18),
                "light_state": "green",
                "seconds_to_change": 5.0,
                "next_light": "yellow",
                "turn_light_state": "red",
                "turn_seconds_to_change": 1.0,
                "next_turn_light": "green",
            },
        ]
        draw_traffic_light_overlays(
            600, states, (0, 0), light_green_duration=9.0, view_rect=Rect(0, 0, 800, 600), draw_timer_bar=True
        )


class TestPathwiseWindowGameplay(unittest.TestCase):
    def test_gameplay_view_empty_draw(self):
        from tests.arcade_harness import fake_arcade_window
        from pathwise.pathwise_window import GamePlayView

        with patch("arcade.get_window", return_value=fake_arcade_window()):
            view = GamePlayView()
            view.window = MagicMock(width=800, height=600)
            view.clear = MagicMock()
            view._draw_state = None
            view.on_draw()


class TestSpectateRoundAutopilotOff(unittest.TestCase):
    def test_autopilot_false_branch(self):
        import main as game
        from analytics.spectate_round import autopilot_keys, run_spectate_round

        game.session_base_seed = 42
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        game.player.rect.centerx = game.current_map.goal_rect.centerx - 100
        game.player.rect.centery = game.current_map.goal_rect.centery
        keys = autopilot_keys(game)
        self.assertTrue(keys.pressed("right") or keys.pressed("left"))
        with tempfile.TemporaryDirectory() as tmp:
            result = run_spectate_round(
                seed=42,
                autopilot=False,
                output_dir=tmp,
                max_frames=120,
            )
            self.assertGreater(result.sim_frames, 0)


class TestDashboardLegacyEntry(unittest.TestCase):
    def test_legacy_entry_dict(self):
        from analytics.dashboard import build_dashboard_html

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(
                {
                    "duration_s": 3,
                    "outcome": "success",
                    "round_index": 1,
                    "replay_frames": [],
                    "decision_marks": [],
                },
                f,
            )
            path = f.name
        build_dashboard_html(path)


class TestMainCarUpdateLoop(unittest.TestCase):
    def test_every_car_update_called(self):
        import main as game

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("hard")
        game.start_round(1, profile, "hard")
        for _ in range(500):
            game.update_round_frame(KeyState())
        car_list = game.cars.sprites()
        if not car_list:
            self.skipTest("no cars spawned")
        car = car_list[0]
        game._frame_car_spatial.rebuild(car_list)
        peers = game._frame_car_spatial.nearby(car._collision_shell, 200, [])
        lane = []
        game._lane_peers_for(car, game._build_lane_buckets(car_list), lane)
        car.update(
            game.road_states,
            game.world_bounds,
            game.intersection_zones,
            game.player.rect,
            game.current_map.roads,
            lane,
            peers,
            frame_index=game.round_frame,
            player_on_road=True,
            honk_allowed=True,
            game_time=1.0,
        )


if __name__ == "__main__":
    unittest.main()
