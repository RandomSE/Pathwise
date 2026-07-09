"""GamePlayView injects FPS into HUD lines."""

import unittest
from unittest.mock import MagicMock, patch

from pathwise.pathwise_window import GamePlayView
from tests.arcade_harness import fake_arcade_window


class TestFpsHudOverlay(unittest.TestCase):
    @patch("main.draw_round_frame")
    def test_on_draw_prepends_fps_line(self, draw_round_frame):
        with patch("arcade.get_window", return_value=fake_arcade_window()):
            view = GamePlayView()
            view.window = MagicMock(width=1920, height=1080)
            view._draw_state = {"hud_lines": ["Time left: 030.0s"]}

            view.on_draw()

            draw_round_frame.assert_called_once()
            draw_state = draw_round_frame.call_args[0][2]
            self.assertTrue(draw_state["hud_lines"][0].startswith("FPS:"))
            self.assertEqual(draw_state["hud_lines"][1], "Time left: 030.0s")


if __name__ == "__main__":
    unittest.main()
