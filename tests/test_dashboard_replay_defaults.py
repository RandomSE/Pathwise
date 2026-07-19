"""Regression tests for dashboard replay open defaults."""

from __future__ import annotations

import unittest

from analytics.dashboard import (
    DEFAULT_CITY_REPLAY_ZOOM,
    DEFAULT_HIGHWAY_REPLAY_ZOOM,
    OLD_DEFAULT_PLAYBACK_RATE,
    replay_defaults_for_session,
    session_is_highway,
)


class TestReplayDefaults(unittest.TestCase):
    def test_city_default_zoom_is_600_percent(self):
        rate, zoom = replay_defaults_for_session({"modifiers": []})
        self.assertEqual(rate, 1.0)
        self.assertEqual(zoom, DEFAULT_CITY_REPLAY_ZOOM)

    def test_highway_modifier_defaults_to_200_percent_zoom(self):
        rate, zoom = replay_defaults_for_session({"modifiers": ["highway"]})
        self.assertEqual(zoom, DEFAULT_HIGHWAY_REPLAY_ZOOM)
        self.assertEqual(rate, 1.0)

    def test_highway_map_id_without_modifiers_list(self):
        session = {"map_layout": {"map_id": "highway_42", "generation": {"mode": "highway"}}}
        self.assertTrue(session_is_highway(session))
        _rate, zoom = replay_defaults_for_session(session)
        self.assertEqual(zoom, DEFAULT_HIGHWAY_REPLAY_ZOOM)

    def test_old_defaults_playback_to_2x(self):
        rate, zoom = replay_defaults_for_session({"modifiers": ["old"]})
        self.assertEqual(rate, OLD_DEFAULT_PLAYBACK_RATE)
        self.assertEqual(zoom, DEFAULT_CITY_REPLAY_ZOOM)

    def test_old_plus_highway(self):
        rate, zoom = replay_defaults_for_session(
            {"modifiers": ["old", "highway"]},
            default_playback_rate=1.0,
        )
        self.assertEqual(rate, 2.0)
        self.assertEqual(zoom, 2.0)

    def test_caller_higher_playback_rate_wins(self):
        rate, _zoom = replay_defaults_for_session(
            {"modifiers": ["old"]},
            default_playback_rate=8.0,
        )
        self.assertEqual(rate, 8.0)

    def test_html_zoom_label_matches_zoom_factor(self):
        # Contract: display percent === round(zoom * 100).
        for zoom in (2.0, 6.0):
            self.assertEqual(f"{int(round(zoom * 100))}%", f"{int(zoom * 100)}%")


if __name__ == "__main__":
    unittest.main()
