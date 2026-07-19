"""Tests for mandatory safety DisclaimerView."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import arcade

from pathwise.pre_game import (
    DISCLAIMER_BODY,
    DISCLAIMER_TITLE,
    DisclaimerView,
)
from tests.arcade_harness import fake_arcade_window


class TestDisclaimerView(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch("pathwise.pre_game.arcade.Text", return_value=MagicMock(draw=MagicMock())).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def test_agree_disabled_until_checkbox(self):
        agree = MagicMock()
        back = MagicMock()
        view = DisclaimerView(on_agree=agree, on_back=back)
        view.window = MagicMock(width=800, height=600)
        view.on_show_view()
        view.on_key_press(arcade.key.ENTER, 0)
        agree.assert_not_called()
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertTrue(view.agreed)
        view.on_key_press(arcade.key.ENTER, 0)
        agree.assert_called_once()

    def test_back_without_accept(self):
        agree = MagicMock()
        back = MagicMock()
        view = DisclaimerView(on_agree=agree, on_back=back)
        view.window = MagicMock(width=800, height=600)
        view.on_show_view()
        view.on_key_press(arcade.key.ESCAPE, 0)
        back.assert_called_once()
        agree.assert_not_called()

    def test_disclaimer_copy_mentions_simulation_and_highways(self):
        self.assertEqual(DISCLAIMER_TITLE, "Safety disclaimer")
        lowered = DISCLAIMER_BODY.lower()
        self.assertIn("simulation", lowered)
        self.assertIn("highway", lowered)
        self.assertIn("real world", lowered.replace("-", " "))

    def test_draw_smoke(self):
        view = DisclaimerView()
        view.window = MagicMock(width=800, height=600)
        view.window.ctx = MagicMock(scissor=None)
        view.on_show_view()
        view.on_draw()

    def test_checkbox_sits_below_body_region(self):
        view = DisclaimerView()
        view.window = MagicMock(width=800, height=900)
        view.window.ctx = MagicMock(scissor=None)
        view.on_show_view()
        h = view.window.height
        # Body floor (Arcade Y) stays above checkbox top (converted to Arcade Y).
        checkbox_arcade_top = h - view.checkbox_rect.top
        self.assertGreaterEqual(view._body_floor_ay, checkbox_arcade_top + 20)
        self.assertGreater(view._body_top_ay, view._body_floor_ay)
        # y-down control order: checkbox, then Agree, then Back toward bottom.
        self.assertLess(view.checkbox_rect.top, view.agree_rect.top)
        self.assertLess(view.agree_rect.top, view.back_rect.top)


if __name__ == "__main__":
    unittest.main()
