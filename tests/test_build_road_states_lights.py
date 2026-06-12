import unittest

from analytics.traffic_lights import light_state_at
from map_generation.difficulty import DifficultyProfile


class TestBuildRoadStatesLights(unittest.TestCase):
    def test_procedural_map_intersection_arms_are_perpendicular(self):
        import main as game

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        g, y, r = game._LIGHT_GREEN, game._LIGHT_YELLOW, game._LIGHT_RED
        cycle = g + y + r
        v0 = min(s["phase_offset"] for s in game.road_states if s["direction"] == "vertical")
        h0 = min(s["phase_offset"] for s in game.road_states if s["direction"] == "horizontal")
        self.assertAlmostEqual((h0 - v0) % cycle, g + y, delta=0.3)
        for t in range(40):
            elapsed = t * 0.5
            vs = light_state_at(elapsed + v0, g, y, r)
            hs = light_state_at(elapsed + h0, g, y, r)
            if vs == "green":
                self.assertNotEqual(hs, "green", msg=f"t={elapsed}")
            if hs == "green":
                self.assertNotEqual(vs, "green", msg=f"t={elapsed}")


if __name__ == "__main__":
    unittest.main()
