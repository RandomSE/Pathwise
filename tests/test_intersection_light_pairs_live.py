import unittest

from analytics.traffic_lights import FORBIDDEN_PERPENDICULAR_PAIRS, alternation_cycle_length
from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KeyState


class TestIntersectionLightPairsLive(unittest.TestCase):
    def test_two_hundred_steps_zero_forbidden_pairs(self):
        import main as game

        game.session_base_seed = 215728416
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        g, y, _r = game._LIGHT_GREEN, game._LIGHT_YELLOW, game._LIGHT_RED
        alt = alternation_cycle_length(g, y)
        v_state = next(s for s in game.road_states if s["direction"] == "vertical")
        h_state = next(s for s in game.road_states if s["direction"] == "horizontal")
        for i in range(200):
            elapsed = (i / 200.0) * alt
            game.update_light_timers(game.road_states, elapsed)
            pair = (v_state["light_state"], h_state["light_state"])
            self.assertNotIn(
                pair,
                FORBIDDEN_PERPENDICULAR_PAIRS,
                msg=f"step={i} t={elapsed} {pair}",
            )
            game.update_round_frame(KeyState())


if __name__ == "__main__":
    unittest.main()
