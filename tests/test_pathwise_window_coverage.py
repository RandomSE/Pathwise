"""Coverage for pathwise.pathwise_window session flow and GamePlayView."""

import unittest
from unittest.mock import MagicMock, patch

import arcade

from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KEY_LEFT, KEY_UP
from pathwise.pathwise_window import GamePlayView, PathwiseWindow, run
from pathwise.pre_game import SessionConfig
from tests.arcade_harness import fake_arcade_window


class TestGamePlayView(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pathwise_window.arcade.set_background_color").start()

    def tearDown(self):
        patch.stopall()

    def _view(self) -> GamePlayView:
        view = GamePlayView()
        view.window = MagicMock(height=600)
        view.clear = MagicMock()
        return view

    def test_key_mapping(self):
        view = self._view()
        view.on_show_view()
        view.on_key_press(arcade.key.LEFT, 0)
        view.on_key_release(arcade.key.W, 0)
        self.assertTrue(view.keys.pressed(KEY_LEFT))
        self.assertFalse(view.keys.pressed(KEY_UP))

    @patch("main.update_round_frame", return_value={"hud_lines": []})
    @patch("main.draw_round_frame")
    @patch("main.round_active", True)
    @patch("main.app_running", True)
    @patch("main.ENABLE_PERF_PROFILE", False)
    def test_update_and_draw_active_round(self, _draw, update):
        view = self._view()
        view.on_update(1 / 60)
        update.assert_called_once()
        view._draw_state = {"hud_lines": []}
        view.on_draw()

    @patch("main.round_active", False)
    @patch("main.app_running", False)
    def test_round_complete_callback_once(self):
        view = self._view()
        cb = MagicMock()
        view._on_round_complete = cb
        view.on_update(1 / 60)
        view.on_update(1 / 60)
        cb.assert_called_once()

    @patch("main.draw_round_frame")
    @patch("main.ENABLE_PERF_PROFILE", True)
    @patch("main.perf_profiler")
    def test_draw_with_perf_profile(self, profiler, _draw):
        view = self._view()
        view._draw_state = {"hud_lines": []}
        view.on_draw()
        profiler.finish_draw.assert_called_once()


class TestPathwiseWindowFlow(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch("pathwise.pre_game.arcade.Text", return_value=MagicMock(draw=MagicMock())).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def _window(self) -> PathwiseWindow:
        window = PathwiseWindow.__new__(PathwiseWindow)
        window._auto_close_seconds = None
        window._elapsed = 0.0
        window._smoke_mode = False
        window._config = None
        window._base_profile = None
        window._round_index = 1
        window._outcomes = []
        window.show_view = MagicMock()
        window.closed = False
        return window

    def test_smoke_auto_close(self):
        window = self._window()
        window._auto_close_seconds = 1.0
        with patch("arcade.close_window") as close:
            window.on_update(1.1)
            close.assert_called_once()

    @patch("main.save_session_log", return_value="logs_dashboard.html")
    @patch("main.session_num_rounds", 1)
    @patch("main.session_base_seed", 42)
    @patch("main.round_results", [{"outcome": "success"}])
    def test_finish_session(self, _save):
        window = self._window()
        window._outcomes = ["success"]
        window._config = SessionConfig(preset="normal")
        window._finish_session()
        window.show_view.assert_called()

    @patch("main.round_results", [])
    @patch("arcade.close_window")
    def test_finish_session_no_results(self, close):
        window = self._window()
        window._finish_session()
        close.assert_called_once()

    @patch("main.app_running", False)
    @patch("arcade.close_window")
    def test_on_round_done_closes_when_not_running(self, close):
        window = self._window()
        window._on_round_done()
        close.assert_called_once()

    @patch("main.app_running", True)
    @patch("main.round_results", [{"outcome": "collision"}])
    @patch("main.session_num_rounds", 3)
    def test_on_round_done_between_rounds(self):
        window = self._window()
        window._round_index = 1
        window._config = SessionConfig(preset="normal")
        window._on_round_done()
        self.assertEqual(window._outcomes, ["collision"])
        window.show_view.assert_called()

    @patch("main.start_round")
    @patch("main.session_num_rounds", 2)
    def test_begin_round_and_next(self, start_round):
        window = self._window()
        window._config = SessionConfig(preset="easy")
        window._base_profile = DifficultyProfile.for_menu_preset("easy")
        window._begin_round()
        window._next_round()
        self.assertEqual(window._round_index, 2)
        self.assertEqual(start_round.call_count, 2)

    @patch("main.car_diagnostics")
    @patch("main.perf_profiler")
    @patch("main.ENABLE_PERF_PROFILE", True)
    @patch("main.start_round")
    @patch("main.session_num_rounds", 1)
    @patch("main.session_base_seed", 1)
    @patch("main.session_seed_source", "menu")
    @patch("main.session_use_adaptive_map", False)
    @patch("main.round_results", [])
    def test_on_pre_game_done_starts_session(self, start_round, profiler, diag):
        window = self._window()
        config = SessionConfig(preset="normal", num_rounds=1, seed=5)
        window._on_pre_game_done(config)
        diag.begin_session.assert_called_once()
        profiler.begin_session.assert_called_once()
        start_round.assert_called_once()

    @patch("arcade.close_window")
    def test_on_pre_game_cancel(self, close):
        window = self._window()
        window._on_pre_game_done(None)
        close.assert_called_once()

    @patch("main.app_running", True)
    @patch("main.start_round")
    def test_start_round_play(self, _start):
        window = self._window()
        window._start_round_play()
        window.show_view.assert_called()

    @patch("pathwise.pathwise_window.PathwiseWindow")
    def test_run_helper(self, window_cls):
        inst = MagicMock()
        window_cls.return_value = inst
        run(auto_close_seconds=0.5)
        window_cls.assert_called_once_with(auto_close_seconds=0.5)
        inst.run.assert_called_once()

    def test_run_smoke_mode_short_circuits_menu(self):
        w = PathwiseWindow.__new__(PathwiseWindow)
        w._smoke_mode = True
        with patch("arcade.Window.run") as super_run:
            PathwiseWindow.run(w)
            super_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
