"""Headless draw-path performance regression at 1080p layout."""

import os
import time
import unittest

import arcade
import pytest

from map_generation.difficulty import DifficultyProfile
from pathwise.gameplay_framebuffer import reset_shared_gameplay_surface
from pathwise.input_keys import KeyState
from pathwise.viewport import DisplayLayout

DRAW_BUDGET_MS = 16.7
HEADLESS_WARMUP_DRAWS = 8
HEADLESS_SAMPLE_DRAWS = 20


class TestDrawPerfRegression(unittest.TestCase):
    def test_1080p_fbo_matches_dest_pixels(self):
        layout = DisplayLayout.fit_window(1920, 1080)
        from pathwise.gameplay_framebuffer import fixed_fbo_pixel_size

        self.assertEqual(fixed_fbo_pixel_size(layout), layout.dest_pixel_size())

    def _profile_draw_ms(self) -> list[float]:
        import main as game
        from pathwise.game_draw import draw_round_scene

        game.session_base_seed = 424242
        game.session_seed_source = "draw_perf"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True

        profile = DifficultyProfile.for_menu_preset("normal")
        from pathwise.game_draw import reset_overlay_text_pools

        reset_overlay_text_pools()
        window = arcade.Window(1920, 1080, visible=False)
        arcade.set_window(window)
        self.assertIs(arcade.get_window(), window)
        try:
            reset_shared_gameplay_surface()
            game.start_round(1, profile, "normal")
            draw_state = game.update_round_frame(KeyState())
            self.assertIsNotNone(draw_state)

            layout = DisplayLayout.fit_window(1920, 1080)
            from pathwise.gameplay_framebuffer import prewarm_draw_gpu_assets

            prewarm_draw_gpu_assets(layout)

            def draw_once():
                nonlocal draw_state
                draw_state = game.update_round_frame(KeyState())
                draw_round_scene(
                    window.width,
                    window.height,
                    current_map=game.current_map,
                    player=game.player,
                    world_bounds=game.world_bounds,
                    road_states=game.road_states,
                    wall_rects=game.wall_rects,
                    draw_sprites=draw_state["draw_sprites"],
                    record_cars=draw_state["record_cars"],
                    camera_offset=draw_state["camera_offset"],
                    view_rect=draw_state["view_rect"],
                    elapsed=draw_state["elapsed"],
                    hud_lines=draw_state["hud_lines"],
                    light_green_duration=game.LIGHT_GREEN_DURATION,
                    display_layout=layout,
                )

            for _ in range(HEADLESS_WARMUP_DRAWS):
                draw_once()

            samples_ms = []
            for _ in range(HEADLESS_SAMPLE_DRAWS):
                t0 = time.perf_counter()
                draw_once()
                samples_ms.append((time.perf_counter() - t0) * 1000.0)
            return samples_ms
        finally:
            window.close()

    @pytest.mark.needs_map_bake
    def test_headless_draw_warmup_stays_under_relaxed_budget(self):
        samples_ms = self._profile_draw_ms()
        avg_ms = sum(samples_ms) / len(samples_ms)
        self.assertLess(
            avg_ms,
            55.0,
            f"avg draw {avg_ms:.1f}ms still high after warmup (headless GL overhead)",
        )

    @pytest.mark.needs_map_bake
    @unittest.skipUnless(
        os.environ.get("PATHWISE_STRICT_DRAW_PERF") == "1",
        "60fps draw budget is GPU/driver sensitive; set PATHWISE_STRICT_DRAW_PERF=1 to enforce",
    )
    def test_headless_draw_60fps_budget_strict(self):
        samples_ms = self._profile_draw_ms()
        avg_ms = sum(samples_ms) / len(samples_ms)
        p95_ms = sorted(samples_ms)[int(len(samples_ms) * 0.95)]
        self.assertLess(avg_ms, DRAW_BUDGET_MS, f"avg draw {avg_ms:.1f}ms exceeds budget")
        self.assertLess(
            p95_ms,
            DRAW_BUDGET_MS * 1.35,
            f"p95 draw {p95_ms:.1f}ms too spiky for 60fps",
        )


if __name__ == "__main__":
    unittest.main()
