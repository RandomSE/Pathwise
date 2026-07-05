import unittest
from unittest.mock import patch

from pathwise.input_keys import KeyState
from map_generation.difficulty import DifficultyProfile


class TestGameEntry(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 12345
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True

    def test_start_round_produces_draw_state(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.assertTrue(self.game.round_active)
        self.assertIsNotNone(self.game.current_map)
        self.assertGreater(len(self.game.road_states), 0)

        keys = KeyState()
        draw_state = self.game.update_round_frame(keys)
        self.assertIsNotNone(draw_state)
        self.assertIn("hud_lines", draw_state)
        self.assertIn("camera_offset", draw_state)
        self.assertIn("draw_sprites", draw_state)

    @patch("pathwise.game_draw.draw_round_scene")
    def test_first_frame_draw_round_frame_delegates(self, draw_scene):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = self.game.update_round_frame(KeyState())
        self.assertIsNotNone(draw_state)
        self.game.draw_round_frame(800, 600, draw_state)
        draw_scene.assert_called_once()

    @patch("pathwise.game_draw.gameplay_draw_surface")
    @patch("pathwise.game_draw.arcade.draw_lbwh_rectangle_filled")
    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw._entity_batch.draw_entities")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    @patch("pathwise.map.draw_arrow")
    @patch("pathwise.map_visuals.draw_baked_map")
    def test_draw_round_scene_after_start_round(
        self,
        _baked,
        _arrow,
        _rect_fill,
        _circle,
        _text_cls,
        _entity_batch,
        _outline,
        _bg_fill,
        _surface,
    ):
        from contextlib import nullcontext
        from pathwise.game_draw import draw_round_scene

        _surface.side_effect = lambda _layout: nullcontext()

        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = self.game.update_round_frame(KeyState())
        self.assertIsNotNone(draw_state)

        draw_round_scene(
            800,
            600,
            current_map=self.game.current_map,
            player=self.game.player,
            world_bounds=self.game.world_bounds,
            road_states=self.game.road_states,
            wall_rects=self.game.wall_rects,
            draw_sprites=draw_state["draw_sprites"],
            record_cars=draw_state["record_cars"],
            camera_offset=draw_state["camera_offset"],
            view_rect=draw_state["view_rect"],
            elapsed=draw_state["elapsed"],
            hud_lines=draw_state["hud_lines"],
            light_green_duration=self.game.LIGHT_GREEN_DURATION,
        )

    def test_launch_draw_path_with_baked_map_tiles(self):
        """Integration: start round and draw one frame (catches missing imports at draw time)."""
        import arcade
        from pathwise.game_draw import draw_round_scene

        profile = DifficultyProfile.for_menu_preset("normal")
        window = arcade.Window(800, 600, "launch test", visible=False)
        try:
            self.game.start_round(1, profile, "normal")
            baked = self.game.current_map.baked_layer
            self.assertIsNotNone(baked)
            self.assertGreater(len(baked.tiles), 0)

            draw_state = self.game.update_round_frame(KeyState())
            self.assertIsNotNone(draw_state)

            draw_round_scene(
                window.width,
                window.height,
                current_map=self.game.current_map,
                player=self.game.player,
                world_bounds=self.game.world_bounds,
                road_states=self.game.road_states,
                wall_rects=self.game.wall_rects,
                draw_sprites=draw_state["draw_sprites"],
                record_cars=draw_state["record_cars"],
                camera_offset=draw_state["camera_offset"],
                view_rect=draw_state["view_rect"],
                elapsed=draw_state["elapsed"],
                hud_lines=draw_state["hud_lines"],
                light_green_duration=self.game.LIGHT_GREEN_DURATION,
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
