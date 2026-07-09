"""Risk counter normalization for legacy and split session logs."""

import unittest

from analytics.archetype_scoring import score_session
from analytics.decision_logger import DecisionLogger
from analytics.session_risks import normalize_risk_counts, reconcile_finalize_risks
from pathwise.geom import Rect


class TestNormalizeRiskCounts(unittest.TestCase):
    def test_legacy_session_uses_risk_events_only(self):
        risky, reasonable, legacy = normalize_risk_counts({"risk_events": 4})
        self.assertEqual((risky, reasonable, legacy), (4, 0, True))

    def test_split_session_uses_explicit_counters(self):
        session = {
            "risk_events": 2,
            "risky_risk_events": 2,
            "reasonable_risk_events": 3,
        }
        risky, reasonable, legacy = normalize_risk_counts(session)
        self.assertEqual((risky, reasonable, legacy), (2, 3, False))

    def test_empty_split_with_legacy_total_is_legacy(self):
        session = {
            "risk_events": 2,
            "risky_risk_events": 0,
            "reasonable_risk_events": 0,
        }
        risky, reasonable, legacy = normalize_risk_counts(session)
        self.assertEqual((risky, reasonable, legacy), (2, 0, True))

    def test_legacy_scoring_ignores_reasonable_rate_penalty(self):
        legacy = {
            "duration_s": 10,
            "crossings": 1,
            "risk_events": 2,
            "outcome": "success",
            "decision_sequence": [],
            "summary": {},
        }
        split = dict(legacy)
        split["risky_risk_events"] = 1
        split["reasonable_risk_events"] = 1
        legacy_score = score_session(legacy)["scores"]["rule_follower"]
        split_score = score_session(split)["scores"]["rule_follower"]
        self.assertNotEqual(legacy_score, split_score)


class TestFinalizeRiskBackfill(unittest.TestCase):
    def test_finalize_backfills_split_from_legacy_counter(self):
        logger = DecisionLogger((0, 0), (100, 100), "m1", 1)
        payload = logger.finalize("success", 5.0, 1, 0, 2, "none")
        self.assertEqual(payload["risk_events"], 2)
        self.assertEqual(payload["risky_risk_events"], 2)
        self.assertEqual(payload["reasonable_risk_events"], 0)

    def test_reconcile_explicit_split(self):
        total, reasonable, risky = reconcile_finalize_risks(
            2, reasonable_risk_events=1, risky_risk_events=2
        )
        self.assertEqual((total, reasonable, risky), (2, 1, 2))


if __name__ == "__main__":
    unittest.main()
