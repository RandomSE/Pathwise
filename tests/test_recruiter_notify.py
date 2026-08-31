"""Recruiter seed-use email: payload, skip rules, failure isolation, no dedup."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.recruiter_accounts import apply_recruiter_schema, create_recruiter
from pathwise.recruiter_notify import notify_recruiter_of_seed_use
from pathwise.recruiter_seeds import register_recruiter_seed
from pathwise.session_seed import encode_recruiter_seed
from tests.test_recruiter_accounts import FakePipeline


class TestRecruiterNotify(unittest.TestCase):
    def setUp(self):
        self.db = FakePipeline()
        self.addCleanup(self.db.conn.close)
        apply_recruiter_schema(execute=self.db.execute)
        self.owner = create_recruiter(
            "owner@example.com",
            "password1",
            execute=self.db.execute,
        )
        self.seed_code = encode_recruiter_seed(99, "hard", 2)
        register_recruiter_seed(
            self.seed_code,
            self.owner.id,
            execute=self.db.execute,
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dashboard = Path(self.tmp.name) / "logs_dashboard.html"
        self.dashboard.write_text("<html>run-one</html>", encoding="utf-8")
        self.sent: list[dict] = []

    def _send(self, **payload):
        self.sent.append(payload)

    def _notify(self, **overrides):
        kwargs = dict(
            recruiter_seed_code=self.seed_code,
            candidate_label="Ada Lovelace",
            used_at_utc="2026-08-30T10:00:00Z",
            completed_at_utc="2026-08-30T10:12:00Z",
            dashboard_path=self.dashboard,
            player_recruiter_id=None,
            execute=self.db.execute,
            send=self._send,
        )
        kwargs.update(overrides)
        return notify_recruiter_of_seed_use(**kwargs)

    def test_send_payload_includes_body_fields_and_attachment(self):
        sent = self._notify()
        self.assertTrue(sent)
        self.assertEqual(len(self.sent), 1)
        payload = self.sent[0]
        self.assertEqual(payload["to"], "owner@example.com")
        self.assertIn("Pathwise", payload["subject"])
        self.assertIn("Ada Lovelace", payload["subject"])
        body = payload["body"]
        self.assertIn("Ada Lovelace", body)
        self.assertIn(self.seed_code, body)
        self.assertIn("2026-08-30T10:00:00Z", body)
        self.assertIn("2026-08-30T10:12:00Z", body)
        self.assertIn("desktop browser", body.lower())
        self.assertIn("replay", body.lower())
        self.assertNotIn("employment", body.lower())
        self.assertNotIn("construct validity", body.lower())
        self.assertNotIn("criterion validity", body.lower())
        self.assertEqual(payload["attachment_filename"], "logs_dashboard.html")
        self.assertEqual(payload["attachment_bytes"], b"<html>run-one</html>")

    def test_skip_when_no_owner(self):
        unknown = encode_recruiter_seed(1, "easy", 1)
        self.assertFalse(
            self._notify(recruiter_seed_code=unknown, candidate_label="Pat")
        )
        self.assertEqual(self.sent, [])

    def test_skip_when_seed_code_missing(self):
        self.assertFalse(self._notify(recruiter_seed_code=None))
        self.assertFalse(self._notify(recruiter_seed_code=""))
        self.assertEqual(self.sent, [])

    def test_skip_self_play(self):
        self.assertFalse(self._notify(player_recruiter_id=self.owner.id))
        self.assertEqual(self.sent, [])

    def test_other_recruiter_play_emails_owner(self):
        other = create_recruiter(
            "player@example.com",
            "password1",
            execute=self.db.execute,
        )
        self.assertTrue(
            self._notify(
                player_recruiter_id=other.id,
                candidate_label=other.email,
            )
        )
        self.assertEqual(self.sent[0]["to"], "owner@example.com")
        self.assertIn("player@example.com", self.sent[0]["subject"])

    def test_skip_missing_smtp_does_not_raise(self):
        with patch("pathwise.recruiter_notify.load_dotenv", return_value=None), patch.dict(
            os.environ,
            {
                "PATHWISE_SMTP_HOST": "",
                "PATHWISE_SMTP_PASSWORD": "",
                "PATHWISE_SMTP_FROM": "",
            },
            clear=False,
        ):
            result = notify_recruiter_of_seed_use(
                recruiter_seed_code=self.seed_code,
                candidate_label="Ada Lovelace",
                used_at_utc="2026-08-30T10:00:00Z",
                completed_at_utc="2026-08-30T10:12:00Z",
                dashboard_path=self.dashboard,
                player_recruiter_id=None,
                execute=self.db.execute,
            )
        self.assertFalse(result)

    def test_send_exception_does_not_raise_to_caller(self):
        def boom(**_payload):
            raise RuntimeError("smtp down")

        result = self._notify(send=boom)
        self.assertFalse(result)

    def test_every_finish_sends_again_no_dedup(self):
        self.assertTrue(self._notify())
        self.assertTrue(self._notify())
        self.assertEqual(len(self.sent), 2)

    def test_lookup_exception_skips_without_raising(self):
        def boom(*_args, **_kwargs):
            raise RuntimeError("turso down")

        with self.assertLogs("pathwise.recruiter_notify", level=logging.WARNING) as captured:
            result = self._notify(execute=boom)
        self.assertFalse(result)
        self.assertEqual(self.sent, [])
        self.assertIn("lookup failed", "\n".join(captured.output).lower())

    def test_missing_dashboard_file_skips(self):
        missing = Path(self.tmp.name) / "no-such-dashboard.html"
        with self.assertLogs("pathwise.recruiter_notify", level=logging.WARNING) as captured:
            result = self._notify(dashboard_path=missing)
        self.assertFalse(result)
        self.assertEqual(self.sent, [])
        self.assertIn("attachment missing", "\n".join(captured.output).lower())

    def test_empty_dashboard_skips(self):
        empty = Path(self.tmp.name) / "empty.html"
        empty.write_bytes(b"")
        with self.assertLogs("pathwise.recruiter_notify", level=logging.WARNING) as captured:
            result = self._notify(dashboard_path=empty)
        self.assertFalse(result)
        self.assertIn("attachment empty", "\n".join(captured.output).lower())

    def test_none_dashboard_path_is_empty_attachment(self):
        with self.assertLogs("pathwise.recruiter_notify", level=logging.WARNING) as captured:
            result = self._notify(dashboard_path=None)
        self.assertFalse(result)
        self.assertIn("attachment empty", "\n".join(captured.output).lower())

    def test_smtp_send_starttls_login_and_invalid_port(self):
        calls: list[str] = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=20):
                self.host = host
                self.port = port
                self.timeout = timeout
                calls.append(f"connect:{host}:{port}")

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                calls.append("close")
                return False

            def starttls(self):
                calls.append("starttls")

            def login(self, user, password):
                calls.append(f"login:{user}:{password}")

            def send_message(self, message):
                calls.append(f"send:{message['To']}:{message['Subject']}")

        env = {
            "PATHWISE_SMTP_HOST": "smtp.example.test",
            "PATHWISE_SMTP_PORT": "587",
            "PATHWISE_SMTP_USER": "smtp-user",
            "PATHWISE_SMTP_PASSWORD": "smtp-secret",
            "PATHWISE_SMTP_FROM": "from@example.test",
        }
        with patch("pathwise.recruiter_notify.load_dotenv", return_value=None), patch.dict(
            os.environ, env, clear=False
        ), patch("pathwise.recruiter_notify.smtplib.SMTP", FakeSMTP):
            result = notify_recruiter_of_seed_use(
                recruiter_seed_code=self.seed_code,
                candidate_label="Ada Lovelace",
                used_at_utc="2026-08-30T10:00:00Z",
                completed_at_utc="2026-08-30T10:12:00Z",
                dashboard_path=self.dashboard,
                player_recruiter_id=None,
                execute=self.db.execute,
            )
        self.assertTrue(result)
        self.assertEqual(
            calls,
            [
                "connect:smtp.example.test:587",
                "starttls",
                "login:smtp-user:smtp-secret",
                "send:owner@example.com:Pathwise session from Ada Lovelace",
                "close",
            ],
        )

        calls.clear()
        env_bad_port = dict(env)
        env_bad_port["PATHWISE_SMTP_PORT"] = "not-a-port"
        with patch("pathwise.recruiter_notify.load_dotenv", return_value=None), patch.dict(
            os.environ, env_bad_port, clear=False
        ), patch("pathwise.recruiter_notify.smtplib.SMTP", FakeSMTP):
            notify_recruiter_of_seed_use(
                recruiter_seed_code=self.seed_code,
                candidate_label="Ada Lovelace",
                used_at_utc="2026-08-30T10:00:00Z",
                completed_at_utc="2026-08-30T10:12:00Z",
                dashboard_path=self.dashboard,
                player_recruiter_id=None,
                execute=self.db.execute,
            )
        self.assertEqual(calls[0], "connect:smtp.example.test:587")
        self.assertIn("starttls", calls)

        calls.clear()
        env_no_user = dict(env)
        env_no_user["PATHWISE_SMTP_PORT"] = "2525"
        env_no_user["PATHWISE_SMTP_USER"] = ""
        with patch("pathwise.recruiter_notify.load_dotenv", return_value=None), patch.dict(
            os.environ, env_no_user, clear=False
        ), patch("pathwise.recruiter_notify.smtplib.SMTP", FakeSMTP):
            notify_recruiter_of_seed_use(
                recruiter_seed_code=self.seed_code,
                candidate_label="Ada Lovelace",
                used_at_utc="2026-08-30T10:00:00Z",
                completed_at_utc="2026-08-30T10:12:00Z",
                dashboard_path=self.dashboard,
                player_recruiter_id=None,
                execute=self.db.execute,
            )
        self.assertEqual(calls[0], "connect:smtp.example.test:2525")
        self.assertNotIn("starttls", calls)
        self.assertTrue(all(not item.startswith("login:") for item in calls))

    def test_warning_does_not_log_smtp_password_or_turso_token(self):
        secret = "smtp-secret-value"
        token = "turso-token-value"
        with patch("pathwise.recruiter_notify.load_dotenv", return_value=None), patch.dict(
            os.environ,
            {
                "PATHWISE_SMTP_HOST": "",
                "PATHWISE_SMTP_FROM": "from@example.test",
                "PATHWISE_SMTP_PASSWORD": secret,
                "TURSO_AUTH_TOKEN": token,
            },
            clear=False,
        ):
            with self.assertLogs("pathwise.recruiter_notify", level=logging.WARNING) as captured:
                notify_recruiter_of_seed_use(
                    recruiter_seed_code=self.seed_code,
                    candidate_label="Ada Lovelace",
                    used_at_utc="2026-08-30T10:00:00Z",
                    completed_at_utc="2026-08-30T10:12:00Z",
                    dashboard_path=self.dashboard,
                    player_recruiter_id=None,
                    execute=self.db.execute,
                )
        blob = "\n".join(captured.output)
        self.assertNotIn(secret, blob)
        self.assertNotIn(token, blob)


if __name__ == "__main__":
    unittest.main()
