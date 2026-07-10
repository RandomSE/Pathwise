"""Direct unit tests for pathwise.round_session."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect
from pathwise.round_session import (
    _load_prior_session,
    _map_seed_for_round,
    _perf_counter_snapshot,
    build_world_bounds,
    end_round,
    finalize_round_result,
    record_risk,
    sync_spawn_state_from_runtime,
)


class TestRoundSession(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 4242
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.round_active = False
        game.round_results = []

    def test_map_seed_for_round_is_stable(self):
        self.assertEqual(_map_seed_for_round(100, 0), 100)
        self.assertEqual(_map_seed_for_round(100, 2), (100 + 2 * 9973) & 0x7FFFFFFF)

    def test_load_prior_session_reads_logs_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("logs.json").write_text(
                    json.dumps({"session": {"outcome": "success", "crossings": 3}}),
                    encoding="utf-8",
                )
                data = _load_prior_session()
            finally:
                os.chdir(cwd)
        self.assertEqual(data["outcome"], "success")
        self.assertEqual(data["crossings"], 3)

    def test_build_world_bounds_includes_start_and_goal(self):
        road = MagicMock()
        road.rect = Rect(100, 200, 300, 80)
        road.direction = "horizontal"
        bounds = build_world_bounds([road], (50, 250), Rect(400, 220, 40, 40))
        self.assertLessEqual(bounds.left, 50 - 80 - 120)
        self.assertGreaterEqual(bounds.right, 400 + 40 + 120)

    def test_end_round_inactive_returns_failure_reason(self):
        self.game.round_active = False
        self.game.failure_reason = "timeout"
        self.assertEqual(end_round(collided=False), "timeout")

    def test_end_round_defers_heavy_finalize(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.assertTrue(self.game.round_active)
        outcome = end_round(collided=False, timed_out=True)
        self.assertEqual(outcome, "timeout")
        self.assertFalse(self.game.round_active)
        last = self.game.round_results[-1]
        self.assertTrue(last.get("_pending_finalize"))
        self.assertIsNone(last["session"])
        finalize_round_result()
        self.assertIsNotNone(last["session"])
        self.assertNotIn("_pending_finalize", last)

    def test_end_round_finalizes_car_diagnostics_immediately(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        with patch("pathwise.round_session.car_diagnostics") as diag:
            end_round(collided=False, timed_out=True)
            diag.end_round.assert_called_once()
        self.assertTrue(self.game.round_results[-1].get("_pending_finalize"))

    def test_record_risk_respects_cooldown(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.game.last_risk_time = 0
        record_risk("test-risk", tier="risky")
        self.assertEqual(self.game.risk_events, 1)
        before = self.game.last_risk_time
        record_risk("test-risk-again", tier="risky")
        self.assertEqual(self.game.risk_events, 1)
        self.assertEqual(self.game.last_risk_time, before)

    def test_sync_spawn_state_from_runtime_mirrors_module(self):
        from pathwise import traffic_spawn

        traffic_spawn.traffic_schedule = [MagicMock()]
        traffic_spawn.traffic_spawn_cursor = 7
        traffic_spawn.traffic_spawn_retry = [MagicMock()]
        traffic_spawn.traffic_respawn_pending = []
        traffic_spawn.traffic_respawn_event_id = 9000
        sync_spawn_state_from_runtime()
        self.assertIs(self.game.traffic_schedule, traffic_spawn.traffic_schedule)
        self.assertEqual(self.game.traffic_spawn_cursor, 7)
        self.assertEqual(self.game.traffic_respawn_event_id, 9000)

    def test_perf_counter_snapshot_shape(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        snap = _perf_counter_snapshot(car_list=[], replay_cars=[], draw_sprites=[])
        self.assertIn("cars_alive", snap)
        self.assertIn("road_states", snap)
        self.assertGreater(snap["road_states"], 0)

    def test_start_round_resets_intersection_rect_cache(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game._ix_rects_cache = object()
        self.game._ix_rects_cache_frame = 99
        self.game.start_round(1, profile, "normal")
        self.assertIsNone(self.game._ix_rects_cache)
        self.assertEqual(self.game._ix_rects_cache_frame, -1)


if __name__ == "__main__":
    unittest.main()
