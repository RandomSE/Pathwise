"""Recruiter sidecar setup screen and candidate play without Turso."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import arcade

from pathwise.pre_game import (
    CANDIDATE_HOME_SUBTITLE,
    RECRUITER_DOOR_LABEL,
    RECRUITER_SEED_SHARE_HINT,
    CandidateHomeView,
    RecruiterConfigView,
)
from pathwise.recruiter_auth_views import (
    RecruiterEnvSetupView,
    user_safe_account_error,
)
from pathwise.runtime_paths import RECRUITER_ENV_FILENAME, recruiter_setup_message
from pathwise.turso_http import TursoConfigError, TursoHttpError
from tests.arcade_harness import fake_arcade_window
from tests.test_recruiter_auth_views import AuthArcadeTestCase, _entitled_record


class TestUserSafeTursoConfig(unittest.TestCase):
    def test_config_error_names_sidecar_not_token_value(self):
        message = user_safe_account_error(
            TursoConfigError("TURSO_AUTH_TOKEN is missing. secret-token")
        )
        self.assertIn("pathwise.env", message)
        self.assertIn("TURSO_DATABASE_URL", message)
        self.assertIn("TURSO_AUTH_TOKEN", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("account service", message.lower())

    def test_http_error_stays_offline_and_strips_token(self):
        message = user_safe_account_error(
            TursoHttpError("Turso HTTP 401: secret-token")
        )
        self.assertIn("account service", message.lower())
        self.assertNotIn("secret-token", message)


class TestRecruiterEnvSetupView(AuthArcadeTestCase):
    def test_copy_names_folder_filename_and_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("pathwise.recruiter_auth_views.env_setup_folder", return_value=folder):
                view = RecruiterEnvSetupView()
                view.on_show_view()
                view.on_draw()
                text = view.setup_copy()
        self.assertIn(str(folder), text)
        self.assertIn(RECRUITER_ENV_FILENAME, text)
        self.assertIn("TURSO_DATABASE_URL", text)
        self.assertIn("TURSO_AUTH_TOKEN", text)

    def test_save_writes_sidecar_and_does_not_echo_token(self):
        on_saved = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("pathwise.recruiter_auth_views.env_setup_folder", return_value=folder):
                with patch("pathwise.runtime_paths.env_setup_folder", return_value=folder):
                    view = RecruiterEnvSetupView(on_saved=on_saved)
                    view.on_show_view()
                    view.url_text = "libsql://example.turso.io"
                    view.token_text = "secret-token-value"
                    view._save()
                    path = folder / RECRUITER_ENV_FILENAME
                    self.assertTrue(path.is_file())
                    written = path.read_text(encoding="utf-8")
                    self.assertIn("libsql://example.turso.io", written)
                    self.assertIn("secret-token-value", written)
                    self.assertEqual(view.token_text, "")
                    self.assertNotIn("secret-token-value", view.status_text)
                    self.assertNotIn("secret-token-value", view.setup_copy())
                    on_saved.assert_called_once()

    def test_save_requires_both_turso_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("pathwise.recruiter_auth_views.env_setup_folder", return_value=folder):
                view = RecruiterEnvSetupView()
                view.on_show_view()
                view.url_text = "libsql://example.turso.io"
                view.token_text = ""
                view._save()
                self.assertFalse((folder / RECRUITER_ENV_FILENAME).is_file())
                self.assertTrue(view.status_text)

    def test_enter_submits_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("pathwise.recruiter_auth_views.env_setup_folder", return_value=folder):
                view = RecruiterEnvSetupView()
                view.on_show_view()
                view.url_text = "libsql://example.turso.io"
                view.token_text = "secret-token-value"
                view.on_key_press(arcade.key.ENTER, 0)
                self.assertTrue((folder / RECRUITER_ENV_FILENAME).is_file())
                self.assertEqual(view.token_text, "")

    def test_back_callback(self):
        on_back = MagicMock()
        view = RecruiterEnvSetupView(on_back=on_back)
        view.on_show_view()
        view.on_mouse_press(
            view.back_rect.centerx,
            view.window.height - view.back_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        on_back.assert_called_once()


class TestCandidatePlayWithoutTurso(AuthArcadeTestCase):
    def test_candidate_home_plays_with_empty_environ(self):
        with patch.dict(os.environ, {}, clear=True):
            view = CandidateHomeView()
            view.on_show_view()
            view.seed_text = ""
            view._try_play()
            self.assertTrue(view._done)
            self.assertIsNone(view._result.seed)
            self.assertEqual(view._result.audience, "candidate")

    def test_candidate_home_copy_separates_recruiter_door(self):
        self.assertIn("No setup", CANDIDATE_HOME_SUBTITLE)
        self.assertIn("Recruiter", RECRUITER_DOOR_LABEL)
        view = CandidateHomeView()
        view.on_show_view()
        view.on_draw()


class TestGenerateSeedShareCopy(AuthArcadeTestCase):
    def test_share_hint_mentions_paste_and_email(self):
        self.assertIn("paste", RECRUITER_SEED_SHARE_HINT.lower())
        self.assertIn("email", RECRUITER_SEED_SHARE_HINT.lower())
        view = RecruiterConfigView(rng=__import__("random").Random(0))
        view.on_show_view()
        view.window._recruiter_record = _entitled_record()
        with patch("pathwise.recruiter_seeds.register_recruiter_seed"):
            view._generate_seed()
        self.assertTrue(view.generated_seed_text)
        view.on_draw()


class TestSetupMessageHelper(unittest.TestCase):
    def test_helper_matches_view_contract(self):
        message = recruiter_setup_message(Path("C:/Pathwise"))
        self.assertIn("pathwise.env", message)
        self.assertIn("C:/Pathwise", message.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
