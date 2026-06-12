"""Unit tests for pathwise.pre_game menu views and blocking runners."""

import unittest
from unittest.mock import MagicMock, patch

import arcade

from pathwise.geom import Rect
from pathwise.pre_game import (
    DIFFICULTY_PRESETS,
    MessageView,
    PreGameMenuView,
    SessionConfig,
    _parse_seed_text,
    run_between_rounds,
    run_pre_game_menu,
    run_round_intro,
    run_session_complete,
)
from tests.arcade_harness import fake_arcade_window


class ArcadeMenuTestCase(unittest.TestCase):
    def setUp(self):
        self._get_window = patch("arcade.get_window", return_value=fake_arcade_window())
        self._set_bg = patch("pathwise.pre_game.arcade.set_background_color")
        self._text = patch("pathwise.pre_game.arcade.Text", return_value=MagicMock(draw=MagicMock()))
        self._fill = patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled")
        self._outline = patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline")
        self._get_window.start()
        self._set_bg.start()
        self._text.start()
        self._fill.start()
        self._outline.start()

    def tearDown(self):
        patch.stopall()


class TestParseSeedText(unittest.TestCase):
    def test_delegates_to_session_seed(self):
        self.assertIsNone(_parse_seed_text(""))
        self.assertEqual(_parse_seed_text("42"), 42)


class TestPreGameMenuView(ArcadeMenuTestCase):
    def test_layout_and_draw(self):
        view = PreGameMenuView()
        view.on_show_view()
        self.assertEqual(len(view.preset_rects), len(DIFFICULTY_PRESETS))
        view.on_draw()
        view.num_rounds = 3
        view.on_draw()

    def test_mouse_selects_preset_and_rounds(self):
        view = PreGameMenuView()
        view.on_show_view()
        easy_rect = view.preset_rects["easy"]
        view.on_mouse_press(easy_rect.centerx, view.window.height - easy_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.selected_preset, "easy")
        view.on_mouse_press(view.minus_rect.centerx, view.window.height - view.minus_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.num_rounds, 1)
        view.on_mouse_press(view.plus_rect.centerx, view.window.height - view.plus_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.num_rounds, 2)
        view.on_mouse_press(view.start_rect.centerx, view.window.height - view.start_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertTrue(view._done)
        self.assertIsInstance(view._result, SessionConfig)

    def test_keyboard_seed_edit_and_escape(self):
        view = PreGameMenuView()
        view.on_show_view()
        view.seed_editing = True
        view.on_text("1")
        view.on_text("2")
        view.on_key_press(arcade.key.BACKSPACE, 0)
        self.assertEqual(view.seed_text, "1")
        view.on_key_press(arcade.key.ENTER, 0)
        self.assertFalse(view.seed_editing)
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertTrue(view._done)
        self.assertIsNone(view._result)

    def test_enter_starts_session(self):
        view = PreGameMenuView()
        view.on_show_view()
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertEqual(view._result.preset, "normal")

    def test_finish_config_with_seed(self):
        view = PreGameMenuView()
        view.seed_text = "99"
        cfg = view._finish_config()
        self.assertEqual(cfg.seed, 99)

    def test_non_left_mouse_ignored(self):
        view = PreGameMenuView()
        view.on_show_view()
        view.on_mouse_press(0, 0, arcade.MOUSE_BUTTON_RIGHT, 0)
        self.assertFalse(view._done)

    def test_draw_button_variants(self):
        view = PreGameMenuView()
        view.on_show_view()
        r = Rect(10, 10, 40, 20)
        view._draw_button(r, "x", 12, selected=True)
        view._draw_button(r, "x", 12, primary=True)
        view._draw_button(r, "", 12, border=(1, 2, 3))


class TestMessageView(ArcadeMenuTestCase):
    def test_auto_advance(self):
        view = MessageView(title="Hi", subtitle="Sub", accent="Go", auto_advance_s=0.5)
        view.on_show_view()
        view.on_update(0.6)
        self.assertTrue(view._done)

    def test_manual_advance(self):
        view = MessageView(title="Hi")
        view.on_key_press(arcade.key.A, 0)
        self.assertTrue(view._done)
        view = MessageView(title="Hi")
        view.on_mouse_press(1, 1, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertTrue(view._done)

    def test_draw_minimal(self):
        view = MessageView(title="Only")
        view.on_draw()


class TestBlockingRunners(ArcadeMenuTestCase):
    @patch("pathwise.pre_game.pump_frame")
    def test_run_pre_game_menu(self, pump):
        window = MagicMock()
        window.closed = False
        captured = {}

        def show_view(view):
            captured["view"] = view

        window.show_view = show_view

        def finish_pump(_window):
            captured["view"].finish(SessionConfig(preset="hard", num_rounds=2, seed=7))

        pump.side_effect = finish_pump
        result = run_pre_game_menu(window)
        self.assertEqual(result.preset, "hard")
        self.assertEqual(result.num_rounds, 2)

    @patch("pathwise.pre_game.pump_frame")
    def test_run_round_intro(self, pump):
        from map_generation.difficulty import DifficultyProfile

        window = MagicMock()
        window.closed = False
        profile = DifficultyProfile.for_menu_preset("normal")

        def show_view(view):
            view.finish(True)

        window.show_view = show_view
        self.assertTrue(run_round_intro(window, 2, 3, profile))

    @patch("pathwise.pre_game.pump_frame")
    def test_run_between_rounds(self, pump):
        window = MagicMock()
        window.closed = False

        def show_view(view):
            view.finish(True)

        window.show_view = show_view
        self.assertTrue(run_between_rounds(window, 1, 3, "success"))
        self.assertTrue(run_between_rounds(window, 3, 3, "timeout"))

    @patch("pathwise.pre_game.pump_frame")
    def test_run_session_complete(self, pump):
        window = MagicMock()
        window.closed = False

        def show_view(view):
            view.finish(True)

        window.show_view = show_view
        run_session_complete(window, ["success", "collision"], 2, session_seed=123)


if __name__ == "__main__":
    unittest.main()
