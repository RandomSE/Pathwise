import json
import os
import tempfile
import unittest

from analytics.replay_turn_audit import (
    audit_replay_turn_pair_overlaps,
    audit_turn_position_jumps,
    turn_arc_pairs_in_replay_frame,
)
from analytics.spectate_round import run_spectate_round


SESSION_SEED = 1890416619
SWEEP_SEEDS = (42, 12345, SESSION_SEED, 999999, 777777)


class TestReplayTurnAudit(unittest.TestCase):
    def test_turn_arc_pairs_detected_in_replay_payload(self):
        cars = [
            {
                "id": 1,
                "x": 100,
                "y": 100,
                "w": 60,
                "h": 30,
                "tp": "turning",
                "cx": 130,
                "cy": 115,
            },
            {
                "id": 2,
                "x": 118,
                "y": 108,
                "w": 60,
                "h": 30,
                "tp": "settling",
                "cx": 148,
                "cy": 123,
            },
        ]
        pairs = turn_arc_pairs_in_replay_frame(cars)
        self.assertEqual(pairs, [(1, 2)])

    def test_seed_replay_turn_pairs_stay_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_spectate_round(
                seed=SESSION_SEED,
                autopilot=True,
                output_dir=tmp,
            )
            with open(result.log_path, encoding="utf-8") as f:
                log = json.load(f)
            frames = log["rounds"][0]["session"]["replay_frames"]
            overlap_stats = audit_replay_turn_pair_overlaps(frames)
            jump_stats = audit_turn_position_jumps(frames)
            self.assertLess(
                overlap_stats["max_streak"],
                3,
                msg=f"replay turn overlap streak {overlap_stats}",
            )
            self.assertLessEqual(
                jump_stats["max_overshoot_px"],
                0.0,
                msg=f"turn position jump {jump_stats}",
            )

    def test_multi_seed_replay_turn_audit(self):
        for seed in SWEEP_SEEDS:
            with self.subTest(seed=seed):
                with tempfile.TemporaryDirectory() as tmp:
                    result = run_spectate_round(
                        seed=seed,
                        autopilot=True,
                        output_dir=tmp,
                    )
                    with open(result.log_path, encoding="utf-8") as f:
                        log = json.load(f)
                    frames = log["rounds"][0]["session"]["replay_frames"]
                    overlap_stats = audit_replay_turn_pair_overlaps(frames)
                    jump_stats = audit_turn_position_jumps(frames)
                    metrics = result.report["metrics"]
                    self.assertEqual(
                        metrics["by_kind"].get("turn_arc_overlap", 0),
                        0,
                        msg=f"seed {seed} turn_arc_overlap anomalies",
                    )
                    self.assertLess(overlap_stats["max_streak"], 3)
                    self.assertLessEqual(jump_stats["max_overshoot_px"], 0.0)
                    self.assertTrue(os.path.isfile(result.dashboard_path))


if __name__ == "__main__":
    unittest.main()
