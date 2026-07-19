"""Route-based round timer and spawn sync regression tests."""

import math
import unittest
from unittest.mock import patch

from map_generation.difficulty import DifficultyProfile
from map_generation.generator import _compute_time_limit, generate_map_layout
from map_generation.pathfinding import Cell, astar_route_estimate, bfs_solvable, sprint_cell_cost_s
from map_generation.safety import expected_wait_for_safe_crossing


class TestRouteTimeLimit(unittest.TestCase):
    def test_compute_time_limit_uses_preset_margin(self):
        self.assertEqual(_compute_time_limit(37.5, 1.10), 42)
        self.assertEqual(_compute_time_limit(27.0, 1.05), 29)

    def test_generated_maps_use_preset_route_margin(self):
        margins = {
            "easy": DifficultyProfile.for_menu_preset("easy").route_time_margin,
            "normal": DifficultyProfile.for_menu_preset("normal").route_time_margin,
            "hard": DifficultyProfile.for_menu_preset("hard").route_time_margin,
        }
        for preset in ("easy", "normal", "hard"):
            margin = margins[preset]
            for seed in (1, 42, 99, 12345):
                layout = generate_map_layout(
                    seed, difficulty=DifficultyProfile.for_menu_preset(preset)
                )
                travel = layout["path_estimate_s"]
                expected = max(28, int(math.ceil(travel * margin)))
                self.assertLessEqual(
                    abs(layout["time_limit"] - expected),
                    1,
                    f"{preset} seed={seed}: limit {layout['time_limit']} vs ~{expected}",
                )

    def test_user_session_seed_normal_timer_is_tight(self):
        from pathwise.round_session import _map_seed_for_round

        map_seed = _map_seed_for_round(891689129, 1)
        profile = DifficultyProfile.for_menu_preset("normal")
        layout = generate_map_layout(map_seed, difficulty=profile)
        self.assertLessEqual(layout["time_limit"], 48)
        self.assertGreaterEqual(layout["time_limit"], 38)

    def test_route_crossings_on_layout_not_total_roads(self):
        layout = generate_map_layout(42, difficulty=DifficultyProfile.for_menu_preset("normal"))
        self.assertIn("route_crossings", layout)
        self.assertLess(layout["route_crossings"], len(layout["roads"]))
        self.assertGreater(layout["route_crossings"], 0)

    def test_astar_route_estimate_counts_path_crossings(self):
        wait = expected_wait_for_safe_crossing(1.0)
        result = astar_route_estimate(Cell(0, 0), Cell(2, 2), 5, 5, wait, 60.0)
        self.assertIsNotNone(result)
        travel_s, crossings = result
        self.assertGreater(travel_s, 0.0)
        self.assertEqual(crossings, 4)
        self.assertTrue(bfs_solvable(Cell(0, 0), Cell(2, 2), 5, 5))

    def test_sprint_route_uses_faster_sidewalk_segments(self):
        from map_generation.pathfinding import walk_cell_cost_s

        self.assertLess(sprint_cell_cost_s(60.0), walk_cell_cost_s(60.0))
        wait = expected_wait_for_safe_crossing(1.0)
        result = astar_route_estimate(Cell(0, 0), Cell(4, 0), 8, 8, wait, 60.0)
        self.assertIsNotNone(result)
        travel_s, _ = result
        self.assertGreater(travel_s, 4 * sprint_cell_cost_s(60.0))


class TestRoundIntroHint(unittest.TestCase):
    def test_round_intro_hint_shows_route_timer(self):
        from pathwise.pre_game import round_intro_hint

        profile = DifficultyProfile.for_menu_preset("normal")
        hint = round_intro_hint(profile, time_limit_s=52, round_index=1)
        self.assertIn("52s route timer", hint)
        self.assertNotIn("180s", hint)


class TestRoundFrameSpawnSync(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 888
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.round_active = False

    @patch("pathwise.round_frame.sync_spawn_state_from_runtime")
    def test_update_round_frame_syncs_spawn_via_round_session(self, sync_spawn):
        from pathwise.input_keys import KeyState
        from pathwise.round_frame import update_round_frame

        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        sync_spawn.reset_mock()
        update_round_frame(KeyState())
        sync_spawn.assert_called_once()

    def test_traffic_spawn_module_has_no_sync_state_to(self):
        from pathwise import traffic_spawn

        self.assertFalse(hasattr(traffic_spawn, "sync_state_to"))


if __name__ == "__main__":
    unittest.main()
