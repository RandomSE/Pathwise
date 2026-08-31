"""Role target similarity: coverage floor, nulls last, two-sided field_construction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analytics.archetype_scoring import score_session
from analytics.dashboard import build_dashboard_html
from analytics.role_catalog import ROLE_CATALOG, ROLE_CATALOG_VERSION, roles_by_id
from analytics.role_fit import MIN_ROLE_FIT_COVERAGE, compute_role_fits, rank_role_fits
from analytics.trait_scoring import TRAIT_KEYS


BANNED_PHRASES = (
    "predicts job",
    "validated trait",
    "convergent validity",
    "will succeed",
)


def _ok_flags():
    return {key: "ok" for key in TRAIT_KEYS}


def _traits(**kwargs):
    base = {key: 50.0 for key in TRAIT_KEYS}
    base.update(kwargs)
    return base


class TestCatalogPriors(unittest.TestCase):
    def test_four_starter_roles_and_unvalidated_priors_comment(self):
        self.assertEqual(len(ROLE_CATALOG), 4)
        self.assertIn("field_construction", roles_by_id())
        self.assertIn("compliance_auditor", roles_by_id())
        self.assertIn("logistics_dispatcher", roles_by_id())
        self.assertIn("warehouse_operator", roles_by_id())
        self.assertTrue(ROLE_CATALOG_VERSION)
        source = Path(__file__).resolve().parents[1] / "analytics" / "role_catalog.py"
        self.assertIn("unvalidated priors", source.read_text(encoding="utf-8").lower())
        self.assertEqual(ROLE_CATALOG_VERSION, "2")
        by_id = roles_by_id()
        field = by_id["field_construction"]
        auditor = by_id["compliance_auditor"]
        dispatcher = by_id["logistics_dispatcher"]
        warehouse = by_id["warehouse_operator"]
        self.assertGreater(
            field["targets"]["risk_propensity"], auditor["targets"]["risk_propensity"]
        )
        self.assertGreater(
            field["targets"]["adaptive_planning"],
            auditor["targets"]["adaptive_planning"],
        )
        self.assertGreater(
            auditor["targets"]["rule_adherence"],
            max(role["targets"]["rule_adherence"] for role in ROLE_CATALOG if role is not auditor),
        )
        self.assertLess(
            auditor["targets"]["risk_propensity"],
            min(role["targets"]["risk_propensity"] for role in ROLE_CATALOG if role is not auditor),
        )
        self.assertGreaterEqual(dispatcher["targets"]["decision_tempo"], 64)
        self.assertGreaterEqual(dispatcher["targets"]["rule_adherence"], 64)
        self.assertLess(dispatcher["targets"]["risk_propensity"], 40)
        self.assertLess(
            abs(warehouse["targets"]["decision_tempo"] - 50.0),
            abs(dispatcher["targets"]["decision_tempo"] - 50.0),
        )
        for role in ROLE_CATALOG:
            self.assertAlmostEqual(sum(role["weights"].values()), 1.0, places=5)
            self.assertEqual(set(role["weights"]), set(TRAIT_KEYS))
            self.assertEqual(set(role["targets"]), set(TRAIT_KEYS))
            self.assertIn("rationale", role)
            self.assertTrue(role["rationale"])
            self.assertEqual(set(role["target_bands"]), set(TRAIT_KEYS))
            for key, (low, high) in role["target_bands"].items():
                self.assertLess(low, high)
                self.assertGreaterEqual(role["targets"][key], low)
                self.assertLessEqual(role["targets"][key], high)


class TestCoverageFloor(unittest.TestCase):
    def test_below_floor_is_null_not_numeric(self):
        flags = {key: "insufficient_data" for key in TRAIT_KEYS}
        flags["decision_tempo"] = "ok"
        traits = {key: None for key in TRAIT_KEYS}
        traits["decision_tempo"] = 90.0
        rows = compute_role_fits(traits, flags)
        field = next(row for row in rows if row["role_id"] == "field_construction")
        self.assertIsNone(field["fit"])
        self.assertEqual(field["reason"], "insufficient_coverage")
        self.assertLess(field["coverage"], MIN_ROLE_FIT_COVERAGE)
        self.assertNotIn("decision_tempo", field["missing_dimensions"])
        self.assertGreaterEqual(len(field["missing_dimensions"]), 1)
        self.assertEqual(field["interpretation"], "target_similarity_only")

    def test_sparse_null_cannot_outrank_full_numeric(self):
        sparse_flags = {key: "insufficient_data" for key in TRAIT_KEYS}
        sparse_flags["decision_tempo"] = "ok"
        sparse_traits = {key: None for key in TRAIT_KEYS}
        sparse_traits["decision_tempo"] = 100.0
        sparse_rows = compute_role_fits(sparse_traits, sparse_flags)

        field = roles_by_id()["field_construction"]["targets"]
        full_traits = _traits(
            risk_propensity=field["risk_propensity"],
            adaptive_planning=field["adaptive_planning"],
            composure=field["composure"],
            rule_adherence=field["rule_adherence"],
            decision_tempo=field["decision_tempo"],
            deliberation_depth=field["deliberation_depth"],
        )
        full_rows = compute_role_fits(full_traits, _ok_flags())
        combined = rank_role_fits(sparse_rows + full_rows)
        first_numeric = next(row for row in combined if row["fit"] is not None)
        self.assertIsNotNone(first_numeric["fit"])
        sparse_field = next(
            row
            for row in sparse_rows
            if row["role_id"] == "field_construction"
        )
        self.assertIsNone(sparse_field["fit"])
        self.assertGreater(
            combined.index(sparse_field),
            combined.index(first_numeric),
        )

    def test_nulls_sort_after_every_numeric(self):
        rows = [
            {
                "role_id": "a",
                "fit": None,
                "coverage": 0.2,
                "interpretation": "target_similarity_only",
            },
            {
                "role_id": "b",
                "fit": 40.0,
                "coverage": 1.0,
                "interpretation": "target_similarity_only",
            },
            {
                "role_id": "c",
                "fit": 90.0,
                "coverage": 1.0,
                "interpretation": "target_similarity_only",
            },
            {
                "role_id": "d",
                "fit": None,
                "coverage": 0.1,
                "interpretation": "target_similarity_only",
            },
        ]
        ranked = rank_role_fits(rows)
        self.assertEqual([row["role_id"] for row in ranked], ["c", "b", "a", "d"])


class TestTwoSidedFieldConstruction(unittest.TestCase):
    def test_reckless_worse_than_target_risk(self):
        field = roles_by_id()["field_construction"]["targets"]
        on_target = compute_role_fits(
            _traits(**{key: float(field[key]) for key in TRAIT_KEYS}),
            _ok_flags(),
        )
        reckless = compute_role_fits(
            _traits(
                **{
                    key: 100.0 if key == "risk_propensity" else float(field[key])
                    for key in TRAIT_KEYS
                }
            ),
            _ok_flags(),
        )
        fit_on = next(r for r in on_target if r["role_id"] == "field_construction")["fit"]
        fit_reckless = next(r for r in reckless if r["role_id"] == "field_construction")["fit"]
        self.assertGreater(fit_on, fit_reckless)

    def test_floor_polarity_does_not_penalize_above_target(self):
        catalog = (
            {
                "role_id": "floor_demo",
                "label": "Floor demo",
                "targets": {key: 50.0 for key in TRAIT_KEYS},
                "weights": {key: 1.0 / len(TRAIT_KEYS) for key in TRAIT_KEYS},
                "polarity": {key: "floor" for key in TRAIT_KEYS},
            },
        )
        at_target = compute_role_fits(_traits(), _ok_flags(), catalog=catalog)
        above = compute_role_fits(
            _traits(
                risk_propensity=90.0,
                decision_tempo=90.0,
                deliberation_depth=90.0,
                rule_adherence=90.0,
                adaptive_planning=90.0,
                composure=90.0,
            ),
            _ok_flags(),
            catalog=catalog,
        )
        below = compute_role_fits(
            _traits(
                risk_propensity=10.0,
                decision_tempo=10.0,
                deliberation_depth=10.0,
                rule_adherence=10.0,
                adaptive_planning=10.0,
                composure=10.0,
            ),
            _ok_flags(),
            catalog=catalog,
        )
        fit_at = at_target[0]["fit"]
        fit_above = above[0]["fit"]
        fit_below = below[0]["fit"]
        self.assertEqual(fit_at, fit_above)
        self.assertGreater(fit_at, fit_below)


class TestDashboardCopyGuard(unittest.TestCase):
    def test_validity_banners_absent_and_banned_phrases_absent(self):
        session = {
            "duration_s": 12.5,
            "outcome": "success",
            "round_index": 1,
            "crossings": 2,
            "risky_risk_events": 0,
            "reasonable_risk_events": 0,
            "replay_frames": [{"t": 0, "cars": []}],
            "decision_marks": [],
            "risk_marks": [],
            "map_layout": {"roads": [{"x": 0}]},
            "car_archetypes": [],
            "decision_sequence": [{"t": 1.0, "action": "cross_on_green"}],
            "crossing_attempts": [
                {
                    "commit_time_s": 0.8,
                    "commit_latency_s": 0.35,
                    "approach_travel_s": 0.45,
                    "approach_path_px": 40.0,
                }
            ],
            "summary": {
                "total_hesitation_s": 0.2,
                "hesitation_count": 0,
                "total_backtracks": 0,
                "quick_commits": 1,
                "slow_commits": 0,
            },
        }
        scored = score_session(session)
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "logs.json"
            log_path.write_text(
                __import__("json").dumps(
                    {"session": session, "outcome": "success", "archetypes": scored}
                ),
                encoding="utf-8",
            )
            out = build_dashboard_html(log_path, output_path=Path(tmp) / "out.html")
            html = Path(out).read_text(encoding="utf-8")
        lower = html.lower()
        self.assertIn("target similarity", lower)
        self.assertIn("session summary flavor (not a hiring label)", lower)
        self.assertNotIn("face-valid in-game behavior", lower)
        self.assertNotIn("not authorized for employment decisions", lower)
        self.assertNotIn("job fit %", lower)
        self.assertNotIn("hire score", lower)
        self.assertNotIn("% fit", lower)
        for phrase in BANNED_PHRASES:
            self.assertNotIn(phrase, lower)
        self.assertNotIn("role-tailored scoring", lower)


if __name__ == "__main__":
    unittest.main()
