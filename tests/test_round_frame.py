"""Direct unit tests for pathwise.round_frame."""

import time
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

    def test_large_wall_clock_gap_returns_quickly(self):
        """SyntheticClock leftover + real time.time() must not stall the suite."""
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.game._sim_clock_last = 0.0
        t0 = time.perf_counter()
        state = update_round_frame(KeyState())
        self.assertLess(time.perf_counter() - t0, 1.0)
        self.assertIsNotNone(state)

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

    def test_candidate_hud_hides_assessment_meta(self):
        """Candidates should not see route / risks / crossings / traffic / intensity."""
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.session_audience = "candidate"
        self.game.start_round(1, profile, "normal")
        self.game.reasonable_risk_events = 1
        self.game.risky_risk_events = 1
        draw_state = update_round_frame(KeyState())
        lines = draw_state["hud_lines"]
        joined = "\n".join(lines)
        self.assertTrue(any(line.startswith("Time left:") for line in lines))
        self.assertFalse(any("intensity" in line for line in lines))
        self.assertFalse(any(line.startswith("Route:") for line in lines))
        self.assertFalse(any(line.startswith("Crossings:") for line in lines))
        self.assertNotIn("traffic", joined)
        self.assertFalse(any(line.startswith("Risks:") for line in lines))

    def test_recruiter_hud_keeps_assessment_meta(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.session_audience = "recruiter"
        self.game.start_round(1, profile, "normal")
        self.game.reasonable_risk_events = 1
        draw_state = update_round_frame(KeyState())
        lines = draw_state["hud_lines"]
        self.assertTrue(any("intensity" in line for line in lines))
        self.assertTrue(any(line.startswith("Crossings:") for line in lines))
        self.assertTrue(any(line.startswith("Risks:") for line in lines))

    def test_car_update_branch_counters_cover_alive_fleet(self):
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        update_round_frame(KeyState())
        branches = getattr(self.game, "car_update_branches", {})
        for key in (
            "branch_cruise",
            "branch_far_skip",
            "branch_far_cruise_tick",
            "branch_near_skip",
            "branch_near_cruise_tick",
            "branch_full_update",
        ):
            self.assertIn(key, branches)
        alive = sum(1 for c in self.game.cars if c.alive())
        self.assertEqual(sum(branches.values()), alive)

    def test_far_offscreen_stride_tick_uses_cruise_not_full_update(self):
        from pathwise.car import Car

        profile = DifficultyProfile.for_menu_preset("hard")
        self.game.start_round(1, profile, "hard")
        player = self.game.player.rect
        probe = Car(
            player.centerx + 8000,
            player.centery + 8000,
            3.0,
            vertical=False,
            spawn_id=999001,
        )
        probe.current_speed = 2.0
        probe.speed = 2.0
        probe._turn_phase = "none"
        probe.turn_signal = 0
        probe._sync_collision_shell(force=True)
        self.game.cars.add(probe)
        update_calls = []
        cruise_calls = []
        orig_update = probe.update
        orig_cruise = probe.straight_cruise_update

        def spy_update(*args, **kwargs):
            update_calls.append(1)
            return orig_update(*args, **kwargs)

        def spy_cruise(*args, **kwargs):
            cruise_calls.append(1)
            return orig_cruise(*args, **kwargs)

        probe.update = spy_update
        probe.straight_cruise_update = spy_cruise
        for _ in range(12):
            update_round_frame(KeyState())
        self.assertEqual(len(update_calls), 0)
        self.assertGreater(len(cruise_calls), 0)

    def test_near_offscreen_stride_uses_cruise_not_full_update(self):
        from pathwise.car import Car
        from pathwise.sim_constants import SIM_UPDATE_VIEW_PAD

        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        draw_state = update_round_frame(KeyState())
        view_rect = draw_state["view_rect"]
        x = view_rect.right + min(80, max(24, SIM_UPDATE_VIEW_PAD // 4))
        y = view_rect.centery
        probe = Car(x, y, 3.0, vertical=False, spawn_id=999002)
        probe.current_speed = 2.0
        probe.speed = 2.0
        probe._turn_phase = "none"
        probe.turn_signal = 0
        probe._rect_in_intersection = lambda *args, **kwargs: False
        probe._approaching_or_in_intersection = lambda *args, **kwargs: False
        probe._sync_collision_shell(force=True)
        self.game.cars.add(probe)
        update_calls = []
        cruise_calls = []
        orig_update = probe.update
        orig_cruise = probe.straight_cruise_update

        def spy_update(*args, **kwargs):
            update_calls.append(1)
            return orig_update(*args, **kwargs)

        def spy_cruise(*args, **kwargs):
            cruise_calls.append(1)
            return orig_cruise(*args, **kwargs)

        probe.update = spy_update
        probe.straight_cruise_update = spy_cruise
        frames = 9
        for _ in range(frames):
            update_round_frame(KeyState())
        self.assertEqual(len(update_calls), 0)
        self.assertGreater(len(cruise_calls), 0)
        self.assertLess(len(cruise_calls), frames)


if __name__ == "__main__":
    unittest.main()
