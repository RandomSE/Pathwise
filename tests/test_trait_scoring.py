"""Trait vector: exclusive signals, shared tempo, validity lock, session aggregate."""

from __future__ import annotations

import unittest

from analytics.archetype_scoring import score_session, score_session_log
from analytics.trait_scoring import (
    FLAG_INSUFFICIENT,
    FLAG_OK,
    LOGGER_QUICK_S,
    LOGGER_SLOW_S,
    MAX_TEMPO_PATH_DELTA,
    MEDIUM_REPR_S,
    MOTOR_TEMPO_KEY,
    QUICK_REPR_S,
    SLOW_REPR_S,
    TRAIT_KEYS,
    _between_round_stdev,
    _finite_commit_times,
    _weighted_mean,
    tempo_from_commit_s,
)


def _base_session(**overrides):
    session = {
        "outcome": "success",
        "duration_s": 20.0,
        "crossings": 4,
        "risk_events": 0,
        "risky_risk_events": 0,
        "reasonable_risk_events": 0,
        "collisions": 0,
        "decision_sequence": [
            {"t": 1.0, "action": "cross_on_green"},
            {"t": 5.0, "action": "cross_on_green"},
            {"t": 9.0, "action": "cross_on_green"},
            {"t": 13.0, "action": "cross_on_green"},
        ],
        "crossing_attempts": [
            {
                "commit_time_s": 0.7,
                "commit_latency_s": 0.35,
                "approach_travel_s": 0.35,
                "approach_path_px": 40.0,
                "road_index": 0,
            },
            {
                "commit_time_s": 0.8,
                "commit_latency_s": 0.40,
                "approach_travel_s": 0.40,
                "approach_path_px": 42.0,
                "road_index": 1,
            },
            {
                "commit_time_s": 0.6,
                "commit_latency_s": 0.30,
                "approach_travel_s": 0.30,
                "approach_path_px": 36.0,
                "road_index": 2,
            },
            {
                "commit_time_s": 0.9,
                "commit_latency_s": 0.45,
                "approach_travel_s": 0.45,
                "approach_path_px": 48.0,
                "road_index": 3,
            },
        ],
        "summary": {
            "total_backtracks": 0,
            "total_hesitation_s": 0.2,
            "hesitation_count": 0,
            "quick_commits": 4,
            "slow_commits": 0,
        },
    }
    session.update(overrides)
    return session


class TestTempoTransform(unittest.TestCase):
    def test_monotonic_decreasing_and_bounds(self):
        self.assertGreater(tempo_from_commit_s(0.4), tempo_from_commit_s(2.6))
        self.assertGreater(tempo_from_commit_s(2.6), tempo_from_commit_s(6.0))
        self.assertGreaterEqual(tempo_from_commit_s(0.0), 99.0)
        self.assertLessEqual(tempo_from_commit_s(30.0), 1.0)

    def test_no_cliff_at_logger_bins(self):
        delta_quick = abs(
            tempo_from_commit_s(LOGGER_QUICK_S - 0.01)
            - tempo_from_commit_s(LOGGER_QUICK_S + 0.01)
        )
        delta_slow = abs(
            tempo_from_commit_s(LOGGER_SLOW_S - 0.01)
            - tempo_from_commit_s(LOGGER_SLOW_S + 0.01)
        )
        self.assertLess(delta_quick, 5.0)
        self.assertLess(delta_slow, 5.0)

    def test_repr_constants_sit_in_named_bins(self):
        self.assertLess(QUICK_REPR_S, LOGGER_QUICK_S)
        self.assertEqual(MEDIUM_REPR_S, 2.6)
        self.assertGreater(SLOW_REPR_S, LOGGER_SLOW_S)

    def test_dual_path_delta_within_named_cap(self):
        times = [QUICK_REPR_S, MEDIUM_REPR_S, SLOW_REPR_S]
        continuous = sum(tempo_from_commit_s(t) for t in times) / 3.0
        residual = score_session(
            {
                "outcome": "success",
                "duration_s": 20.0,
                "crossings": 3,
                "risky_risk_events": 0,
                "reasonable_risk_events": 0,
                "decision_sequence": [],
                "crossing_attempts": [
                    {
                        "commit_time_s": t + 2.0,
                        "approach_travel_s": 2.0,
                        "road_index": i,
                    }
                    for i, t in enumerate(times)
                ],
                "summary": {
                    "quick_commits": 1,
                    "slow_commits": 1,
                    "total_hesitation_s": 0,
                    "hesitation_count": 0,
                    "total_backtracks": 0,
                },
            }
        )
        self.assertEqual(
            residual["signal_sources"]["decision_tempo"], "commit_latency_residual"
        )
        self.assertLessEqual(
            abs(continuous - residual["traits"]["decision_tempo"]),
            MAX_TEMPO_PATH_DELTA,
        )

    def test_commit_times_ignore_quick_slow_counts(self):
        with_times = _base_session(
            summary={
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 4,
                "slow_commits": 0,
            }
        )
        bloated = _base_session(
            summary={
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 0,
                "slow_commits": 4,
            }
        )
        a = score_session(with_times)
        b = score_session(bloated)
        self.assertEqual(a["signal_sources"]["decision_tempo"], "commit_latency_s")
        self.assertEqual(b["signal_sources"]["decision_tempo"], "commit_latency_s")
        self.assertEqual(a["traits"]["decision_tempo"], b["traits"]["decision_tempo"])

    def test_empty_tempo_is_insufficient_not_fifty(self):
        result = score_session(
            {
                "outcome": "unknown",
                "duration_s": 12.0,
                "crossings": 0,
                "risky_risk_events": 0,
                "decision_sequence": [],
                "crossing_attempts": [],
                "summary": {
                    "quick_commits": 0,
                    "slow_commits": 0,
                    "total_hesitation_s": 0,
                    "hesitation_count": 0,
                    "total_backtracks": 0,
                },
            }
        )
        self.assertEqual(result["trait_flags"]["decision_tempo"], "insufficient_data")
        self.assertIsNone(result["traits"]["decision_tempo"])

    def test_decision_tempo_live_counts_on_scored_payload(self):
        ok = score_session(_base_session())
        counts = ok["signal_sources"]["decision_tempo_live_counts"]
        self.assertEqual(counts["n_commit_latency"], 4)
        self.assertEqual(counts["n_residual"], 0)
        self.assertEqual(counts["n_insufficient"], 0)

        residual = score_session(
            {
                "outcome": "success",
                "duration_s": 14.0,
                "crossings": 2,
                "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 2,
                "crossing_attempts": [
                    {"commit_time_s": 3.0, "approach_path_px": 90.0, "road_index": 0},
                    {"commit_time_s": 3.2, "approach_travel_s": 1.0, "road_index": 1},
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
        residual_counts = residual["signal_sources"]["decision_tempo_live_counts"]
        self.assertEqual(residual_counts["n_commit_latency"], 0)
        self.assertEqual(residual_counts["n_residual"], 2)
        self.assertEqual(residual_counts["n_insufficient"], 0)

        empty = score_session(
            {
                "outcome": "unknown",
                "duration_s": 8.0,
                "crossings": 0,
                "decision_sequence": [],
                "crossing_attempts": [],
                "summary": {},
            }
        )
        empty_counts = empty["signal_sources"]["decision_tempo_live_counts"]
        self.assertEqual(empty_counts["n_commit_latency"], 0)
        self.assertEqual(empty_counts["n_residual"], 0)
        self.assertGreaterEqual(empty_counts["n_insufficient"], 1)

        mixed_log = score_session_log(
            {
                "rounds": [
                    {"session": _base_session()},
                    {
                        "session": {
                            "duration_s": 10.0,
                            "crossing_attempts": [{"commit_time_s": 2.0}],
                            "summary": {},
                        }
                    },
                ]
            }
        )
        mixed = mixed_log["signal_sources"]["decision_tempo_live_counts"]
        self.assertEqual(mixed["n_commit_latency"], 4)
        self.assertEqual(mixed["n_insufficient"], 1)


class TestExclusivity(unittest.TestCase):
    def test_hesitation_does_not_move_risk_or_rule(self):
        base = _base_session()
        paused = _base_session(
            summary={
                "total_backtracks": 0,
                "total_hesitation_s": 8.0,
                "hesitation_count": 6,
                "quick_commits": 4,
                "slow_commits": 0,
            }
        )
        a = score_session(base)
        b = score_session(paused)
        self.assertEqual(a["traits"]["risk_propensity"], b["traits"]["risk_propensity"])
        self.assertEqual(a["traits"]["rule_adherence"], b["traits"]["rule_adherence"])
        self.assertNotEqual(
            a["traits"]["deliberation_depth"], b["traits"]["deliberation_depth"]
        )

    def test_lights_do_not_move_tempo_or_deliberation(self):
        green = _base_session()
        red = _base_session(
            decision_sequence=[
                {"t": 1.0, "action": "cross_on_red"},
                {"t": 5.0, "action": "cross_on_red"},
                {"t": 9.0, "action": "cross_on_red"},
                {"t": 13.0, "action": "cross_on_red"},
            ]
        )
        a = score_session(green)
        b = score_session(red)
        self.assertEqual(a["traits"]["decision_tempo"], b["traits"]["decision_tempo"])
        self.assertEqual(
            a["traits"]["deliberation_depth"], b["traits"]["deliberation_depth"]
        )
        self.assertNotEqual(a["traits"]["rule_adherence"], b["traits"]["rule_adherence"])
        self.assertNotEqual(a["traits"]["risk_propensity"], b["traits"]["risk_propensity"])


class TestDispatcherShape(unittest.TestCase):
    def test_high_rule_and_high_tempo_coexist(self):
        result = score_session(_base_session())
        self.assertGreaterEqual(result["traits"]["rule_adherence"], 65.0)
        self.assertGreaterEqual(result["traits"]["decision_tempo"], 65.0)
        self.assertEqual(result["trait_flags"]["rule_adherence"], "ok")
        self.assertEqual(result["trait_flags"]["decision_tempo"], "ok")
        dispatcher = next(
            row
            for row in result["role_fits"]
            if row["role_id"] == "logistics_dispatcher"
        )
        self.assertIsNotNone(dispatcher["fit"])
        self.assertEqual(dispatcher["interpretation"], "target_similarity_only")


class TestValidityLock(unittest.TestCase):
    def test_payload_face_validity_only(self):
        result = score_session(_base_session())
        validity = result["validity"]
        self.assertEqual(validity["claim_level"], "face_validity_only")
        self.assertIs(validity["construct_validity"], False)
        self.assertIs(validity["convergent_validity"], False)
        self.assertIs(validity["criterion_validity"], False)
        self.assertIs(validity["predicts_job_performance"], False)
        self.assertFalse(validity["authorized_for_employment_decisions"])
        self.assertTrue(validity["register_version"])
        self.assertEqual(validity["population"], "in_game_pathwise_session")
        self.assertIn("this Pathwise session", validity["summary"])
        self.assertEqual(result["hiring_output"]["kind"], "role_target_similarity")
        self.assertNotIn("primary_archetype", result["hiring_output"])
        self.assertIs(result["archetype"]["cosmetic"], True)
        self.assertIn("validity", result["hiring_output"])

    def test_sparse_session_still_has_validity(self):
        result = score_session({"duration_s": 0.05, "decision_sequence": []})
        self.assertEqual(result["validity"]["claim_level"], "face_validity_only")
        self.assertIs(result["validity"]["construct_validity"], False)

    def test_insights_do_not_claim_job_success(self):
        reckless = _base_session(
            risky_risk_events=12,
            risk_events=12,
            decision_sequence=[{"t": 1.0, "action": "cross_on_red"}] * 8,
            crossing_attempts=[{"commit_time_s": 0.5, "commit_latency_s": 0.3}],
            summary={
                "total_backtracks": 2,
                "total_hesitation_s": 0.1,
                "hesitation_count": 0,
                "quick_commits": 1,
                "slow_commits": 0,
            },
        )
        blob = " ".join(score_session(reckless)["insights"]).lower()
        self.assertNotIn("will succeed", blob)
        self.assertNotIn("predicts job", blob)
        self.assertNotIn("validated trait", blob)

    def test_old_ipsative_offsets_absent_from_scoring_source(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "analytics"
        text = (root / "archetype_scoring.py").read_text(encoding="utf-8")
        text += (root / "trait_scoring.py").read_text(encoding="utf-8")
        joined = "".join(ch for ch in text if not ch.isspace())
        self.assertNotIn("35+risk_rate", joined)
        self.assertNotIn("30+slow_commits", joined)
        self.assertNotIn("25+green_crosses", joined)
        self.assertNotIn("risk_rate*120", joined)
        self.assertNotIn("20+quick_commits", joined)


class TestSessionAggregate(unittest.TestCase):
    def test_duration_weighted_mean_and_composure_variance_flag(self):
        fast = _base_session(duration_s=10.0)
        slow = _base_session(
            duration_s=30.0,
            crossing_attempts=[
                {
                    "commit_time_s": 5.0,
                    "commit_latency_s": 4.2,
                    "approach_travel_s": 0.8,
                    "approach_path_px": 70.0,
                }
            ]
            * 4,
            summary={
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 0,
                "slow_commits": 4,
            },
        )
        log = {
            "rounds": [
                {"session": fast, "round": 1, "outcome": "success"},
                {"session": slow, "round": 2, "outcome": "success"},
            ]
        }
        result = score_session_log(log)
        self.assertIn("validity", result)
        one = score_session(fast)["traits"]["decision_tempo"]
        two = score_session(slow)["traits"]["decision_tempo"]
        expected = (10.0 * one + 30.0 * two) / 40.0
        self.assertAlmostEqual(result["traits"]["decision_tempo"], expected, places=1)
        self.assertEqual(
            result["signal_sources"].get("composure_between_round_variance"),
            "insufficient_data",
        )
        self.assertIn("reliability", result)

    def test_single_round_marks_between_round_variance_insufficient(self):
        result = score_session(_base_session())
        self.assertEqual(
            result["signal_sources"]["composure_between_round_variance"],
            "insufficient_data",
        )

    def test_log_shapes_and_zero_duration_weights(self):
        nested = score_session_log({"session": _base_session()})
        flat = score_session_log(_base_session())
        self.assertEqual(nested["traits"]["decision_tempo"], flat["traits"]["decision_tempo"])
        mixed_rounds = score_session_log(
            {
                "rounds": [
                    0,
                    _base_session(duration_s=15.0),
                ]
            }
        )
        self.assertEqual(mixed_rounds["validity"]["claim_level"], "face_validity_only")
        zero_dur = score_session_log(
            {
                "rounds": [
                    {"session": _base_session(duration_s=0.0)},
                    {"session": _base_session(duration_s=0.0)},
                ]
            }
        )
        self.assertEqual(zero_dur["trait_flags"]["decision_tempo"], FLAG_OK)

    def test_fallback_tempo_tag_on_multi_round_log(self):
        residual_round = {
            "outcome": "success",
            "duration_s": 12.0,
            "crossings": 3,
            "risky_risk_events": 0,
            "reasonable_risk_events": 0,
            "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}] * 3,
            "crossing_attempts": [
                {"commit_time_s": 3.2, "approach_travel_s": 1.0},
                {"commit_time_s": 3.4, "approach_path_px": 90.0},
            ],
            "summary": {
                "total_backtracks": 0,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 2,
                "slow_commits": 1,
            },
        }
        result = score_session_log(
            {
                "rounds": [
                    {"session": residual_round},
                    {"session": dict(residual_round, duration_s=18.0)},
                ]
            }
        )
        self.assertEqual(result["signal_sources"]["decision_tempo"], "commit_latency_residual")

    def test_composure_recovery_does_not_blend_between_round_variance(self):
        fast = _base_session(
            decision_sequence=[
                {"t": 1.0, "action": "backtrack"},
                {"t": 1.3, "action": "advance"},
                {"t": 2.0, "action": "cross_on_green"},
            ]
        )
        slow = _base_session(
            duration_s=30.0,
            crossing_attempts=[
                {
                    "commit_time_s": 5.0,
                    "commit_latency_s": 4.0,
                    "approach_travel_s": 1.0,
                }
            ]
            * 4,
            decision_sequence=[
                {"t": 1.0, "action": "backtrack"},
                {"t": 7.5, "action": "commit"},
                {"t": 8.0, "action": "cross_on_green"},
            ],
            summary={
                "total_backtracks": 1,
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "quick_commits": 0,
                "slow_commits": 4,
            },
        )
        result = score_session_log(
            {"rounds": [{"session": fast}, {"session": slow}]}
        )
        self.assertEqual(result["trait_flags"]["composure"], FLAG_OK)
        self.assertIsNotNone(result["traits"]["composure"])
        self.assertEqual(
            result["signal_sources"]["composure_between_round_variance"],
            FLAG_INSUFFICIENT,
        )
        one = score_session(fast)["traits"]["composure"]
        two = score_session(slow)["traits"]["composure"]
        expected = (20.0 * one + 30.0 * two) / 50.0
        self.assertAlmostEqual(result["traits"]["composure"], expected, places=1)

    def test_two_empty_rounds_mark_variance_insufficient(self):
        empty = {
            "duration_s": 0.05,
            "decision_sequence": [],
            "crossing_attempts": [],
            "summary": {},
        }
        result = score_session_log({"rounds": [{"session": empty}, {"session": empty}]})
        self.assertEqual(
            result["signal_sources"]["composure_between_round_variance"],
            FLAG_INSUFFICIENT,
        )


class TestNamedHelpersAndRecoveryEdges(unittest.TestCase):
    def test_tempo_rejects_non_numeric(self):
        self.assertEqual(tempo_from_commit_s("nope"), 50.0)
        self.assertEqual(tempo_from_commit_s(None), 50.0)
        self.assertEqual(MOTOR_TEMPO_KEY, "motor_tempo")
        self.assertEqual(
            _finite_commit_times(
                {"crossing_attempts": [{"commit_time_s": 1.2}, {"commit_time_s": "x"}]}
            ),
            [1.2],
        )

    def test_weighted_mean_and_stdev_empty_paths(self):
        from analytics.trait_scoring import _composure_from_variance

        self.assertIsNone(_weighted_mean([(10.0, 0.0), (20.0, 0.0)]))
        self.assertAlmostEqual(_weighted_mean([(10.0, 1.0), (30.0, 1.0)]), 20.0)
        self.assertGreater(_composure_from_variance(0.0), 90.0)
        self.assertIsNone(_between_round_stdev([{"risk_propensity": 10}], [{"risk_propensity": FLAG_OK}]))
        empty_flags = {key: FLAG_INSUFFICIENT for key in TRAIT_KEYS}
        empty_traits = {key: None for key in TRAIT_KEYS}
        self.assertIsNone(
            _between_round_stdev([empty_traits, empty_traits], [empty_flags, empty_flags])
        )

    def test_missing_timestamps_flag_composure_insufficient(self):
        missing_start = score_session(
            _base_session(
                decision_sequence=[
                    {"action": "backtrack"},
                    {"t": 2.0, "action": "advance"},
                ]
            )
        )
        self.assertEqual(missing_start["trait_flags"]["composure"], FLAG_INSUFFICIENT)
        missing_later = score_session(
            _base_session(
                decision_sequence=[
                    {"t": 1.0, "action": "risk_event"},
                    {"action": "advance"},
                ]
            )
        )
        self.assertEqual(missing_later["trait_flags"]["composure"], FLAG_INSUFFICIENT)
        bad_stamp = score_session(
            _base_session(
                decision_sequence=[
                    {"t": "later", "action": "backtrack"},
                    {"t": 2.0, "action": "advance"},
                ]
            )
        )
        self.assertEqual(bad_stamp["trait_flags"]["composure"], FLAG_INSUFFICIENT)
        no_follow = score_session(
            _base_session(decision_sequence=[{"t": 1.0, "action": "backtrack"}])
        )
        self.assertEqual(no_follow["trait_flags"]["composure"], FLAG_INSUFFICIENT)

    def test_fast_and_slow_recovery_anchors(self):
        fast = score_session(
            _base_session(
                decision_sequence=[
                    {"t": 1.0, "action": "backtrack"},
                    {"t": 1.2, "action": "advance"},
                ]
            )
        )
        slow = score_session(
            _base_session(
                decision_sequence=[
                    {"t": 1.0, "action": "backtrack"},
                    {"t": 12.0, "action": "commit"},
                ]
            )
        )
        self.assertGreaterEqual(fast["traits"]["composure"], 95.0)
        self.assertLessEqual(slow["traits"]["composure"], 5.0)

    def test_replans_recover_and_fail_and_outcome_none(self):
        recovered = score_session(
            _base_session(
                outcome="collision",
                decision_sequence=[
                    {"t": 1.0, "action": "backtrack"},
                    {"t": 2.0, "action": "advance"},
                    {"t": 3.0, "action": "cross_on_green"},
                ],
                summary={
                    "total_backtracks": 1,
                    "total_hesitation_s": 0.2,
                    "hesitation_count": 0,
                    "quick_commits": 4,
                    "slow_commits": 0,
                },
            )
        )
        failed = score_session(
            _base_session(
                outcome="collision",
                decision_sequence=[
                    {"t": 1.0, "action": "backtrack"},
                    {"t": 3.0, "action": "cross_on_green"},
                ],
                summary={
                    "total_backtracks": 1,
                    "total_hesitation_s": 0.2,
                    "hesitation_count": 0,
                    "quick_commits": 4,
                    "slow_commits": 0,
                },
            )
        )
        self.assertGreater(
            recovered["traits"]["adaptive_planning"],
            failed["traits"]["adaptive_planning"],
        )
        empty = score_session(
            {
                "duration_s": 5.0,
                "outcome": None,
                "decision_sequence": [],
                "crossing_attempts": [],
                "summary": {"total_backtracks": 0},
            }
        )
        self.assertEqual(empty["trait_flags"]["adaptive_planning"], FLAG_INSUFFICIENT)

    def test_score_session_none_still_emits_validity(self):
        result = score_session(None)
        self.assertEqual(result["validity"]["claim_level"], "face_validity_only")
        log = score_session_log(None)
        self.assertEqual(log["hiring_output"]["kind"], "role_target_similarity")


if __name__ == "__main__":
    unittest.main()
