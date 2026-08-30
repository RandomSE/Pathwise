"""Docs, logger split fields, residual tempo, catalog bands, contrasts."""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from analytics.decision_logger import DecisionLogger
from analytics.role_catalog import ROLE_CATALOG, ROLE_CATALOG_VERSION
from analytics.session_simulator import simulate_round, simulate_session_log
from analytics.trait_scoring import FLAG_INSUFFICIENT, FLAG_OK, score_session, score_session_log
from analytics.validity_register import VALIDITY_REGISTER_VERSION


ROOT = Path(__file__).resolve().parents[1]


class TestDocsPresent(unittest.TestCase):
    def test_psychometrics_and_compliance_docs(self):
        psycho = (ROOT / "docs" / "PSYCHOMETRICS.md").read_text(encoding="utf-8")
        compliance = (ROOT / "docs" / "COMPLIANCE.md").read_text(encoding="utf-8")
        self.assertIn("commit_latency_s", psycho)
        self.assertIn("Not: DOSPERT", psycho)
        self.assertIn("authorized_for_employment_decisions", psycho)
        self.assertIn("Employee Selection Procedures", compliance)
        self.assertIn("DOSPERT", compliance)
        self.assertIn("BIS-11", compliance)
        self.assertIn("not implemented evidence", compliance.lower())
        self.assertIn(VALIDITY_REGISTER_VERSION, psycho)
        self.assertIn(ROLE_CATALOG_VERSION, psycho)


class TestLoggerCurbSplit(unittest.TestCase):
    def test_curb_arrival_splits_latency_from_approach(self):
        logger = DecisionLogger((0, 0), (200, 0), "map", 2)
        logger.note_road_approach(0, pos=(0, 0))
        time.sleep(0.05)
        logger.note_curb_arrival(0, pos=(80, 0))
        time.sleep(0.03)
        logger.note_road_crossed(0, "green")
        attempt = logger.crossing_attempts[-1]
        self.assertIsNotNone(attempt["commit_latency_s"])
        self.assertIsNotNone(attempt["approach_travel_s"])
        self.assertGreater(attempt["approach_path_px"], 50.0)
        self.assertGreaterEqual(attempt["commit_time_s"], attempt["commit_latency_s"])


class TestResidualAndContrasts(unittest.TestCase):
    def test_path_px_residual_scores_tempo(self):
        result = score_session(
            {
                "outcome": "success",
                "duration_s": 14.0,
                "crossings": 2,
                "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 2,
                "crossing_attempts": [
                    {"commit_time_s": 3.0, "approach_path_px": 90.0, "road_index": 0},
                    {"commit_time_s": 3.2, "approach_path_px": 90.0, "road_index": 1},
                ],
                "summary": {
                    "quick_commits": 0,
                    "slow_commits": 0,
                    "total_hesitation_s": 0.1,
                    "hesitation_count": 0,
                    "total_backtracks": 0,
                },
            }
        )
        self.assertEqual(result["trait_flags"]["decision_tempo"], FLAG_OK)
        self.assertEqual(result["signal_sources"]["decision_tempo"], "commit_latency_residual")
        self.assertEqual(result["diagnostics"]["motor_tempo_flag"], FLAG_OK)

    def test_within_person_modifier_deltas(self):
        baseline = {
            "outcome": "success",
            "duration_s": 16.0,
            "modifiers": [],
            "crossings": 2,
            "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 2,
            "crossing_attempts": [
                {"commit_latency_s": 0.4, "approach_travel_s": 1.0, "commit_time_s": 1.4}
            ]
            * 2,
            "summary": {
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 2,
                "slow_commits": 0,
            },
        }
        pressure = dict(
            baseline,
            modifiers=["time_pressure"],
            crossing_attempts=[
                {"commit_latency_s": 0.2, "approach_travel_s": 0.8, "commit_time_s": 1.0}
            ]
            * 2,
        )
        result = score_session_log(
            {"rounds": [{"session": baseline}, {"session": pressure}]}
        )
        self.assertEqual(result["within_person_contrasts"]["status"], FLAG_OK)
        self.assertIn("decision_tempo", result["within_person_contrasts"]["deltas"])

    def test_simulator_unknown_policy(self):
        with self.assertRaises(KeyError):
            simulate_round("not_a_policy", seed=1)
        log = simulate_session_log("low_risk", seed=2, n_rounds=0)
        self.assertEqual(log["rounds"], [])


class TestCatalogDirectionalBands(unittest.TestCase):
    def test_no_theatrical_dispatcher_clone(self):
        by_id = {role["role_id"]: role for role in ROLE_CATALOG}
        disp = by_id["logistics_dispatcher"]["targets"]
        ware = by_id["warehouse_operator"]["targets"]
        offsets = [abs(disp[key] - ware[key]) for key in disp]
        self.assertFalse(all(4.0 <= off <= 6.0 for off in offsets))
        self.assertNotIn(85, [role["targets"]["rule_adherence"] for role in ROLE_CATALOG])
        self.assertNotIn(75, [role["targets"]["decision_tempo"] for role in ROLE_CATALOG])
        self.assertNotIn(70, [role["targets"]["risk_propensity"] for role in ROLE_CATALOG])


class TestReliabilityEdges(unittest.TestCase):
    def test_helpers_reject_short_matrices(self):
        from analytics.reliability import cronbach_alpha, icc1, session_reliability, spearman_brown

        self.assertIsNone(cronbach_alpha([]))
        self.assertIsNone(cronbach_alpha([[1.0]]))
        self.assertIsNone(icc1([[1.0, 2.0]]))
        self.assertIsNone(icc1([[1.0, 2.0], [3.0]]))
        with self.assertRaises(ValueError):
            spearman_brown(0.5, n_fold=0)
        report = session_reliability([])
        self.assertEqual(report["n_rounds"], 0)
        for row in report["traits"].values():
            self.assertEqual(row["flag"], FLAG_INSUFFICIENT)

    def test_fairness_single_group_and_bad_values(self):
        from analytics.fairness import adverse_impact_ratio, fairness_report

        self.assertIsNone(adverse_impact_ratio("x", 1.0))
        report = fairness_report(
            [{"group": "a", "decision_tempo": 10}, {"group": "a", "decision_tempo": None}],
            group_key="group",
            score_keys=("decision_tempo",),
            selection_cutoffs={"decision_tempo": 50},
        )
        self.assertEqual(report["status"], "computed")
        self.assertIsNone(report["adverse_impact_ratio"]["decision_tempo"])
