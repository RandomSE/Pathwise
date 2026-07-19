"""Lock intentional route-timer + dashboard template contracts (false-positive guards)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from map_generation.difficulty import DifficultyProfile
from map_generation.generator import _compute_time_limit, generate_map_layout
from analytics.dashboard import build_dashboard_html, replay_defaults_for_session


class TestRouteTimerSafetyContract(unittest.TestCase):
    def test_tuple_route_estimate_is_unpacked_into_timer(self):
        """astar_route_estimate returns (travel_s, crossings); timer uses travel_s * margin."""
        profile = DifficultyProfile.for_menu_preset("normal")
        layout = generate_map_layout(7, difficulty=profile)
        travel = float(layout["path_estimate_s"])
        expected = _compute_time_limit(travel, profile.route_time_margin)
        self.assertEqual(layout["time_limit"], expected)
        # Floor + preset margin are the remaining safety constraints (intentional).
        self.assertGreaterEqual(layout["time_limit"], 28)
        self.assertGreaterEqual(profile.route_time_margin, 1.05)

    def test_time_limit_not_below_sprint_route_estimate(self):
        profile = DifficultyProfile.for_menu_preset("hard")
        layout = generate_map_layout(99, difficulty=profile)
        self.assertGreaterEqual(layout["time_limit"], layout["path_estimate_s"])


class TestDashboardFStringSubstitution(unittest.TestCase):
    def test_replay_zoom_is_numeric_js_literal_not_placeholder(self):
        session = {
            "duration_s": 1,
            "replay_frames": [{"t": 0, "player": {"x": 0, "y": 0}, "cars": [], "lights": []}],
            "map_layout": {
                "map_id": "city_1",
                "bounds": {"x": 0, "y": 0, "w": 100, "h": 100},
                "start": [0, 0],
                "goal": {"x": 1, "y": 1, "w": 1, "h": 1},
                "roads": [],
                "crosswalks": [],
            },
            "decision_marks": [],
            "risk_marks": [],
            "modifiers": [],
        }
        payload = {"session": session, "outcome": "success", "archetypes": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            out = Path(tmp) / "dash.html"
            build_dashboard_html(str(path), str(out))
            html = out.read_text(encoding="utf-8")
        _rate, zoom = replay_defaults_for_session(session)
        self.assertNotIn("{default_replay_zoom}", html)
        self.assertIn(f"const DEFAULT_REPLAY_ZOOM = {zoom}", html)
        self.assertIn(f'id="zoom-level">{int(round(zoom * 100))}%</span>', html)


if __name__ == "__main__":
    unittest.main()
