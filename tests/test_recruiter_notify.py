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
