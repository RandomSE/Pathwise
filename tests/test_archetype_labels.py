"""Cosmetic archetype labels: nearest centroid, dual-write, not hiring."""

from __future__ import annotations

import unittest

from analytics.archetype_labels import ARCHETYPE_CENTROIDS, cosmetic_archetype
from analytics.archetype_scoring import score_session
from analytics.trait_scoring import TRAIT_KEYS


class TestCosmeticLabels(unittest.TestCase):
    def test_nearest_centroid_stable_tie_break(self):
        traits = {key: 50.0 for key in TRAIT_KEYS}
        flags = {key: "ok" for key in TRAIT_KEYS}
        result = cosmetic_archetype(traits, flags)
        self.assertIn(result["primary_key"], ARCHETYPE_CENTROIDS)
        self.assertTrue(result["cosmetic"])
        self.assertIn(result["primary_label"], (
            "Risk-Taker",
            "Strategic Planner",
            "Rule-Follower",
            "Cautious Deliberator",
            "Impulsive Mover",
        ))

    def test_score_session_dual_write_from_labels_not_hiring(self):
        session = {
            "outcome": "success",
            "duration_s": 18.0,
            "crossings": 3,
            "risky_risk_events": 0,
            "reasonable_risk_events": 0,
            "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 3,
            "crossing_attempts": [
                {
                    "commit_time_s": 0.7,
                    "commit_latency_s": 0.35,
                    "approach_travel_s": 0.35,
                    "approach_path_px": 40.0,
                }
            ]
            * 3,
            "summary": {
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 3,
                "slow_commits": 0,
            },
        }
        payload = score_session(session)
        self.assertEqual(
            payload["primary_archetype"], payload["archetype"]["primary_key"]
        )
        self.assertEqual(payload["primary_label"], payload["archetype"]["primary_label"])
        self.assertTrue(payload["archetype"]["cosmetic"])
        self.assertNotEqual(payload["hiring_output"]["kind"], payload["primary_archetype"])
        self.assertIn("scores", payload)
        self.assertIn("risk_taker", payload["scores"])
        hiring = payload["hiring_output"]
        self.assertEqual(hiring["kind"], "role_target_similarity")
        self.assertIs(hiring["traits"], payload["traits"])
        self.assertNotIn("primary_archetype", hiring)


if __name__ == "__main__":
    unittest.main()
