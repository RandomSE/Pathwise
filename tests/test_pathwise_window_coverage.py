"""Coverage for pathwise.pathwise_window session flow and GamePlayView."""

import unittest
from unittest.mock import MagicMock, patch

import arcade

from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KEY_LEFT, KEY_UP
from pathwise.pathwise_window import GamePlayView, PathwiseWindow, run
from pathwise import pre_game
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
        view.window = MagicMock(width=800, height=600)
        view.clear = MagicMock()
        view._sync_display_layout()
        return view

    def test_key_mapping(self):
        view = self._view()
        # Do not call on_show_view: it prewarms GPU and may run a live sim frame.
        view.on_key_press(arcade.key.LEFT, 0)
        view.on_key_release(arcade.key.W, 0)
        self.assertTrue(view.keys.pressed(KEY_LEFT))
        self.assertFalse(view.keys.pressed(KEY_UP))

    @patch("main.update_round_frame", return_value={"hud_lines": []})
    @patch("main.draw_round_frame")
    @patch("main.round_active", True)
    @patch("main.app_running", True)
    @patch("main.ENABLE_PERF_PROFILE", False)
    @patch.object(GamePlayView, "_fps_tracker_instance")
    def test_update_and_draw_active_round(self, fps_tracker, _draw, update):
        fps_tracker.return_value.hud_line.return_value = "FPS: 60"
        view = self._view()
        view.on_update(1 / 60)
        update.assert_called_once_with(view.keys)
        view._draw_state = {"hud_lines": []}
        view.on_draw()
        _draw.assert_called_once_with(
            800,
            600,
            {"hud_lines": ["FPS: 60"]},
            display_layout=view._display_layout,
        )

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
        window._pending_config = None
        window._modifiers_from_recruiter = False
        window._disclaimer_accepted = False
        window._disclaimer_return_to = "candidate"
        window._base_profile = None
        window._round_index = 1
        window._outcomes = []
        window._seed_text = ""
        window._recruiter_generated_text = ""
        window._recruiter_record = None
        window._recruiter_session_token = None
        window._recruiter_execute = None
        window._notify_recruiter = None
        window._notify_send = None
        window.show_view = MagicMock()
        window.closed = False
        window.set_update_rate = MagicMock()
        window.set_draw_rate = MagicMock()
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
    @patch("pathwise.pathwise_window.resolve_candidate_play_seed", return_value=(5, "menu", False))
    def test_on_pre_game_done_starts_session(self, resolve_seed, start_round, profiler, diag):
        window = self._window()
        window._disclaimer_accepted = True
        config = SessionConfig(preset="normal", num_rounds=1, seed=5)
        window._on_pre_game_done(config)
        resolve_seed.assert_called_once_with(5)
        diag.begin_session.assert_called_once()
        profiler.begin_session.assert_called_once()
        start_round.assert_called_once()

    @patch("arcade.close_window")
    def test_on_pre_game_cancel(self, close):
        window = self._window()
        window._on_pre_game_done(None)
        close.assert_called_once()

    def test_pre_game_done_without_disclaimer_blocks_start(self):
        window = self._window()
        config = SessionConfig(preset="normal", num_rounds=1, seed=5)
        with patch.object(window, "_commit_session_start") as commit:
            window._on_pre_game_done(config)
            commit.assert_not_called()
        self.assertIs(window._pending_config, config)
        shown = window.show_view.call_args.args[0]
        self.assertIsInstance(shown, pre_game.DisclaimerView)

    def test_recruiter_start_without_disclaimer_blocks_start(self):
        window = self._window()
        config = SessionConfig(preset="hard", num_rounds=1, seed=9, audience="recruiter")
        with patch.object(window, "_commit_session_start") as commit:
            window._on_recruiter_start(config)
            commit.assert_not_called()
        shown = window.show_view.call_args.args[0]
        self.assertIsInstance(shown, pre_game.DisclaimerView)
        self.assertEqual(window._disclaimer_return_to, "recruiter")

    @patch("main.car_diagnostics")
    @patch("main.perf_profiler")
    @patch("main.ENABLE_PERF_PROFILE", False)
    @patch("main.start_round")
    @patch("main.session_num_rounds", 1)
    @patch("main.session_base_seed", 1)
    @patch("main.session_seed_source", "menu")
    @patch("main.session_use_adaptive_map", False)
    @patch("main.round_results", [])
    @patch("pathwise.pathwise_window.resolve_candidate_play_seed", return_value=(5, "menu", False))
    def test_disclaimer_agree_then_starts_session(self, resolve_seed, start_round, _profiler, diag):
        window = self._window()
        config = SessionConfig(preset="normal", num_rounds=1, seed=5)
        window._on_pre_game_done(config)
        start_round.assert_not_called()
        window._on_disclaimer_agreed()
        self.assertTrue(window._disclaimer_accepted)
        resolve_seed.assert_called_once_with(5)
        diag.begin_session.assert_called_once()
        start_round.assert_called_once()

    @patch("main.app_running", True)
    @patch("main.round_results", [{"outcome": "trip"}])
    @patch("main.session_num_rounds", 1)
    def test_trip_shows_notice_before_round_over(self):
        window = self._window()
        window._round_index = 1
        window._config = SessionConfig(preset="normal")
        with patch.object(window, "_finish_session") as finish:
            window._on_round_done()
            finish.assert_not_called()
        self.assertEqual(window._outcomes, ["trip"])
        notice = window.show_view.call_args.args[0]
        self.assertIsInstance(notice, pre_game.MessageView)
        self.assertEqual(notice.title, pre_game.TRIP_NOTICE_TITLE)
        window.show_view.reset_mock()
        with patch("main.save_session_log", return_value="dash.html"):
            with patch("main.session_base_seed", 1):
                with patch("main.round_results", [{"outcome": "trip", "session": {}}]):
                    # After notice, continue into session complete.
                    window._continue_after_round_outcome()
        shown = window.show_view.call_args.args[0]
        self.assertIsInstance(shown, pre_game.MessageView)
        self.assertIn("Tripped", shown.title)

    @patch("main.app_running", True)
    @patch("main.start_round")
    def test_start_round_play(self, _start):
        window = self._window()
        import main as game

        previous = game.start_time
        try:
            with patch("time.time", return_value=1234.5):
                window._start_round_play()
            self.assertEqual(game.start_time, 1234.5)
        finally:
            game.start_time = previous
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

    def test_candidate_to_recruiter_and_back(self):
        from pathwise.recruiter_accounts import RecruiterRecord
        from pathwise.recruiter_auth_views import RecruiterEnvSetupView, RecruiterLoginView

        window = self._window()
        window._show_candidate_home()
        candidate = window.show_view.call_args.args[0]
        self.assertIsInstance(candidate, pre_game.CandidateHomeView)
        with patch("pathwise.runtime_paths.turso_ready", return_value=False):
            candidate._on_configure("seed-from-candidate")
        setup = window.show_view.call_args.args[0]
        self.assertIsInstance(setup, RecruiterEnvSetupView)
        self.assertEqual(window._seed_text, "seed-from-candidate")
        self.assertFalse(window.recruiter_session_active())
        with patch("pathwise.runtime_paths.turso_ready", return_value=True):
            window._show_recruiter_login()
        login = window.show_view.call_args.args[0]
        self.assertIsInstance(login, RecruiterLoginView)
        record = RecruiterRecord(
            id="d" * 32,
            email="ok@example.com",
            billing_date=None,
            active=1,
            trial_active=0,
            billing_exempt=1,
            tier="basic",
            company=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        window._on_recruiter_authenticated(record, "token-1")
        recruiter = window.show_view.call_args.args[0]
        self.assertIsInstance(recruiter, pre_game.RecruiterConfigView)
        self.assertTrue(window.recruiter_session_active())
        self.assertTrue(window.recruiter_can_generate_codes())
        recruiter._on_back("generated-99")
        self.assertEqual(window._seed_text, "generated-99")
        returned = window.show_view.call_args.args[0]
        self.assertIsInstance(returned, pre_game.CandidateHomeView)
        self.assertEqual(returned.seed_text, "generated-99")
        candidate2 = returned
        candidate2._on_configure("again")
        skipped = window.show_view.call_args.args[0]
        self.assertIsInstance(skipped, pre_game.RecruiterConfigView)

    @patch("main.car_diagnostics")
    @patch("main.perf_profiler")
    @patch("main.ENABLE_PERF_PROFILE", False)
    @patch("main.start_round")
    @patch("main.session_num_rounds", 1)
    @patch("main.session_base_seed", 1)
    @patch("main.session_seed_source", "menu")
    @patch("main.session_use_adaptive_map", False)
    @patch("main.round_results", [])
    @patch("pathwise.pathwise_window.resolve_candidate_play_seed", return_value=(50, "menu", False))
    def test_recruiter_start_starts_session(self, _resolve, start_round, _profiler, _diag):
        window = self._window()
        window._disclaimer_accepted = True
        config = SessionConfig(preset="hard", num_rounds=3, seed=50)
        window._on_recruiter_start(config)
        start_round.assert_called_once()
        self.assertEqual(window._config.preset, "hard")
        self.assertEqual(window._config.num_rounds, 3)

    def test_recruiter_finish_session_offers_open_dashboard(self):
        import main as game

        window = self._window()
        window._outcomes = ["success"]
        window._config = SessionConfig(preset="normal", audience="recruiter")
        game.round_results = [{"outcome": "success"}]
        game.session_num_rounds = 1
        game.session_base_seed = 7
        game.session_audience = "recruiter"
        window._notify_recruiter = MagicMock()
        shown = {}

        def capture(view):
            shown["view"] = view

        window.show_view = capture
        with patch.object(game, "save_session_log", return_value="logs_dashboard.html"):
            window._finish_session()
        view = shown["view"]
        self.assertIn("Dashboard:", view.accent)
        self.assertEqual(view.action_label, "Open dashboard")
        self.assertTrue(view.dashboard_path)

    def test_setup_from_config_shows_env_view(self):
        from pathwise.recruiter_auth_views import RecruiterEnvSetupView

        window = self._window()
        window._recruiter_generated_text = "123"
        window._show_recruiter_setup_from_config()
        view = window.show_view.call_args.args[0]
        self.assertIsInstance(view, RecruiterEnvSetupView)


if __name__ == "__main__":
    unittest.main()
