"""Regression: round tabs must swap per-round scoring, not leave a stale profile."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from analytics.dashboard import build_dashboard_html


def _round_session(*, outcome: str, red: bool, duration_s: float) -> dict:
    action = "cross_on_red" if red else "cross_on_green"
    return {
        "outcome": outcome,
        "duration_s": duration_s,
        "crossings": 1,
        "risk_events": 1 if red else 0,
        "risky_risk_events": 1 if red else 0,
        "reasonable_risk_events": 0,
        "collisions": 1 if outcome == "collision" else 0,
        "decision_sequence": [{"t": 1.0, "action": action}],
        "crossing_attempts": [{"commit_time_s": 0.5 if red else 5.0, "road_index": 0}],
        "summary": {
            "total_backtracks": 0,
            "total_hesitation_s": 0.2,
            "hesitation_count": 1,
            "quick_commits": 1 if red else 0,
            "slow_commits": 0 if red else 1,
            "decision_count": 1,
        },
        "replay_frames": [
            {"t": 0.0, "player": {"x": 0, "y": 0}, "cars": [], "lights": []}
        ],
        "map_layout": {"bounds": {"x": 0, "y": 0, "w": 80, "h": 80}},
    }


def _two_round_payload() -> dict:
    return {
        "rounds": [
            {
                "round": 1,
                "outcome": "success",
                "session": _round_session(outcome="success", red=False, duration_s=18.0),
            },
            {
                "round": 2,
                "outcome": "collision",
                "session": _round_session(
                    outcome="collision", red=True, duration_s=9.0
                ),
            },
        ]
    }


def _write_log(payload: dict, directory: Path) -> Path:
    path = directory / "logs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _embedded_data(html: str) -> dict:
    match = re.search(r"const DATA = (\{.*?\});\s*let currentFrameIndex", html, re.S)
    if match is None:
        raise AssertionError("embedded DATA payload missing from dashboard HTML")
    return json.loads(match.group(1))


class TestDashboardRoundSwitchScoring(unittest.TestCase):
    def test_apply_round_assigns_round_archetypes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            html_path = build_dashboard_html(_write_log(_two_round_payload(), directory))
            html = Path(html_path).read_text(encoding="utf-8")
        self.assertTrue(
            "DATA.archetypes = r.archetypes;" in html,
            "applyRoundToData must copy r.archetypes onto DATA",
        )

    def test_render_prefers_current_round_archetypes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            html_path = build_dashboard_html(_write_log(_two_round_payload(), directory))
            html = Path(html_path).read_text(encoding="utf-8")
        self.assertTrue(
            "DATA.archetypes || DATA.session_scoring" in html,
            "renderRoundPanels must prefer the current round archetypes",
        )
        self.assertNotIn("DATA.session_scoring || DATA.archetypes", html)

    def test_rounds_embed_distinct_archetype_payloads(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            html_path = build_dashboard_html(_write_log(_two_round_payload(), directory))
            html = Path(html_path).read_text(encoding="utf-8")
        data = _embedded_data(html)
        rounds = data["rounds"]
        self.assertEqual(len(rounds), 2)
        first = rounds[0].get("archetypes") or {}
        second = rounds[1].get("archetypes") or {}
        self.assertNotEqual(first.get("primary_label"), second.get("primary_label"))
        self.assertIn("traits", first)
        self.assertIn("traits", second)

    def test_apply_round_contract_swaps_embedded_archetypes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            html_path = build_dashboard_html(_write_log(_two_round_payload(), directory))
            html = Path(html_path).read_text(encoding="utf-8")
        data = _embedded_data(html)
        self.assertTrue(
            "DATA.archetypes = r.archetypes;" in html,
            "applyRoundToData must copy r.archetypes onto DATA",
        )
        apply_round = data["rounds"][0]
        data["archetypes"] = apply_round["archetypes"]
        self.assertEqual(data["archetypes"], data["rounds"][0]["archetypes"])
        apply_round = data["rounds"][1]
        data["archetypes"] = apply_round["archetypes"]
        self.assertEqual(data["archetypes"], data["rounds"][1]["archetypes"])
        self.assertNotEqual(
            data["archetypes"].get("primary_label"),
            data["rounds"][0]["archetypes"].get("primary_label"),
        )


if __name__ == "__main__":
    unittest.main()
