"""Supersampled render surface, entity batching, display-matched FBO policy."""

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
    render_supersample,
)
from pathwise.render_budget import shared_render_budget
from pathwise.viewport import DisplayLayout


class TestDisplayMatchedFboPolicy(unittest.TestCase):
    def test_identity_window_uses_sim_resolution(self):
        layout = DisplayLayout.fit_window(800, 600)
        self.assertEqual(fixed_fbo_pixel_size(layout), (800, 600))
        self.assertEqual(fixed_fbo_render_multiplier(layout), 1.0)

    def test_1080p_fbo_uses_fixed_internal_resolution(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        fw, fh = fixed_fbo_pixel_size(layout)
        self.assertEqual((fw, fh), (FIXED_FBO_WIDTH, FIXED_FBO_HEIGHT))
        self.assertAlmostEqual(fixed_fbo_render_multiplier(layout), 1.5, places=1)

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


class TestGameplaySurface(unittest.TestCase):
    def test_fbo_size_fixed_at_1080p(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        surface = GameplaySurface()
        self.assertEqual(
            surface.fbo_pixel_size(layout),
            (FIXED_FBO_WIDTH, FIXED_FBO_HEIGHT),
        )

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
