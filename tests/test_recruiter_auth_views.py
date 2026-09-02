"""Login/register recruiter gating: views, window routing, generate entitlement."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import arcade

from pathwise.pre_game import CandidateHomeView, RecruiterConfigView
from pathwise.recruiter_accounts import (
    RecruiterAuthError,
    RecruiterDuplicateEmailError,
    RecruiterRecord,
    RecruiterValidationError,
)
from pathwise.recruiter_auth_views import (
    SIGNING_IN_MESSAGE,
    RecruiterLoginView,
    RecruiterRegisterView,
)
from pathwise.turso_http import TursoConfigError, TursoHttpError
from tests.arcade_harness import fake_arcade_window


def _entitled_record() -> RecruiterRecord:
    return RecruiterRecord(
        id="a" * 32,
        email="launch@example.com",
        billing_date=None,
        active=1,
        trial_active=0,
        billing_exempt=1,
        tier="basic",
        company=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _blocked_record() -> RecruiterRecord:
    return RecruiterRecord(
        id="b" * 32,
        email="blocked@example.com",
        billing_date=None,
        active=0,
        trial_active=0,
        billing_exempt=0,
        tier="basic",
        company=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


class AuthArcadeTestCase(unittest.TestCase):
    def setUp(self):
        self._get_window = patch("arcade.get_window", return_value=fake_arcade_window())
        self._set_bg = patch("pathwise.recruiter_auth_views.arcade.set_background_color")
        self._pre_bg = patch("pathwise.pre_game.arcade.set_background_color")
        self._text = patch(
            "pathwise.recruiter_auth_views.arcade.Text",
            return_value=MagicMock(draw=MagicMock()),
        )
        self._pre_text = patch(
            "pathwise.pre_game.arcade.Text",
            return_value=MagicMock(draw=MagicMock()),
        )
        self._fill = patch("pathwise.recruiter_auth_views.arcade.draw_lbwh_rectangle_filled")
        self._outline = patch("pathwise.recruiter_auth_views.arcade.draw_lbwh_rectangle_outline")
        self._pre_fill = patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled")
        self._pre_outline = patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline")
        self._get_window.start()
        self._set_bg.start()
        self._pre_bg.start()
        self._text.start()
        self._pre_text.start()
        self._fill.start()
        self._outline.start()
        self._pre_fill.start()
        self._pre_outline.start()

    def tearDown(self):
        patch.stopall()


class TestRecruiterLoginView(AuthArcadeTestCase):
    def test_login_success_calls_on_success_with_record_and_token(self):
        rec = _entitled_record()
        on_success = MagicMock()
        view = RecruiterLoginView(on_success=on_success, execute=MagicMock())
        view.on_show_view()
        view.email_text = "launch@example.com"
        view.password_text = "password1"
        with patch(
            "pathwise.recruiter_auth_views.authenticate_recruiter",
            return_value=(rec, "raw-token"),
        ) as auth:
            view._submit()
            auth.assert_called_once()
            kwargs = auth.call_args.kwargs
            self.assertEqual(auth.call_args.args[0], "launch@example.com")
            self.assertEqual(auth.call_args.args[1], "password1")
            self.assertIn("execute", kwargs)
        on_success.assert_called_once_with(rec, "raw-token")

    def test_login_paints_signing_in_before_authenticate(self):
        rec = _entitled_record()
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.email_text = "launch@example.com"
        view.password_text = "password1"
        seen = {}

        def auth(*_args, **_kwargs):
            seen["status"] = view.error_text
            return rec, "raw-token"

        with patch("pathwise.recruiter_auth_views.authenticate_recruiter", side_effect=auth):
            view._submit()
        self.assertEqual(seen["status"], SIGNING_IN_MESSAGE)
        self.assertEqual(view.error_text, "")

    def test_failed_login_stays_with_generic_auth_error(self):
        on_success = MagicMock()
        view = RecruiterLoginView(on_success=on_success, execute=MagicMock())
        view.on_show_view()
        view.email_text = "a@b.co"
        view.password_text = "wrongpass"
        with patch(
            "pathwise.recruiter_auth_views.authenticate_recruiter",
            side_effect=RecruiterAuthError("Invalid credentials"),
        ):
            view._submit()
        on_success.assert_not_called()
        self.assertEqual(view.error_text, "Invalid credentials")
        self.assertNotIn("password_hash", view.error_text.lower())
        self.assertNotIn("turso", view.error_text.lower())

    def test_turso_errors_map_to_safe_offline_copy(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.email_text = "a@b.co"
        view.password_text = "password1"
        with patch(
            "pathwise.recruiter_auth_views.authenticate_recruiter",
            side_effect=TursoHttpError("Turso HTTP 401: secret-token"),
        ):
            view._submit()
        self.assertIn("account service", view.error_text.lower())
        self.assertNotIn("secret-token", view.error_text)
        self.assertNotIn("TURSO_AUTH_TOKEN", view.error_text)
        view.error_text = ""
        with patch(
            "pathwise.recruiter_auth_views.authenticate_recruiter",
            side_effect=TursoConfigError("TURSO_AUTH_TOKEN is missing"),
        ):
            view._submit()
        self.assertIn("pathwise.env", view.error_text)
        self.assertIn("TURSO_DATABASE_URL", view.error_text)
        self.assertIn("TURSO_AUTH_TOKEN", view.error_text)
        self.assertNotIn("account service", view.error_text.lower())

    def test_enter_submits_login_and_tab_moves_focus(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view._focus = "email"
        view.on_key_press(arcade.key.TAB, 0)
        self.assertEqual(view._focus, "password")
        view.on_text("p")
        self.assertEqual(view.password_text, "p")
        with patch.object(view, "_submit") as submit:
            view.on_key_press(arcade.key.ENTER, 0)
            submit.assert_called_once()

    def test_password_field_is_masked_and_not_copied(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.password_text = "password1"
        view.window.set_clipboard_text = MagicMock()
        drawn = view._masked_password()
        self.assertNotIn("password1", drawn)
        self.assertEqual(len(drawn), len("password1"))
        view.on_key_press(arcade.key.C, arcade.key.MOD_CTRL)
        view.window.set_clipboard_text.assert_not_called()

    def test_create_account_and_back_callbacks(self):
        on_register = MagicMock()
        on_back = MagicMock()
        view = RecruiterLoginView(
            on_success=MagicMock(),
            on_register=on_register,
            on_back=on_back,
            execute=MagicMock(),
        )
        view.on_show_view()
        view.on_mouse_press(
            view.register_rect.centerx,
            view.window.height - view.register_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        on_register.assert_called_once()
        view.on_mouse_press(
            view.back_rect.centerx,
            view.window.height - view.back_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        on_back.assert_called_once()

    def test_draw_and_email_edit_smoke(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.on_text("a")
        self.assertEqual(view.email_text, "a")
        view.error_text = "Invalid credentials"
        view.on_draw()
        view.on_resize(800, 600)

    def test_ctrl_v_pastes_into_email_and_password(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view._focus = "email"
        view.window.get_clipboard_text = MagicMock(return_value="  user@example.com \n")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.email_text, "user@example.com")
        view._focus = "password"
        view.window.get_clipboard_text = MagicMock(return_value="hunter2pass\r\n")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.password_text, "hunter2pass")
        view.window.set_clipboard_text = MagicMock()
        view.on_key_press(arcade.key.C, arcade.key.MOD_CTRL)
        view.window.set_clipboard_text.assert_not_called()

    def test_on_text_multichar_pastes_into_focused_field(self):
        view = RecruiterLoginView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view._focus = "email"
        view.on_text("paste@example.com")
        self.assertEqual(view.email_text, "paste@example.com")
        view._focus = "password"
        view.on_text("longpassword")
        self.assertEqual(view.password_text, "longpassword")
        drawn = view._masked_password()
        self.assertNotIn("longpassword", drawn)


class TestRecruiterRegisterView(AuthArcadeTestCase):
    def test_register_success_creates_then_authenticates(self):
        rec = _entitled_record()
        on_success = MagicMock()
        execute = MagicMock()
        view = RecruiterRegisterView(on_success=on_success, execute=execute)
        view.on_show_view()
        view.email_text = "launch@example.com"
        view.password_text = "password1"
        view.confirm_text = "password1"
        with patch(
            "pathwise.recruiter_auth_views.create_recruiter",
            return_value=rec,
        ) as create, patch(
            "pathwise.recruiter_auth_views.authenticate_recruiter",
            return_value=(rec, "sess-token"),
        ) as auth:
            view._submit()
            create.assert_called_once()
            auth.assert_called_once()
            self.assertEqual(create.call_args.args[0], "launch@example.com")
            self.assertEqual(auth.call_args.args[1], "password1")
        on_success.assert_called_once_with(rec, "sess-token")
        self.assertEqual(rec.billing_exempt, 1)
        self.assertEqual(rec.active, 1)

    def test_confirm_mismatch_does_not_hit_create(self):
        view = RecruiterRegisterView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.email_text = "ok@example.com"
        view.password_text = "password1"
        view.confirm_text = "password2"
        with patch("pathwise.recruiter_auth_views.create_recruiter") as create:
            view._submit()
            create.assert_not_called()
        self.assertIn("match", view.error_text.lower())

    def test_duplicate_email_and_validation_are_user_safe(self):
        view = RecruiterRegisterView(on_success=MagicMock(), execute=MagicMock())
        view.on_show_view()
        view.email_text = "ok@example.com"
        view.password_text = "password1"
        view.confirm_text = "password1"
        with patch(
            "pathwise.recruiter_auth_views.create_recruiter",
            side_effect=RecruiterDuplicateEmailError("Email already registered"),
        ):
            view._submit()
        self.assertIn("already", view.error_text.lower())
        self.assertNotIn("UNIQUE", view.error_text)
        with patch(
            "pathwise.recruiter_auth_views.create_recruiter",
            side_effect=RecruiterValidationError("Password must be at least 8 characters"),
        ):
            view._submit()
        self.assertIn("8", view.error_text)

    def test_back_to_login_callback(self):
        on_back = MagicMock()
        view = RecruiterRegisterView(on_success=MagicMock(), on_back=on_back)
        view.on_show_view()
        view.on_mouse_press(
            view.back_rect.centerx,
            view.window.height - view.back_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        on_back.assert_called_once()

    def test_draw_smoke(self):
        view = RecruiterRegisterView(on_success=MagicMock())
        view.on_show_view()
        view.password_text = "secret999"
        view.confirm_text = "secret999"
        view.on_draw()

    def test_ctrl_v_pastes_into_confirm_password(self):
        view = RecruiterRegisterView(on_success=MagicMock())
        view.on_show_view()
        view._focus = "confirm"
        view.window.get_clipboard_text = MagicMock(return_value="password1\n")
        view.on_key_press(arcade.key.V, arcade.key.MOD_CTRL)
        self.assertEqual(view.confirm_text, "password1")


class TestGenerateSeedGate(AuthArcadeTestCase):
    def test_generate_blocked_when_not_entitled(self):
        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view.window._recruiter_record = _blocked_record()
        view._generate_seed()
        self.assertEqual(view.generated_seed_text, "")
        self.assertTrue(view._generate_error)

    def test_generate_fail_closed_without_record(self):
        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view._generate_seed()
        self.assertEqual(view.generated_seed_text, "")

    def test_generate_encodes_when_entitled(self):
        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view.window._recruiter_record = _entitled_record()
        view.selected_preset = "hard"
        view.num_rounds = 2
        with patch("pathwise.recruiter_seeds.register_recruiter_seed"):
            view._generate_seed()
        self.assertEqual(len(view.generated_seed_text), 13)
        payload = __import__(
            "pathwise.session_seed", fromlist=["decode_recruiter_seed"]
        ).decode_recruiter_seed(view.generated_seed_text)
        self.assertEqual(payload.preset, "hard")
        self.assertEqual(payload.num_rounds, 2)

    def test_generate_turso_config_calls_needs_setup(self):
        on_setup = MagicMock()
        view = RecruiterConfigView(
            rng=__import__("random").Random(0),
            on_needs_setup=on_setup,
        )
        view.on_show_view()
        view.window._recruiter_record = _entitled_record()
        with patch(
            "pathwise.recruiter_seeds.register_recruiter_seed",
            side_effect=TursoConfigError("TURSO_AUTH_TOKEN is missing"),
        ):
            view._generate_seed()
        on_setup.assert_called_once()
        self.assertEqual(view.generated_seed_text, "")


class TestCandidatePlayUngated(AuthArcadeTestCase):
    def test_candidate_play_does_not_require_session(self):
        view = CandidateHomeView()
        view.on_show_view()
        view.seed_text = "42"
        view.name_text = "Ada"
        view._try_play()
        self.assertTrue(view._done)
        self.assertEqual(view._result.seed, 42)


if __name__ == "__main__":
    unittest.main()
