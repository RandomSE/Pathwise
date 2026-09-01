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
    ROUND_CONTROLS_HINT,
    ROUND_START_PROMPT,
    SessionConfig,
    _parse_seed_text,
    build_candidate_session_config,
    measure_modifier_popup_height,
    modifier_detail_lines,
    run_between_rounds,
    run_pre_game_menu,
    run_round_intro,
    run_session_complete,
    round_outcome_label,
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
        view._layout()
        view.on_draw()

    def test_name_field_hidden_on_empty_seed_shown_after_chars_or_paste(self):
        view = CandidateHomeView()
        view.on_show_view()
        self.assertEqual(view.name_field_rect.height, 0)
        view.seed_editing = True
        view.on_text("4")
        self.assertGreater(view.name_field_rect.height, 0)
        view.seed_text = ""
        view._layout()
        self.assertEqual(view.name_field_rect.height, 0)
        view.window.get_clipboard_text = MagicMock(return_value="42")
        view.on_mouse_press(
            view.paste_rect.centerx,
            view.window.height - view.paste_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(view.seed_text, "42")
        self.assertGreater(view.name_field_rect.height, 0)

    def test_play_with_valid_seed(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "42"
        view.name_text = "Ada Lovelace"
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertTrue(view._done)
        cfg = view._result
        self.assertEqual(cfg, build_candidate_session_config("42", candidate_label="Ada Lovelace"))
        self.assertEqual(cfg.candidate_label, "Ada Lovelace")
        self.assertIsNone(cfg.recruiter_seed_code)

    def test_play_blocked_without_name_on_valid_seed(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "42"
        view.name_text = ""
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertFalse(view._done)

    def test_play_random_empty_seed_needs_no_name(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = ""
        view.name_text = ""
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertTrue(view._done)
        self.assertIsNone(view._result.seed)
        self.assertIsNone(view._result.recruiter_seed_code)
        self.assertIsNone(view._result.candidate_label)

    def test_logged_in_recruiter_play_uses_email_as_label(self):
        from pathwise.recruiter_accounts import RecruiterRecord

        view = CandidateHomeView()
        view.on_show_view()
        view.window.recruiter_session_active = lambda: True
        view.window._recruiter_record = RecruiterRecord(
            id="c" * 32,
            email="player@example.com",
            billing_date=None,
            active=1,
            trial_active=0,
            billing_exempt=1,
            tier="basic",
            company=None,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        view.window._recruiter_session_token = "token"
        encoded = encode_recruiter_seed(8, "normal", 1)
        view.seed_text = encoded
        view.name_text = ""
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertTrue(view._done)
        self.assertEqual(view._result.candidate_label, "player@example.com")
        self.assertEqual(view._result.recruiter_seed_code, encoded)

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
        view.name_text = "Ada"
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertEqual(view._result.preset, "normal")
        self.assertEqual(view._result.num_rounds, 1)

    def test_paste_rejects_invalid_recruiter_length(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "42"
        view.window.get_clipboard_text = MagicMock(return_value="1234567890")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.seed_text, "1234567890")
        self.assertEqual(view.seed_state, "invalid")
        self.assertFalse(view.seed_editing)

    def test_paste_from_clipboard(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.window.get_clipboard_text = MagicMock(return_value="  8123456 \n")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.seed_text, "8123456")
        self.assertTrue(view.seed_editing)

    def test_play_with_modifiers_starts_session(self):
        rainy_seed = encode_recruiter_seed(
            834941, "normal", 1, modifiers=frozenset({"rainy_roads"})
        )
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = rainy_seed
        view.name_text = "Ada"
        view._layout()
        view.on_mouse_press(
            view.play_rect.centerx,
            view.window.height - view.play_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertTrue(view._done)
        self.assertIn("rainy_roads", view._result.modifiers)

    def test_paste_button(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.window.get_clipboard_text = MagicMock(return_value="42")
        view.on_mouse_press(
            view.paste_rect.centerx,
            view.window.height - view.paste_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(view.seed_text, "42")
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
        from pathwise.recruiter_accounts import RecruiterRecord

        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view.window._recruiter_record = RecruiterRecord(
            id="c" * 32,
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
        view.selected_preset = "hard"
        view.num_rounds = 2
        with patch("pathwise.recruiter_seeds.register_recruiter_seed") as register:
            view.on_mouse_press(
                view.generate_rect.centerx,
                view.window.height - view.generate_rect.centery,
                arcade.MOUSE_BUTTON_LEFT,
                0,
            )
        register.assert_called_once()
        self.assertEqual(len(view.generated_seed_text), 13)
        payload = __import__("pathwise.session_seed", fromlist=["decode_recruiter_seed"]).decode_recruiter_seed(
            view.generated_seed_text
        )
        self.assertEqual(payload.preset, "hard")
        self.assertEqual(payload.num_rounds, 2)
        self.assertEqual(register.call_args.args[0], view.generated_seed_text)

    def test_generate_does_not_keep_new_code_if_register_fails(self):
        from pathwise.recruiter_accounts import RecruiterRecord
        from pathwise.recruiter_auth_views import OFFLINE_MESSAGE
        from pathwise.turso_http import TursoHttpError

        view = RecruiterConfigView(rng=__import__("random").Random(1))
        view.on_show_view()
        view.window._recruiter_record = RecruiterRecord(
            id="c" * 32,
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
        prior = encode_recruiter_seed(12, "normal", 1)
        view.generated_seed_text = prior
        with patch(
            "pathwise.recruiter_seeds.register_recruiter_seed",
            side_effect=TursoHttpError("offline"),
        ):
            view._generate_seed()
        self.assertEqual(view.generated_seed_text, prior)
        self.assertEqual(view._generate_error, OFFLINE_MESSAGE)

    def test_generate_retries_on_unique_conflict(self):
        from pathwise.recruiter_accounts import RecruiterRecord
        from pathwise.recruiter_seeds import RecruiterSeedConflictError

        view = RecruiterConfigView(rng=__import__("random").Random(2))
        view.on_show_view()
        view.window._recruiter_record = RecruiterRecord(
            id="c" * 32,
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
        attempts = {"n": 0}

        def register(_code, _recruiter_id, *, execute=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RecruiterSeedConflictError("seed already registered")

        with patch("pathwise.recruiter_seeds.register_recruiter_seed", side_effect=register):
            view._generate_seed()
        self.assertEqual(attempts["n"], 2)
        self.assertEqual(len(view.generated_seed_text), 13)
        self.assertEqual(view._generate_error, "")

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

    def test_start_without_generated_seed_does_not_raise(self):
        start_cb = MagicMock()
        view = RecruiterConfigView(on_start=start_cb)
        view.on_show_view()
        view.on_mouse_press(
            view.start_rect.centerx,
            view.window.height - view.start_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        start_cb.assert_not_called()

    def test_start_with_modifiers_goes_directly_to_session(self):
        start_cb = MagicMock()
        encoded = encode_recruiter_seed(
            50, "easy", 1, modifiers=frozenset({"rainy_roads"})
        )
        view = RecruiterConfigView(
            on_start=start_cb,
            generated_seed_text=encoded,
        )
        view.on_show_view()
        view.on_mouse_press(
            view.start_rect.centerx,
            view.window.height - view.start_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        start_cb.assert_called_once()
        self.assertIn("rainy_roads", start_cb.call_args.args[0].modifiers)

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

    def test_open_dashboard_action_does_not_finish(self):
        opened = []
        view = MessageView(
            title="Done",
            accent="Dashboard: /tmp/logs_dashboard.html",
            action_label="Open dashboard",
            on_action=lambda: opened.append("open"),
            dashboard_path="/tmp/logs_dashboard.html",
        )
        view.on_show_view()
        self.assertIsNotNone(view.action_rect)
        view.on_mouse_press(
            view.action_rect.centerx,
            view.window.height - view.action_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(opened, ["open"])
        self.assertFalse(view._done)
        view.on_draw()

    def test_draw_minimal(self):
        view = MessageView(title="Only")
        view.on_draw()

    def test_round_controls_details(self):
        view = MessageView(
            title="Round 1",
            accent=ROUND_START_PROMPT,
            details=ROUND_CONTROLS_HINT,
        )
        self.assertIn("WASD", view.details)
        self.assertIn("Shift", view.details)

    def test_round_intro_waits_for_input(self):
        view = MessageView(
            title="Round 1 of 1",
            accent=ROUND_START_PROMPT,
            details=ROUND_CONTROLS_HINT,
        )
        view.on_update(10.0)
        self.assertFalse(view._done)
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertTrue(view._done)

    def test_see_modifiers_button_when_session_has_modifiers(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        self.assertIsNotNone(view.modifiers_btn_rect)

    def test_see_modifiers_opens_popup_without_starting(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        btn = view.modifiers_btn_rect
        view.on_mouse_press(btn.centerx, view.window.height - btn.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertTrue(view._modifiers_popup_open)
        self.assertFalse(view._done)

    def test_outside_popup_click_closes_without_starting(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        btn = view.modifiers_btn_rect
        view.on_mouse_press(btn.centerx, view.window.height - btn.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        view.on_mouse_press(5, view.window.height - 5, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertFalse(view._modifiers_popup_open)
        self.assertFalse(view._done)

    def test_escape_closes_popup_without_starting(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        btn = view.modifiers_btn_rect
        view.on_mouse_press(btn.centerx, view.window.height - btn.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertFalse(view._modifiers_popup_open)
        self.assertFalse(view._done)

    def test_popup_draw(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        view._modifiers_popup_open = True
        view.on_draw()

    def test_start_after_popup_closed(self):
        view = MessageView(title="Round 1", modifiers=frozenset({"rainy_roads"}))
        view.on_show_view()
        btn = view.modifiers_btn_rect
        view.on_mouse_press(btn.centerx, view.window.height - btn.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        view.on_mouse_press(5, view.window.height - 5, arcade.MOUSE_BUTTON_LEFT, 0)
        view.on_key_press(arcade.key.SPACE, 0)
        self.assertTrue(view._done)

    def test_modifier_popup_height_fits_title_and_description(self):
        height = measure_modifier_popup_height(472, frozenset({"rainy_roads"}))
        self.assertGreaterEqual(height, 160)

    def test_three_modifiers_popup_can_scroll(self):
        mods = frozenset({"rainy_roads", "ignored", "untrustworthy"})
        view = MessageView(title="Round 1", modifiers=mods)
        view.on_show_view()
        # Tall desktop window previously reported max_scroll == 0 (unreachable text).
        view.window.height = 900
        view.window.width = 800
        view._layout_message()
        btn = view.modifiers_btn_rect
        view.on_mouse_press(btn.centerx, view.window.height - btn.centery, arcade.MOUSE_BUTTON_LEFT, 0)
        self.assertTrue(view._modifiers_popup_open)
        self.assertGreater(view._popup_max_scroll, 0)
        before = view._popup_scroll
        view.on_mouse_scroll(0, 0, 0, -1)
        self.assertGreater(view._popup_scroll, before)
        view.on_key_press(arcade.key.DOWN, 0)
        self.assertGreaterEqual(view._popup_scroll, before)
        view._popup_scroll = view._popup_max_scroll + 50
        view._clamp_popup_scroll()
        self.assertEqual(view._popup_scroll, view._popup_max_scroll)
        view.on_draw()

    def test_fractional_scroll_still_moves(self):
        mods = frozenset({"rainy_roads", "ignored", "untrustworthy"})
        view = MessageView(title="Round 1", modifiers=mods, audience="recruiter")
        view.on_show_view()
        view.window.height = 900
        view.window.width = 800
        view._layout_message()
        view._open_modifiers_popup()
        self.assertGreater(view._popup_max_scroll, 0)
        view._scroll_modifiers_popup(-0.05)
        self.assertGreater(view._popup_scroll, 0)

    def test_large_seed_catalog_scroll_covers_all_after_draw(self):
        from pathwise.session_seed import decode_recruiter_seed

        payload = decode_recruiter_seed("9112015292841")
        assert payload is not None
        view = MessageView(
            title="Round 1",
            modifiers=payload.modifiers,
            audience="recruiter",
        )
        view.on_show_view()
        view.window.height = 900
        view.window.width = 800
        view._layout_message()
        view._open_modifiers_popup()
        estimated = view._popup_max_scroll
        self.assertGreater(estimated, 0)
        view.on_draw()
        # Live Text metrics must never shrink reachable scroll below estimate.
        self.assertGreaterEqual(view._popup_max_scroll, estimated)
        lines = modifier_detail_lines(payload.modifiers, audience="recruiter")
        self.assertGreaterEqual(len(lines), 10)
        titles = [title for title, _ in lines]
        self.assertIn("Old", titles)
        self.assertIn("Lag", titles)

    def test_recruiter_hidden_still_lists_all_modifiers(self):
        mods = frozenset({"hidden", "rainy_roads", "old", "exposure"})
        view = MessageView(
            title="Round 1",
            modifiers=mods,
            audience="recruiter",
        )
        view.on_show_view()
        self.assertEqual(view.modifiers, mods)
        titles = {title for title, _ in modifier_detail_lines(mods, audience="recruiter")}
        self.assertIn("Hidden", titles)
        self.assertIn("Rainy roads", titles)
        self.assertIn("Old", titles)

    def test_recruiter_click_explains_modifier(self):
        view = RecruiterConfigView()
        view.on_show_view()
        rainy = view.modifier_toggle_rects["rainy_roads"]
        action = view.modifier_action_rects["rainy_roads"]
        self.assertLess(rainy.width, 400)
        self.assertEqual(action.width, 44)
        self.assertEqual(rainy.left, view.window.width // 2 - 200)
        explain = view._layout_state.modifier_explain_rect
        self.assertGreaterEqual(explain.width, 280)
        self.assertGreaterEqual(explain.height, 150)
        self.assertGreater(explain.left, rainy.right)
        # Title row toggles selection (not explain-only).
        view.on_mouse_press(
            rainy.centerx,
            view.window.height - rainy.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertIn("rainy_roads", view.selected_modifiers)
        self.assertEqual(view._explained_modifier_id, "rainy_roads")
        view.on_draw()
        view.on_mouse_press(
            action.centerx,
            view.window.height - action.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(view._explained_modifier_id, "rainy_roads")

    def test_wrap_text_words_avoids_mid_word_splits(self):
        from pathwise.pre_game import multiline_text_width, wrap_text_words
        from pathwise.modifiers.registry import MODIFIER_CATALOG

        text = "Wet pavement: cars brake more slowly, some stop past crosswalk lines."
        wrapped = wrap_text_words(text, width_px=180, font_size=14)
        for line in wrapped.split("\n"):
            if not line:
                continue
            for token in line.split():
                self.assertTrue(token.isascii())
        self.assertIn("\n", wrapped)
        highway = next(e for e in MODIFIER_CATALOG if e["id"] == "highway")
        hw = wrap_text_words(highway["description"], width_px=260, font_size=14)
        for line in hw.split("\n"):
            self.assertNotIn("  ", line)
        joined = " ".join(hw.split())
        for word in highway["description"].replace("\n", " ").split():
            self.assertIn(word, joined)
        # Arcade requires non-zero width for multiline; our helper must allow draw.
        width = multiline_text_width(260)
        self.assertGreater(width, 0)
        text_obj = arcade.Text(
            hw,
            0,
            0,
            (255, 255, 255),
            14,
            multiline=True,
            width=width,
        )
        self.assertIsNotNone(text_obj)

    def test_modifier_desc_draw_x_keeps_block_inside_card(self):
        from pathwise.pre_game import (
            _modifier_popup_text_width,
            modifier_desc_draw_x,
            multiline_text_width,
        )

        card_left = 100
        card_width = 472
        text_width = _modifier_popup_text_width(card_width)
        draw_x = modifier_desc_draw_x(card_left, card_width, text_width=text_width)
        # Left-aligned content block stays inside the card (titles did; old center+
        # huge-width layout put glyphs near center - multiline_text_width/2).
        self.assertGreaterEqual(draw_x, card_left)
        self.assertLessEqual(draw_x + text_width, card_left + card_width)
        broken_left = (card_left + card_width // 2) - multiline_text_width(text_width) // 2
        self.assertLess(broken_left, card_left)
        self.assertGreater(draw_x, broken_left)

    def test_recruiter_highway_explain_draw(self):
        view = RecruiterConfigView()
        view.on_show_view()
        view.selected_modifiers.add("highway")
        view._explained_modifier_id = "highway"
        view.on_draw()


class TestMultilineTextRuntime(unittest.TestCase):
    """Uses real arcade.Text (no menu harness mock) to catch width=None crashes."""

    def test_prewrapped_highway_text_constructs(self):
        from pathwise.pre_game import multiline_text_width, wrap_text_words
        from pathwise.modifiers.registry import MODIFIER_CATALOG

        highway = next(e for e in MODIFIER_CATALOG if e["id"] == "highway")
        body = wrap_text_words(highway["description"], width_px=280, font_size=14)
        # Must not raise ValueError about width=None when multiline=True.
        arcade.Text(
            body,
            0,
            0,
            (255, 255, 255),
            14,
            multiline=True,
            width=multiline_text_width(280),
        )
        with self.assertRaises(ValueError):
            arcade.Text(
                body,
                0,
                0,
                (255, 255, 255),
                14,
                multiline=True,
                width=None,
            )

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
        captured = {}

        def show_view(view):
            captured["view"] = view
            view.finish(True)

        window.show_view = show_view
        self.assertTrue(run_round_intro(window, 2, 3, profile, time_limit_s=52))
        self.assertIn("Shift", captured["view"].details)
        self.assertIsNone(captured["view"].auto_advance_s)

    @patch("pathwise.pre_game.pump_frame")
    def test_run_round_intro_passes_modifiers(self, pump):
        from map_generation.difficulty import DifficultyProfile

        window = MagicMock()
        window.closed = False
        profile = DifficultyProfile.for_menu_preset("normal")
        captured = {}

        def show_view(view):
            captured["view"] = view
            view.finish(True)

        window.show_view = show_view
        mods = frozenset({"rainy_roads"})
        self.assertTrue(
            run_round_intro(window, 1, 1, profile, time_limit_s=60, modifiers=mods)
        )
        self.assertEqual(captured["view"].modifiers, mods)

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

    def test_round_outcome_labels(self):
        self.assertEqual(round_outcome_label("success"), "Goal reached")
        self.assertEqual(round_outcome_label("collision"), "Collision")
        self.assertEqual(round_outcome_label("timeout"), "Time expired")


if __name__ == "__main__":
    unittest.main()
