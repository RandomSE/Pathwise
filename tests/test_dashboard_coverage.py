"""Coverage for analytics.dashboard HTML builder and CLI."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analytics.dashboard import build_dashboard_html, main


def _minimal_session(outcome="success"):
    return {
        "duration_s": 12.5,
        "outcome": outcome,
        "round_index": 1,
        "replay_frames": [{"t": 0, "cars": []}],
        "decision_marks": [{"t": 1, "action": "risk_event", "risk": True}],
        "risk_marks": [],
        "map_layout": {"roads": [{"x": 0}]},
        "car_archetypes": [],
    }


class TestBuildDashboardHtml(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_path = Path(self.tmpdir) / "logs.json"

    def _write(self, payload):
        self.session_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_replay_includes_spawn_route_hint_when_generation_present(self):
        self._write(
            {
                "session": {
                    **_minimal_session(),
                    "map_layout": {
                        "roads": [],
                        "start": [120, 340],
                        "goal": {"x": 500, "y": 80, "w": 40, "h": 40},
                        "generation": {
                            "spawn_edge": "left",
                            "goal_edge": "right",
                        },
                    },
                },
                "outcome": "success",
            }
        )
        out = build_dashboard_html(self.session_path, output_path=Path(self.tmpdir) / "route.html")
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("gen.spawn_edge", html)
        self.assertIn("gen.goal_edge", html)
        self.assertIn("stroke-dasharray", html)
        self.assertIn("${start[0]}", html)

    def test_single_session_payload(self):
        self._write({"session": _minimal_session(), "outcome": "success"})
        out = build_dashboard_html(self.session_path, output_path=Path(self.tmpdir) / "out.html")
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("<html", html.lower())
        self.assertIn("Pathwise", html)
        self.assertIn("decision_tempo_live_counts", html)
        self.assertIn("not authorized for employment decisions", html)
        self.assertIn("not construct validity", html.lower())

    def test_multi_round_payload(self):
        self._write(
            {
                "rounds": [
                    {"round": 1, "outcome": "collision", "session": _minimal_session("collision")},
                    {"round": 2, "outcome": "success", "session": _minimal_session("success")},
                ]
            }
        )
        out = build_dashboard_html(self.session_path)
        self.assertTrue(Path(out).is_file())

    def test_legacy_flat_session(self):
        sess = _minimal_session()
        self._write(sess)
        out = build_dashboard_html(self.session_path)
        self.assertTrue(Path(out).exists())

    def test_spectate_metadata_forwarded(self):
        self._write({"session": _minimal_session()})
        out = build_dashboard_html(
            self.session_path,
            spectate_anomalies=[{"kind": "stall"}],
            spectate_metrics={"frames": 1},
        )
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("stall", html)

    def test_default_output_path(self):
        self._write({"session": _minimal_session()})
        out = build_dashboard_html(self.session_path)
        self.assertTrue(str(out).endswith("_dashboard.html"))


class TestDashboardMain(unittest.TestCase):
    def test_main_missing_file(self):
        with patch("sys.argv", ["dashboard", "missing_file.json"]):
            self.assertEqual(main(), 1)

    def test_main_writes_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.json"
            path.write_text(json.dumps({"session": _minimal_session()}), encoding="utf-8")
            out = Path(tmp) / "custom.html"
            with patch("sys.argv", ["dashboard", str(path), "-o", str(out)]):
                self.assertEqual(main(), 0)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
