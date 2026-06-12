import json
import os
import tempfile
import unittest
from unittest.mock import patch

from analytics.spectate_analyzer import (
    SpectateTracker,
    TURN_ARC_OVERLAP_FRAMES,
    _overlap_pairs,
    _turn_arc_overlap_pairs,
)
from analytics.spectate_round import SyntheticClock, autopilot_keys, run_spectate_round
from pathwise.geom import Rect, rects_overlap
from pathwise.input_keys import KeyState


SESSION_SEED = 1890416619


class TestSpectateAnalyzer(unittest.TestCase):
    def test_overlap_pairs_detected(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        b = game.Car(118, 100, 3.0, vertical=False, spawn_id=2)
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        pairs = _overlap_pairs([a, b])
        self.assertEqual(pairs, [(1, 2)])

    def test_tracker_emits_overlap_anomaly(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        b = game.Car(118, 100, 3.0, vertical=False, spawn_id=2)
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        tracker = SpectateTracker()
        emitted = tracker.observe(
            frame=10,
            sim_t=0.5,
            cars=[a, b],
            intersection_zones=[],
        )
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].kind, "shell_overlap")

    def test_turn_arc_overlap_pairs_require_arc_phase(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        a._turn_phase = "turning"
        b = game.Car(118, 100, 3.0, vertical=False, spawn_id=2)
        b._turn_phase = "none"
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        self.assertEqual(_turn_arc_overlap_pairs([a, b]), [])

        b._turn_phase = "settling"
        b._sync_collision_shell(force=True)
        self.assertEqual(_turn_arc_overlap_pairs([a, b]), [(1, 2)])

    def test_tracker_emits_turn_arc_overlap_pre_separation(self):
        import main as game

        a = game.Car(100, 100, 3.0, vertical=False, spawn_id=1)
        a._turn_phase = "turning"
        b = game.Car(118, 100, 3.0, vertical=False, spawn_id=2)
        b._turn_phase = "turning"
        a._sync_collision_shell(force=True)
        b._sync_collision_shell(force=True)
        tracker = SpectateTracker()
        emitted = []
        for frame in range(1, TURN_ARC_OVERLAP_FRAMES + 1):
            emitted = tracker.observe_pre_separation(
                frame=frame,
                sim_t=frame / 60.0,
                cars=[a, b],
                intersection_zones=[],
            )
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].kind, "turn_arc_overlap")
        self.assertEqual(tracker.turn_arc_pre_separation_frames, TURN_ARC_OVERLAP_FRAMES)


class TestSyntheticClock(unittest.TestCase):
    def test_clock_advances_deterministically(self):
        clock = SyntheticClock(t=100.0, dt=1 / 60)
        self.assertEqual(clock.now(), 100.0)
        clock.advance()
        self.assertAlmostEqual(clock.now(), 100.0 + 1 / 60)


class TestSpectateRound(unittest.TestCase):
    def test_run_spectate_round_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_spectate_round(
                seed=SESSION_SEED,
                autopilot=True,
                output_dir=tmp,
                playback_rate=8.0,
            )
            self.assertIn(result.outcome, ("collision", "timeout", "success"))
            self.assertGreater(result.sim_frames, 100)
            self.assertLess(result.wall_seconds, 60.0)
            self.assertTrue(os.path.isfile(result.log_path))
            self.assertTrue(os.path.isfile(result.report_path))
            self.assertTrue(os.path.isfile(result.dashboard_path))

            with open(result.report_path, encoding="utf-8") as f:
                report = json.load(f)
            self.assertEqual(report["session_seed"], SESSION_SEED)
            self.assertIn("metrics", report)
            self.assertIn("anomalies", report)

            with open(result.dashboard_path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("const DEFAULT_PLAYBACK_RATE = 8", html)
            self.assertIn("spectate_anomalies", html)
            self.assertIn("spectate_metrics", html)

    def test_synthetic_clock_drives_round_duration(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile

        clock = SyntheticClock(t=2_000_000.0, dt=1 / 60)
        game.session_base_seed = SESSION_SEED
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []

        with patch.object(game.time, "time", clock.now):
            game.start_round(1, DifficultyProfile.for_menu_preset("normal"), "normal")
            for _ in range(300):
                game.update_round_frame(KeyState())
                clock.advance()
            if game.round_active:
                game.end_round(False, timed_out=True)

        duration = game.round_results[-1]["duration_s"]
        self.assertAlmostEqual(duration, 300 / 60, delta=0.05)

    def test_autopilot_moves_toward_goal(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile

        game.session_base_seed = 12345
        game.session_use_adaptive_map = False
        game.start_round(1, DifficultyProfile.for_menu_preset("normal"), "normal")
        start = game.player.rect.center
        keys = autopilot_keys(game)
        self.assertTrue(keys.pressed("left", "right", "up", "down"))
        game.update_round_frame(keys)
        self.assertNotEqual(game.player.rect.center, start)


class TestSpectateAnomalyBudget(unittest.TestCase):
    def test_seed_1890416619_anomalies_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_spectate_round(
                seed=SESSION_SEED,
                autopilot=True,
                output_dir=tmp,
            )
            metrics = result.report["metrics"]
            self.assertLess(metrics["anomaly_count"], 45)
            self.assertLess(metrics["overlap_frames"], 350)
            self.assertLessEqual(metrics["max_overlap_pairs"], 2)
            by_kind = metrics["by_kind"]
            self.assertEqual(by_kind.get("turn_stuck", 0), 0)
            self.assertEqual(by_kind.get("frozen_near_turner", 0), 0)
            self.assertEqual(by_kind.get("turn_arc_overlap", 0), 0)
            self.assertLess(metrics.get("turn_arc_pre_separation_frames", 0), 12)
            self.assertEqual(metrics["anomaly_count"], 0)

    def test_cars_enter_intersections_during_round(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile

        clock = SyntheticClock(t=1_000_000.0, dt=1 / 60)
        game.session_base_seed = SESSION_SEED
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []
        profile = DifficultyProfile.for_menu_preset("normal")

        max_in_ix = 0
        with patch.object(game.time, "time", clock.now):
            game.start_round(1, profile, "normal")
            for _ in range(450):
                game.update_round_frame(KeyState())
                clock.advance()
                alive = [c for c in game.cars.sprites() if c.alive()]
                in_ix = sum(
                    1
                    for c in alive
                    if any(rects_overlap(c.rect, z) for z in game.intersection_zones)
                )
                max_in_ix = max(max_in_ix, in_ix)

        self.assertGreater(
            max_in_ix,
            0,
            "no car entered an intersection — traffic is frozen at approach lines",
        )


if __name__ == "__main__":
    unittest.main()
