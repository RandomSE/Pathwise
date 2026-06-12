import unittest

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

if __name__ == "__main__":
    unittest.main()
