"""Supersampled render surface, entity batching, adaptive replay."""

import unittest
from unittest.mock import MagicMock, patch

from pathwise.geom import Rect
from pathwise.gameplay_framebuffer import render_supersample
from pathwise.viewport import DisplayLayout


class TestRenderSupersample(unittest.TestCase):
    def test_identity_window_uses_single_sample(self):
        layout = DisplayLayout.fit_window(800, 600)
        self.assertEqual(render_supersample(layout), 1)

    def test_fullscreen_uses_double_sample(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        self.assertEqual(render_supersample(layout), 2)

    def test_env_override(self):
        layout = DisplayLayout.fit_window(800, 600)
        with patch.dict("os.environ", {"PATHWISE_RENDER_SCALE": "3"}):
            self.assertEqual(render_supersample(layout), 3)


class TestGameplaySurface(unittest.TestCase):
    def test_fbo_size_scales_with_supersample(self):
        from pathwise.gameplay_framebuffer import GameplaySurface

        layout = DisplayLayout.fit_window(1920, 1080)
        surface = GameplaySurface()
        self.assertEqual(surface.fbo_pixel_size(layout), (1600, 1200))

    def test_blit_builds_geometry_on_first_frame(self):
        import arcade
        from unittest.mock import patch

        from pathwise.gameplay_framebuffer import reset_shared_gameplay_surface, shared_gameplay_surface
        from pathwise.viewport import gameplay_draw_surface

        window = arcade.Window(1920, 1080, visible=False)
        try:
            reset_shared_gameplay_surface()
            layout = DisplayLayout.fit_window(1920, 1080)
            surface = shared_gameplay_surface()
            with patch("arcade.draw_lbwh_rectangle_filled"):
                with gameplay_draw_surface(layout):
                    pass
            self.assertIsNotNone(surface._blit_geo)
        finally:
            window.close()


class TestAdaptiveReplaySampling(unittest.TestCase):
    def test_slow_frames_drop_capture_rate(self):
        from analytics.frame_recorder import (
            FIXED_SAMPLE_INTERVAL_FAST_S,
            FIXED_SAMPLE_INTERVAL_SLOW_S,
            FrameRecorder,
        )

        recorder = FrameRecorder(16)
        for _ in range(5):
            recorder.note_sim_frame_seconds(0.01)
        self.assertEqual(recorder.sample_interval_s, FIXED_SAMPLE_INTERVAL_FAST_S)
        for _ in range(4):
            recorder.note_sim_frame_seconds(0.025)
        self.assertEqual(recorder.sample_interval_s, FIXED_SAMPLE_INTERVAL_SLOW_S)


if __name__ == "__main__":
    unittest.main()
