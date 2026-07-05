"""Fixed sim viewport and display scaling."""

import unittest

from pathwise import commonUtils
from pathwise.game_tuning import DEFAULT_TUNING
from pathwise.viewport import (
    DisplayLayout,
    camera_offset_for,
    normalize_viewport_size,
    sim_viewport_size,
    view_rect_for_camera,
)


class TestViewport(unittest.TestCase):
    def test_sim_viewport_is_design_resolution(self):
        self.assertEqual(sim_viewport_size(), (800, 600))

    def test_normalize_viewport_ignores_window_size(self):
        w, h = normalize_viewport_size(1920, 1080)
        self.assertEqual((w, h), (commonUtils.WIDTH, commonUtils.HEIGHT))

    def test_camera_offset_centers_player_in_sim_space(self):
        self.assertEqual(camera_offset_for(500, 400, 800, 600), (100, 100))

    def test_view_rect_matches_sim_viewport_plus_pad(self):
        pad = DEFAULT_TUNING.FRAME_RECORD_VIEW_PAD
        vw, vh = sim_viewport_size()
        cam = (10, 20)
        rect = view_rect_for_camera(cam, vw, vh)
        self.assertEqual(rect.x, cam[0] - pad)
        self.assertEqual(rect.y, cam[1] - pad)
        self.assertEqual(rect.width, vw + pad * 2)
        self.assertEqual(rect.height, vh + pad * 2)

    def test_display_layout_scales_uniformly_at_1080p(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        self.assertAlmostEqual(layout.scale, 1.8)
        self.assertAlmostEqual(layout.dest_width, 800 * 1.8)
        self.assertAlmostEqual(layout.dest_height, 600 * 1.8)
        self.assertAlmostEqual(layout.dest_left, (1920 - layout.dest_width) / 2)
        self.assertAlmostEqual(layout.dest_bottom, 0.0)

    def test_display_layout_identity_at_design_resolution(self):
        layout = DisplayLayout.fit_window(800, 600)
        self.assertAlmostEqual(layout.scale, 1.0)
        self.assertAlmostEqual(layout.dest_left, 0.0)
        self.assertAlmostEqual(layout.dest_bottom, 0.0)
        self.assertAlmostEqual(layout.dest_width, 800.0)
        self.assertAlmostEqual(layout.dest_height, 600.0)

    def test_display_layout_maps_sim_origin_to_dest_corner(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        self.assertEqual(layout.map_arcade_point(0, 0), (layout.dest_left, layout.dest_bottom))
        self.assertEqual(
            layout.map_arcade_point(800, 600),
            (layout.dest_left + layout.dest_width, layout.dest_bottom + layout.dest_height),
        )

    def test_update_round_frame_view_rect_fixed_regardless_of_window(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile
        from pathwise.input_keys import KeyState

        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        state = game.update_round_frame(KeyState())
        self.assertIsNotNone(state)
        vw, vh = sim_viewport_size()
        pad = DEFAULT_TUNING.FRAME_RECORD_VIEW_PAD
        self.assertEqual(state["view_rect"].width, vw + pad * 2)
        self.assertEqual(state["view_rect"].height, vh + pad * 2)


if __name__ == "__main__":
    unittest.main()
