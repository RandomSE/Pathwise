"""Adaptive difficulty must preserve menu preset map size and route timer."""

import json
import os
import unittest

from map_generation.difficulty import DifficultyProfile
from map_generation.generator import generate_map_layout
from pathwise.round_session import _map_seed_for_round


class TestAdaptiveMapPreservesPreset(unittest.TestCase):
    def test_with_adaptive_traffic_keeps_preset_route_margin(self):
        preset = DifficultyProfile.for_menu_preset("easy")
        prior = {"outcome": "success", "duration_s": 30, "time_limit": 60, "risk_events": 4}
        merged = preset.with_adaptive_traffic(prior)
        self.assertEqual(merged.route_time_margin, preset.route_time_margin)
        self.assertEqual(merged.min_crossings, preset.min_crossings)
        self.assertEqual(merged.max_crossings, preset.max_crossings)

    def test_random_seed_sessions_no_longer_spawn_huge_maps(self):
        prior = None
        if os.path.isfile("logs.json"):
            with open("logs.json", encoding="utf-8") as f:
                payload = json.load(f)
            prior = payload.get("session") or payload

        for session_seed in (891689129, 530771037):
            map_seed = _map_seed_for_round(session_seed, 1)
            for preset, max_limit in (("easy", 35), ("normal", 75)):
                difficulty = DifficultyProfile.for_menu_preset(preset).with_adaptive_traffic(
                    prior
                )
                layout = generate_map_layout(map_seed, prior_session=None, difficulty=difficulty)
                self.assertLessEqual(
                    len(layout["roads"]),
                    40,
                    f"{preset} session {session_seed}: too many roads",
                )
                self.assertLessEqual(
                    layout["time_limit"],
                    max_limit,
                    f"{preset} session {session_seed}: timer {layout['time_limit']}",
                )

    def test_start_round_adaptive_uses_preset_timer(self):
        import main as game

        game.session_base_seed = 891689129
        game.session_use_adaptive_map = True
        game.session_num_rounds = 1
        game.round_results = []
        profile = DifficultyProfile.for_menu_preset("easy")
        game.start_round(1, profile, "easy")
        self.assertLessEqual(game.ROUND_TIME_LIMIT, 35)
        self.assertLessEqual(len(game.current_map.roads), 35)


if __name__ == "__main__":
    unittest.main()
