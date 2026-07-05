"""Unit tests for pathwise.pre_game menu views and blocking runners."""

import unittest
from unittest.mock import MagicMock, patch

import arcade

from pathwise.geom import Rect
from pathwise.pre_game import (
    DIFFICULTY_PRESETS,
    CandidateHomeView,
    MessageView,
    RecruiterConfigView,
    SessionConfig,
    _parse_seed_text,
    build_candidate_session_config,
    run_between_rounds,
    run_pre_game_menu,
    run_round_intro,
    run_session_complete,
)
from pathwise.session_seed import encode_recruiter_seed
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


class TestCandidateHomeView(ArcadeMenuTestCase):
    def test_layout_and_draw(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.on_draw()
        view.seed_text = "bad!"
        view.on_draw()

    def test_play_with_valid_seed(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "42"
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertTrue(view._done)
        self.assertEqual(view._result, build_candidate_session_config("42"))

    def test_play_disabled_for_invalid_seed(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "12x"
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertFalse(view._done)

    def test_configure_callback(self):
        view = CandidateHomeView(on_configure=MagicMock())
        view.on_show_view()
        view.seed_text = "7"
        view.on_mouse_press(
            view.configure_rect.centerx,
            view.window.height - view.configure_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        view._on_configure.assert_called_once_with("7")

    def test_keyboard_seed_edit_and_escape_quits(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_editing = True
        view.on_text("1")
        view.on_text("x")
        self.assertEqual(view.seed_text, "1x")
        view.on_key_press(arcade.key.BACKSPACE, 0)
        self.assertEqual(view.seed_text, "1")
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertFalse(view.seed_editing)
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertTrue(view._done)
        self.assertIsNone(view._result)

    def test_enter_starts_when_valid(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "5"
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertEqual(view._result.preset, "normal")
        self.assertEqual(view._result.num_rounds, 1)

    def test_paste_from_clipboard(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.window.get_clipboard_text = MagicMock(return_value="  8123456 \n")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.seed_text, "8123456")
        self.assertTrue(view.seed_editing)

    def test_paste_button(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.window.get_clipboard_text = MagicMock(return_value="9988776655")
        view.on_mouse_press(
            view.paste_rect.centerx,
            view.window.height - view.paste_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(view.seed_text, "9988776655")
        self.assertTrue(view.seed_editing)


class TestRecruiterConfigView(ArcadeMenuTestCase):
    def test_layout_and_draw(self):
        view = RecruiterConfigView()
        view.on_show_view()
        self.assertEqual(len(view.preset_rects), len(DIFFICULTY_PRESETS))
        view.on_draw()
        view.num_rounds = 3
        view.on_draw()

    def test_layout_has_no_vertical_overlap(self):
        from pathwise.menu_layout import layout_recruiter, layout_vertical_spans, layouts_do_not_overlap

        layout = layout_recruiter(800, 600, num_rounds=3, show_stale_hint=True)
        self.assertTrue(layouts_do_not_overlap(layout_vertical_spans(layout), window_height=600))
        self.assertEqual(layout.copy_rect.top, layout.seed_display_rect.top)

    def test_mouse_selects_preset_and_rounds(self):
        view = RecruiterConfigView()
        view.on_show_view()
        easy_rect = view.preset_rects["easy"]
        view.on_mouse_press(easy_rect.centerx, view.window.height - easy_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.selected_preset, "easy")
        view.on_mouse_press(view.minus_rect.centerx, view.window.height - view.minus_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.num_rounds, 1)
        view.on_mouse_press(view.plus_rect.centerx, view.window.height - view.plus_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertEqual(view.num_rounds, 2)

    def test_back_invokes_callback_with_seed(self):
        back_cb = MagicMock()
        encoded = encode_recruiter_seed(99, "normal", 1)
        view = RecruiterConfigView(on_back=back_cb, generated_seed_text=encoded)
        view.on_show_view()
        view.on_mouse_press(view.back_rect.centerx, view.window.height - view.back_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        back_cb.assert_called_once_with(encoded)

    def test_generate_seed(self):
        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view.selected_preset = "hard"
        view.num_rounds = 2
        view.on_mouse_press(
            view.generate_rect.centerx,
            view.window.height - view.generate_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(len(view.generated_seed_text), 10)
        payload = __import__("pathwise.session_seed", fromlist=["decode_recruiter_seed"]).decode_recruiter_seed(
            view.generated_seed_text
        )
        self.assertEqual(payload.preset, "hard")
        self.assertEqual(payload.num_rounds, 2)

    def test_start_invokes_callback(self):
        start_cb = MagicMock()
        encoded = encode_recruiter_seed(50, "easy", 3)
        view = RecruiterConfigView(on_start=start_cb, generated_seed_text=encoded)
        view.on_show_view()
        view.on_mouse_press(view.start_rect.centerx, view.window.height - view.start_rect.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        start_cb.assert_called_once()
        cfg = start_cb.call_args.args[0]
        self.assertEqual(cfg.preset, "easy")
        self.assertEqual(cfg.num_rounds, 3)
        self.assertEqual(cfg.seed, 50)

    def test_copy_button_writes_clipboard(self):
        encoded = encode_recruiter_seed(12, "normal", 1)
        view = RecruiterConfigView(generated_seed_text=encoded)
        view.on_show_view()
        view.window.set_clipboard_text = MagicMock()
        view.on_mouse_press(
            view.copy_rect.centerx,
            view.window.height - view.copy_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        view.window.set_clipboard_text.assert_called_once_with(encoded)

    def test_copy_disabled_without_seed(self):
        view = RecruiterConfigView()
        view.on_show_view()
        view.window.set_clipboard_text = MagicMock()
        view.on_mouse_press(
            view.copy_rect.centerx,
            view.window.height - view.copy_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        view.window.set_clipboard_text.assert_not_called()

    def test_copy_shows_feedback(self):
        encoded = encode_recruiter_seed(12, "normal", 1)
        view = RecruiterConfigView(generated_seed_text=encoded)
        view.on_show_view()
        view.window.set_clipboard_text = MagicMock()
        with patch("pathwise.pre_game.time.monotonic", return_value=100.0):
            view.on_mouse_press(
                view.copy_rect.centerx,
                view.window.height - view.copy_rect.centery,
                arcade.MOUSE_BUTTON_LEFT,
                0,
            )
        self.assertEqual(view._copy_feedback_until, 100.0 + 1.5)

    def test_stale_hint_after_settings_change(self):
        encoded = encode_recruiter_seed(12, "normal", 1)
        view = RecruiterConfigView(generated_seed_text=encoded, rng=__import__("random").Random(0))
        view.on_show_view()
        self.assertFalse(view.seed_stale)
        view.selected_preset = "hard"
        view._layout()
        self.assertTrue(view.seed_stale)

    def test_keyboard_escape_back(self):
        view = RecruiterConfigView(on_back=MagicMock())
        view.on_show_view()
        view.on_key_press(arcade.key.ESCAPE, 0)
        view._on_back.assert_called_once()

    def test_non_left_mouse_ignored(self):
        view = RecruiterConfigView()
        view.on_show_view()
        view.on_mouse_press(0, 0, arcade.MOUSE_BUTTON_RIGHT, 0)
        self.assertFalse(view._done)

    def test_draw_button_variants(self):
        view = RecruiterConfigView()
        view.on_show_view()
        r = Rect(10, 10, 40, 20)
        view._draw_button(r, "x", 12, selected=True)
        view._draw_button(r, "x", 12, primary=True)
        view._draw_button(r, "", 12, border=(1, 2, 3))
        view._draw_button(r, "off", 12, disabled=True)


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
            captured["view"].finish(build_candidate_session_config("7"))

        pump.side_effect = finish_pump
        result = run_pre_game_menu(window)
        self.assertEqual(result.preset, "normal")
        self.assertEqual(result.num_rounds, 1)
        self.assertEqual(result.seed, 7)

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
