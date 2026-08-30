"""Supersampled render surface, entity batching, display-matched FBO policy."""

import os
import unittest
from unittest.mock import patch

from pathwise.geom import Rect
from pathwise.gameplay_framebuffer import (
    FIXED_FBO_HEIGHT,
    FIXED_FBO_WIDTH,
    GameplaySurface,
    fixed_fbo_pixel_size,
    fixed_fbo_render_multiplier,
    fixed_sprite_bake_multiplier,
    present_uses_nearest,
    render_supersample,
    upscale_filter_mode,
)
from pathwise.render_budget import shared_render_budget
from pathwise.viewport import DisplayLayout


class TestDisplayMatchedFboPolicy(unittest.TestCase):
    def test_identity_window_uses_sim_resolution(self):
        layout = DisplayLayout.fit_window(800, 600)
        self.assertEqual(fixed_fbo_pixel_size(layout), (800, 600))
        self.assertEqual(fixed_fbo_render_multiplier(layout), 1.0)

    def test_720p_keeps_dest_native_one_to_one_present(self):
        """Small windows already 1:1 blit; do not drop them to 1x sim then upscale."""
        layout = DisplayLayout.fit_window(1280, 720)
        dw, dh = layout.dest_pixel_size()
        self.assertEqual(fixed_fbo_pixel_size(layout), (dw, dh))

    def test_1080p_fbo_matches_dest_for_one_to_one_present(self):
        """2x sim FBO (1200px) LINEAR-blit to 1080p at 0.9 makes bands race down the screen."""
        layout = DisplayLayout.fit_window(1920, 1080)
        fw, fh = fixed_fbo_pixel_size(layout)
        self.assertEqual((fw, fh), layout.dest_pixel_size())
        self.assertNotEqual((fw, fh), (FIXED_FBO_WIDTH, FIXED_FBO_HEIGHT))
        self.assertAlmostEqual(fixed_fbo_render_multiplier(layout), 1.8, places=1)

    def test_sprite_bake_locked_for_1080p(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        self.assertEqual(fixed_sprite_bake_multiplier(layout), 2)

    def test_sprite_bake_single_at_identity(self):
        layout = DisplayLayout.fit_window(800, 600)
        self.assertEqual(fixed_sprite_bake_multiplier(layout), 1)

    def test_render_budget_does_not_reduce_quality(self):
        budget = shared_render_budget()
        budget.reset()
        for _ in range(120):
            budget.note_frame_seconds(0.025)
        self.assertEqual(budget.multiplier, 1.0)

    def test_env_override(self):
        with patch.dict("os.environ", {"PATHWISE_RENDER_SCALE": "3"}):
            layout_scaled = DisplayLayout.fit_window(1920, 1080)
            self.assertEqual(render_supersample(layout_scaled), 3)

    def test_upscale_filter_defaults_to_auto(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PATHWISE_UPSCALE_FILTER", None)
            self.assertEqual(upscale_filter_mode(), "auto")

    def test_upscale_filter_smooth_opt_in(self):
        with patch.dict("os.environ", {"PATHWISE_UPSCALE_FILTER": "smooth"}):
            self.assertEqual(upscale_filter_mode(), "smooth")
            layout = DisplayLayout.fit_window(1280, 720)
            self.assertFalse(present_uses_nearest(layout))

    def test_upscale_filter_sharp_forces_nearest(self):
        with patch.dict("os.environ", {"PATHWISE_UPSCALE_FILTER": "sharp"}):
            self.assertEqual(upscale_filter_mode(), "sharp")
            layout = DisplayLayout.fit_window(1920, 1080)
            self.assertTrue(present_uses_nearest(layout))

    def test_1080p_auto_present_is_nearest_at_one_to_one(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PATHWISE_UPSCALE_FILTER", None)
            layout = DisplayLayout.fit_window(1920, 1080)
            fw, fh = fixed_fbo_pixel_size(layout)
            dw, dh = layout.dest_pixel_size()
            self.assertEqual((fw, fh), (dw, dh))
            self.assertTrue(present_uses_nearest(layout))

    def test_720p_auto_present_stays_nearest_at_one_to_one(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PATHWISE_UPSCALE_FILTER", None)
            layout = DisplayLayout.fit_window(1280, 720)
            self.assertTrue(present_uses_nearest(layout))


class TestGameplaySurface(unittest.TestCase):
    def test_fbo_size_matches_dest_at_1080p(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        surface = GameplaySurface()
        self.assertEqual(surface.fbo_pixel_size(layout), layout.dest_pixel_size())

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

    def test_capture_metadata_reports_median_gap(self):
        from analytics.frame_recorder import FrameRecorder

        recorder = FrameRecorder(16)
        player = Rect(0, 0, 20, 20)
        recorder.capture_start(0.0, player, [], [])
        recorder.capture(0.125, player, [], [], force=True, game_time=0.125)
        recorder.capture(0.25, player, [], [], force=True, game_time=0.25)
        meta = recorder.capture_metadata()
        self.assertAlmostEqual(meta["median_frame_gap_s"], 0.125, places=3)


if __name__ == "__main__":
    unittest.main()
