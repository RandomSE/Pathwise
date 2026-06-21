import unittest

from analytics.traffic_lights import (
    FORBIDDEN_PERPENDICULAR_PAIRS,
    alternation_cycle_length,
    arm_light_state_at,
    perpendicular_light_states_at,
    perpendicular_pair_legal,
)
from map_generation.difficulty import DifficultyProfile


class TestBuildRoadStatesLights(unittest.TestCase):
    def test_procedural_map_intersection_arms_are_perpendicular(self):
        import main as game

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        g, y, r = game._LIGHT_GREEN, game._LIGHT_YELLOW, game._LIGHT_RED
        alt = alternation_cycle_length(g, y)
        v0 = min(s["phase_offset"] for s in game.road_states if s["direction"] == "vertical")
        h0 = min(s["phase_offset"] for s in game.road_states if s["direction"] == "horizontal")
        self.assertAlmostEqual(h0, v0, delta=0.05)
        for t in range(80):
            elapsed = (t / 80.0) * alt
            vs = arm_light_state_at(
                elapsed, v0, arm_vertical=True, green_s=g, yellow_s=y
            )
            hs = arm_light_state_at(
                elapsed, h0, arm_vertical=False, green_s=g, yellow_s=y
            )
            self.assertTrue(perpendicular_pair_legal(vs, hs), msg=f"t={elapsed} {vs}/{hs}")
            self.assertNotIn((vs, hs), FORBIDDEN_PERPENDICULAR_PAIRS, msg=f"t={elapsed}")

    def test_all_vertical_and_horizontal_offsets_are_globally_aligned(self):
        import main as game

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        g, y, r = game._LIGHT_GREEN, game._LIGHT_YELLOW, game._LIGHT_RED

        v_offsets = {round(s["phase_offset"] % (g + y + r), 6) for s in game.road_states if s["direction"] == "vertical"}
        h_offsets = {round(s["phase_offset"] % (g + y + r), 6) for s in game.road_states if s["direction"] == "horizontal"}
        self.assertEqual(len(v_offsets), 1, f"vertical offsets diverged: {v_offsets}")
        self.assertEqual(len(h_offsets), 1, f"horizontal offsets diverged: {h_offsets}")
        v0 = next(iter(v_offsets))
        h0 = next(iter(h_offsets))
        self.assertAlmostEqual(h0, v0, delta=0.05)

    def test_live_road_states_never_show_forbidden_pairs(self):
        import main as game

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        g, y, _r = game._LIGHT_GREEN, game._LIGHT_YELLOW, game._LIGHT_RED
        alt = alternation_cycle_length(g, y)
        v_state = next(s for s in game.road_states if s["direction"] == "vertical")
        h_state = next(s for s in game.road_states if s["direction"] == "horizontal")
        for i in range(100):
            elapsed = (i / 100.0) * alt
            game.update_light_timers(game.road_states, elapsed)
            pair = (v_state["light_state"], h_state["light_state"])
            self.assertNotIn(pair, FORBIDDEN_PERPENDICULAR_PAIRS, msg=f"t={elapsed} {pair}")


if __name__ == "__main__":
    unittest.main()
