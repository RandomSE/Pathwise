import unittest
from unittest.mock import MagicMock, patch

from pathwise.pathwise_window import PathwiseWindow


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
    def test_finish_session_saves_before_showing_view(self):
        import main as game

        window = PathwiseWindow.__new__(PathwiseWindow)
        window._outcomes = ["success"]
        game.round_results = [{"outcome": "success"}]
        game.session_num_rounds = 1
        game.session_base_seed = 42

        call_order: list[str] = []

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

        self.assertEqual(call_order, ["save", "show"])


if __name__ == "__main__":
    unittest.main()
