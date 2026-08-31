import os
import unittest
from unittest.mock import MagicMock, patch

from pathwise.pathwise_window import PathwiseWindow, vsync_enabled


class TestPathwiseWindowDraw(unittest.TestCase):
    def _bare_window(self) -> PathwiseWindow:
        window = PathwiseWindow.__new__(PathwiseWindow)
        window._cleared = False
        window.clear = lambda: setattr(window, "_cleared", True)
        return window

    def test_on_draw_skips_clear_when_view_active(self):
        window = self._bare_window()
        window._current_view = object()
        PathwiseWindow.on_draw(window)
        self.assertFalse(window._cleared)

    def test_on_draw_clears_when_no_view(self):
        window = self._bare_window()
        window._current_view = None
        PathwiseWindow.on_draw(window)
        self.assertTrue(window._cleared)


class TestFinishSessionOrder(unittest.TestCase):
    def _finish(self, window, call_order: list[str]):
        import main as game

        window._outcomes = ["success"]
        game.round_results = [{"outcome": "success"}]
        game.session_num_rounds = 1
        game.session_base_seed = 42

        with patch.object(
            game,
            "save_session_log",
            side_effect=lambda: call_order.append("save") or "logs_dashboard.html",
        ), patch.object(
            PathwiseWindow,
            "show_view",
            side_effect=lambda *_args, **_kwargs: call_order.append("show"),
        ), patch("pathwise.pre_game.MessageView", MagicMock()):
            window._finish_session()

    def test_finish_session_saves_before_showing_view(self):
        window = PathwiseWindow.__new__(PathwiseWindow)
        window._config = None
        window._recruiter_record = None
        window._recruiter_session_token = None
        window._recruiter_execute = None
        call_order: list[str] = []
        notify_calls: list[object] = []

        def _notify(**kwargs):
            notify_calls.append(kwargs)
            call_order.append("notify")

        window._notify_recruiter = _notify
        self._finish(window, call_order)
        self.assertEqual(call_order, ["save", "notify", "show"])
        self.assertEqual(notify_calls[0]["dashboard_path"], "logs_dashboard.html")

    def test_finish_session_self_play_skips_notify(self):
        from pathwise.pre_game import SessionConfig
        from pathwise.recruiter_accounts import apply_recruiter_schema, create_recruiter
        from pathwise.recruiter_seeds import register_recruiter_seed
        from pathwise.session_seed import encode_recruiter_seed
        from tests.test_recruiter_accounts import FakePipeline

        db = FakePipeline()
        self.addCleanup(db.conn.close)
        apply_recruiter_schema(execute=db.execute)
        owner = create_recruiter("owner@example.com", "password1", execute=db.execute)
        encoded = encode_recruiter_seed(7, "normal", 1)
        register_recruiter_seed(encoded, owner.id, execute=db.execute)

        window = PathwiseWindow.__new__(PathwiseWindow)
        window._config = SessionConfig(
            preset="normal",
            recruiter_seed_code=encoded,
            candidate_label=owner.email,
        )
        window._recruiter_record = owner
        window._recruiter_session_token = "token"
        window._recruiter_execute = db.execute
        sent: list[dict] = []
        window._notify_send = lambda **payload: sent.append(payload)
        call_order: list[str] = []
        self._finish(window, call_order)
        self.assertEqual(call_order, ["save", "show"])
        self.assertEqual(sent, [])


class TestVsyncPolicy(unittest.TestCase):
    def test_play_defaults_to_vsync_on(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PATHWISE_VSYNC", None)
            self.assertTrue(vsync_enabled(smoke_mode=False))

    def test_smoke_defaults_to_vsync_off(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PATHWISE_VSYNC", None)
            self.assertFalse(vsync_enabled(smoke_mode=True))

    def test_env_off_wins(self):
        with patch.dict("os.environ", {"PATHWISE_VSYNC": "0"}):
            self.assertFalse(vsync_enabled(smoke_mode=False))

    def test_env_on_wins_in_smoke(self):
        with patch.dict("os.environ", {"PATHWISE_VSYNC": "1"}):
            self.assertTrue(vsync_enabled(smoke_mode=True))


if __name__ == "__main__":
    unittest.main()
