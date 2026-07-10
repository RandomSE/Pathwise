"""Direct unit tests for pathwise.round_frame."""

import unittest
from unittest.mock import patch

from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile
from pathwise.round_frame import draw_round_frame, update_round_frame


class TestRoundFrame(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 777
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.round_active = False

    def test_update_round_frame_inactive_returns_none(self):
        self.game.round_active = False
        self.assertIsNone(update_round_frame(KeyState()))

    def test_update_round_frame_active_returns_draw_state(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = update_round_frame(KeyState())
        self.assertIsNotNone(draw_state)
        for key in (
            "camera_offset",
            "view_rect",
            "record_cars",
            "draw_sprites",
            "elapsed",
            "hud_lines",
        ):
            self.assertIn(key, draw_state)

    @patch("pathwise.game_draw.draw_round_scene")
    def test_draw_round_frame_delegates_to_game_draw(self, draw_scene):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = update_round_frame(KeyState())
        draw_round_frame(800, 600, draw_state)
        draw_scene.assert_called_once()
        kwargs = draw_scene.call_args.kwargs
        self.assertEqual(kwargs["current_map"], self.game.current_map)
        self.assertEqual(kwargs["player"], self.game.player)
        self.assertEqual(kwargs["draw_sprites"], draw_state["draw_sprites"])

    def test_crosswalk_hud_uses_cars_label_not_module_ref(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        crosswalk = self.game.road_states[0]["crosswalk"]
        self.game.player.rect.center = crosswalk.center
        draw_state = update_round_frame(KeyState())
        crosswalk_lines = [
            line for line in draw_state["hud_lines"] if line.startswith("Crosswalk ·")
        ]
        self.assertEqual(len(crosswalk_lines), 1)
        self.assertRegex(crosswalk_lines[0], r"^Crosswalk · cars: (red|green)")
        self.assertNotIn("m.cars", crosswalk_lines[0])
        self.assertNotIn("EntityGroup", crosswalk_lines[0])


if __name__ == "__main__":
    unittest.main()
