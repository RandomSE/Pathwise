"""Reliability, rank-order recovery, and motor/decision tempo split.

Fixtures are generated in-process by analytics.session_simulator with
deterministic seeds. Coefficients must not be 1.0 by construction.
"""

from __future__ import annotations

import statistics
import unittest

from analytics.fairness import adverse_impact_ratio, fairness_report
from analytics.reliability import (
    cronbach_alpha,
    icc1,
    reliability_report,
    spearman_brown,
)
from analytics.session_simulator import POLICIES, simulate_session_log
from analytics.trait_scoring import FLAG_INSUFFICIENT, FLAG_OK, score_session, score_session_log
from analytics.validity_register import VALIDITY_REGISTER, VALIDITY_REGISTER_VERSION


TRAIT_KEYS = (
    "risk_propensity",
    "decision_tempo",
    "deliberation_depth",
    "rule_adherence",
    "adaptive_planning",
    "composure",
)


def _mean_trait(policy: str, trait: str, *, seed: int, n_persons: int = 8, n_rounds: int = 6):
    values = []
    for index in range(n_persons):
        log = simulate_session_log(policy, seed=seed + index * 17, n_rounds=n_rounds)
        scored = score_session_log(log)
        if scored["trait_flags"].get(trait) == FLAG_OK and scored["traits"].get(trait) is not None:
            values.append(float(scored["traits"][trait]))
    return values


class TestValidityRegisterContract(unittest.TestCase):
    def test_six_in_game_dimensions_documented(self):
        self.assertTrue(VALIDITY_REGISTER_VERSION)
        self.assertEqual(set(VALIDITY_REGISTER["dimensions"]), set(TRAIT_KEYS))
        for key in TRAIT_KEYS:
            dim = VALIDITY_REGISTER["dimensions"][key]
            self.assertTrue(str(dim["construct_label"]).startswith("In-game"))
            self.assertIn("operational_definition", dim)
            self.assertIn("inclusion", dim)
            self.assertIn("exclusion", dim)
            self.assertIn("known_confounds", dim)
            self.assertIn("is_not", dim)
            joined = " ".join(dim["is_not"]).lower()
            self.assertIn("dospert", joined)
            self.assertIn("big five", joined)

    def test_decision_tempo_is_not_raw_approach_time(self):
        text = VALIDITY_REGISTER["dimensions"]["decision_tempo"]["operational_definition"].lower()
        self.assertIn("commit_latency", text)
        self.assertIn("not scored as cognitive tempo", text)
        self.assertNotIn("raw approach-to-cross time as", text)

    def test_payload_cites_register_and_denies_external_validity(self):
        log = simulate_session_log("rule_follower", seed=3, n_rounds=2)
        payload = score_session_log(log)
        validity = payload["validity"]
        self.assertEqual(validity["register_version"], VALIDITY_REGISTER_VERSION)
        self.assertEqual(validity["claim_level"], "face_validity_only")
        self.assertIs(validity["construct_validity"], False)
        self.assertIs(validity["convergent_validity"], False)
        self.assertIs(validity["criterion_validity"], False)
        self.assertIs(validity["predicts_job_performance"], False)
        self.assertFalse(validity["authorized_for_employment_decisions"])
        self.assertIn("reliability", payload)
        self.assertIn("internal_reliability", validity)


class TestDecisionTempoSplit(unittest.TestCase):
    def test_raw_approach_time_alone_is_insufficient(self):
        session = {
            "outcome": "success",
            "duration_s": 16.0,
            "crossings": 3,
            "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 3,
            "crossing_attempts": [
                {"commit_time_s": 0.4, "road_index": 0},
                {"commit_time_s": 0.5, "road_index": 1},
                {"commit_time_s": 0.6, "road_index": 2},
            ],
            "summary": {
                "quick_commits": 3,
                "slow_commits": 0,
                "total_hesitation_s": 0.1,
                "hesitation_count": 0,
                "total_backtracks": 0,
            },
        }
        result = score_session(session)
        self.assertEqual(result["trait_flags"]["decision_tempo"], FLAG_INSUFFICIENT)
        self.assertIsNone(result["traits"]["decision_tempo"])

    def test_curb_latency_scores_decision_tempo(self):
        fast = score_session(
            {
                "outcome": "success",
                "duration_s": 16.0,
                "crossings": 3,
                "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 3,
                "crossing_attempts": [
                    {
                        "commit_time_s": 4.0,
                        "commit_latency_s": 0.3,
                        "approach_travel_s": 3.7,
                        "approach_path_px": 220.0,
                        "road_index": i,
                    }
                    for i in range(3)
                ],
                "summary": {
                    "quick_commits": 0,
                    "slow_commits": 3,
                    "total_hesitation_s": 0.1,
                    "hesitation_count": 0,
                    "total_backtracks": 0,
                },
            }
        )
        slow = score_session(
            {
                "outcome": "success",
                "duration_s": 16.0,
                "crossings": 3,
                "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 3,
                "crossing_attempts": [
                    {
                        "commit_time_s": 4.0,
                        "commit_latency_s": 6.5,
                        "approach_travel_s": 0.4,
                        "approach_path_px": 40.0,
                        "road_index": i,
                    }
                    for i in range(3)
                ],
                "summary": {
                    "quick_commits": 0,
                    "slow_commits": 3,
                    "total_hesitation_s": 0.1,
                    "hesitation_count": 0,
                    "total_backtracks": 0,
                },
            }
        )
        self.assertEqual(fast["trait_flags"]["decision_tempo"], FLAG_OK)
        self.assertGreater(fast["traits"]["decision_tempo"], slow["traits"]["decision_tempo"])
        self.assertEqual(fast["signal_sources"]["decision_tempo"], "commit_latency_s")
        self.assertIn("motor_tempo", fast.get("diagnostics") or fast["signal_sources"])

    def test_motor_slow_does_not_fully_masquerade_as_low_decision_tempo(self):
        motor_slow = _mean_trait("motor_slow", "decision_tempo", seed=11, n_persons=6, n_rounds=5)
        motor_fast = _mean_trait("motor_fast", "decision_tempo", seed=21, n_persons=6, n_rounds=5)
        slow_commit = _mean_trait("slow_commit", "decision_tempo", seed=31, n_persons=6, n_rounds=5)
        self.assertGreaterEqual(len(motor_slow), 4)
        self.assertGreaterEqual(len(motor_fast), 4)
        self.assertGreaterEqual(len(slow_commit), 4)
        motor_gap = abs(statistics.mean(motor_slow) - statistics.mean(motor_fast))
        commit_gap = abs(statistics.mean(slow_commit) - statistics.mean(motor_fast))
        self.assertLess(motor_gap, commit_gap)
        self.assertGreater(statistics.mean(motor_slow), 45.0)


class TestReliabilityFromSimulatedSessions(unittest.TestCase):
    def test_same_policy_stability_is_high_but_not_one(self):
        persons = []
        for index in range(10):
            log = simulate_session_log("high_risk", seed=100 + index, n_rounds=8)
            persons.append(log)
        report = reliability_report(persons, score_fn=score_session_log)
        risk = report["traits"]["risk_propensity"]
        self.assertGreaterEqual(risk["n_ok_rounds_mean"], 4)
        self.assertGreaterEqual(risk["spearman_brown"], 0.70)
        self.assertLess(risk["spearman_brown"], 1.0)
        self.assertGreater(risk["sd_across_rounds_mean"], 0.0)
        if risk.get("cronbach_alpha") is not None:
            self.assertLess(risk["cronbach_alpha"], 1.0)
        if risk.get("icc1") is not None:
            self.assertGreaterEqual(risk["icc1"], 0.40)
            self.assertLess(risk["icc1"], 1.0)
        self.assertEqual(risk["flag"], "ok")

    def test_too_few_rounds_flag_insufficient(self):
        log = simulate_session_log("rule_follower", seed=4, n_rounds=1)
        payload = score_session_log(log)
        for key in TRAIT_KEYS:
            self.assertEqual(payload["reliability"]["traits"][key]["flag"], FLAG_INSUFFICIENT)

    def test_high_risk_recovers_above_low_risk(self):
        high = _mean_trait("high_risk", "risk_propensity", seed=40, n_persons=8, n_rounds=6)
        low = _mean_trait("low_risk", "risk_propensity", seed=50, n_persons=8, n_rounds=6)
        self.assertGreater(statistics.mean(high), statistics.mean(low) + 8.0)

    def test_rule_follower_recovers_above_red_crosser(self):
        follow = _mean_trait("rule_follower", "rule_adherence", seed=60, n_persons=8, n_rounds=6)
        red = _mean_trait("red_crosser", "rule_adherence", seed=70, n_persons=8, n_rounds=6)
        self.assertGreater(statistics.mean(follow), statistics.mean(red) + 8.0)

    def test_fast_commit_recovers_above_slow_commit(self):
        fast = _mean_trait("fast_commit", "decision_tempo", seed=80, n_persons=8, n_rounds=6)
        slow = _mean_trait("slow_commit", "decision_tempo", seed=90, n_persons=8, n_rounds=6)
        self.assertGreater(statistics.mean(fast), statistics.mean(slow) + 8.0)

    def test_session_payload_persists_reliability(self):
        log = simulate_session_log("high_risk", seed=5, n_rounds=6)
        payload = score_session_log(log)
        self.assertIn("reliability", payload)
        self.assertIn("hiring_output", payload)
        self.assertIn("reliability", payload["hiring_output"])
        risk = payload["reliability"]["traits"]["risk_propensity"]
        self.assertIn("sd_across_rounds", risk)
        self.assertNotEqual(risk.get("spearman_brown"), 1.0)


class TestReliabilityMath(unittest.TestCase):
    def test_cronbach_and_icc_reject_perfect_constant(self):
        items = [[10.0, 10.0, 10.0], [10.0, 10.0, 10.0], [10.0, 10.0, 10.0]]
        alpha = cronbach_alpha(items)
        self.assertIsNone(alpha)
        varied = [
            [12.0, 18.0, 11.0],
            [40.0, 48.0, 36.0],
            [70.0, 66.0, 74.0],
            [90.0, 88.0, 92.0],
        ]
        alpha = cronbach_alpha(varied)
        self.assertIsNotNone(alpha)
        self.assertGreater(alpha, 0.7)
        self.assertLess(alpha, 1.0)
        icc = icc1(varied)
        self.assertIsNotNone(icc)
        self.assertGreater(icc, 0.5)
        self.assertLess(icc, 1.0)
        sb = spearman_brown(0.6, n_fold=2)
        self.assertGreater(sb, 0.6)
        self.assertLess(sb, 1.0)


class TestFairnessScaffolding(unittest.TestCase):
    def test_motor_groups_decision_tempo_air_nearer_one_than_raw_approach(self):
        rows = []
        for index in range(12):
            slow = simulate_session_log("motor_slow", seed=200 + index, n_rounds=4)
            fast = simulate_session_log("motor_fast", seed=300 + index, n_rounds=4)
            slow_scored = score_session_log(slow)
            fast_scored = score_session_log(fast)
            slow_raw = _mean_approach(slow)
            fast_raw = _mean_approach(fast)
            rows.append(
                {
                    "group": "motor_slow",
                    "decision_tempo": slow_scored["traits"]["decision_tempo"],
                    "raw_approach_s": slow_raw,
                }
            )
            rows.append(
                {
                    "group": "motor_fast",
                    "decision_tempo": fast_scored["traits"]["decision_tempo"],
                    "raw_approach_s": fast_raw,
                }
            )
        report = fairness_report(
            rows,
            group_key="group",
            score_keys=("decision_tempo", "raw_approach_s"),
            selection_cutoffs={"decision_tempo": 55.0, "raw_approach_s": 2.5},
            higher_is_selected={"decision_tempo": True, "raw_approach_s": False},
        )
        tempo_air = report["adverse_impact_ratio"]["decision_tempo"]
        raw_air = report["adverse_impact_ratio"]["raw_approach_s"]
        self.assertIsNotNone(tempo_air)
        self.assertIsNotNone(raw_air)
        self.assertLess(abs(1.0 - tempo_air), abs(1.0 - raw_air))

    def test_no_group_label_skips_ratio(self):
        rows = [{"decision_tempo": 60.0}, {"decision_tempo": 40.0}]
        report = fairness_report(rows, group_key="group", score_keys=("decision_tempo",))
        self.assertEqual(report["status"], "no_group_labels")
        self.assertIsNone(report["adverse_impact_ratio"].get("decision_tempo"))

    def test_adverse_impact_ratio_helper(self):
        self.assertAlmostEqual(adverse_impact_ratio(0.4, 0.5), 0.8)
        self.assertIsNone(adverse_impact_ratio(0.4, 0.0))


def _mean_approach(log: dict) -> float:
    times = []
    for entry in log.get("rounds") or []:
        session = entry.get("session") or entry
        for attempt in session.get("crossing_attempts") or []:
            raw = attempt.get("commit_time_s")
            if raw is None:
                continue
            times.append(float(raw))
    if not times:
        return 99.0
    return sum(times) / len(times)


class TestPoliciesExist(unittest.TestCase):
    def test_required_policies(self):
        for name in (
            "high_risk",
            "low_risk",
            "fast_commit",
            "slow_commit",
            "rule_follower",
            "red_crosser",
            "motor_slow",
            "motor_fast",
        ):
            self.assertIn(name, POLICIES)


if __name__ == "__main__":
    unittest.main()
