"""GPU viewport draw path and layout caching."""

import unittest
from unittest.mock import MagicMock, patch

from pathwise.viewport import DisplayLayout, gameplay_draw_surface


class TestGameplayDrawSurface(unittest.TestCase):
    def test_identity_layout_sets_sim_projection(self):
        import arcade
        from pyglet.math import Mat4

        window = arcade.Window(800, 600, visible=False)
        try:
            layout = DisplayLayout.fit_window(800, 600)
            saved_viewport = window.viewport
            saved_projection = window.projection
            with patch("arcade.draw_lbwh_rectangle_filled") as fill:
                with gameplay_draw_surface(layout):
                    self.assertEqual(
                        window.projection,
                        Mat4.orthogonal_projection(0, 800, 0, 600, -8192, 8192),
                    )
            self.assertEqual(fill.call_count, 1)
            self.assertEqual(window.viewport, saved_viewport)
            self.assertEqual(window.projection, saved_projection)
        finally:
            window.close()

    def test_scaled_layout_uses_supersampled_fbo(self):
        import arcade

        window = arcade.Window(1920, 1080, visible=False)
        try:
            saved_viewport = window.viewport
            saved_projection = window.projection
            layout = DisplayLayout.fit_window(1920, 1080)
            with patch("arcade.draw_lbwh_rectangle_filled"):
                with gameplay_draw_surface(layout):
                    self.assertEqual(window.viewport[2], 1600)
                    self.assertEqual(window.viewport[3], 1200)
                from pathwise.gameplay_framebuffer import shared_gameplay_surface

                self.assertIsNotNone(shared_gameplay_surface()._blit_geo)
            self.assertEqual(window.viewport, saved_viewport)
            self.assertEqual(window.projection, saved_projection)
        finally:
            window.close()


class TestGamePlayViewLayoutCache(unittest.TestCase):
    def test_display_layout_cached_until_resize(self):
        from unittest.mock import patch

        from pathwise.pathwise_window import GamePlayView
        from tests.arcade_harness import fake_arcade_window

        with patch("arcade.get_window", return_value=fake_arcade_window()):
            view = GamePlayView()
            view.window = MagicMock(width=1920, height=1080)
            view._sync_display_layout()
            first = view._display_layout
            view._sync_display_layout()
            self.assertIs(view._display_layout, first)
            view.on_resize(1280, 720)
            self.assertIsNot(view._display_layout, first)
            self.assertEqual(view._layout_size, (1280, 720))


if __name__ == "__main__":
    unittest.main()
