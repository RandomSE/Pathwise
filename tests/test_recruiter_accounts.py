"""Recruiter account data plane: schema, signup, auth, code entitlement."""

from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pathwise.recruiter_accounts import (
    RecruiterAuthError,
    RecruiterDuplicateEmailError,
    RecruiterRecord,
    RecruiterValidationError,
    apply_recruiter_schema,
    authenticate_recruiter,
    can_generate_codes,
    create_recruiter,
    require_billing_enabled,
)
from pathwise.turso_http import TursoHttpError
from pathwise.session_seed import encode_recruiter_seed


ROOT = Path(__file__).resolve().parents[1]


class FakePipeline:
    """In-memory SQLite stand-in that returns Hrana-shaped execute payloads."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, args=(), **_kwargs):
        bound = tuple(args)
        self.calls.append((sql, bound))
        try:
            cur = self.conn.execute(sql, bound)
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            return {
                "results": [
                    {"type": "error", "error": {"message": str(exc)}}
                ]
            }
        cols = []
        rows = []
        if cur.description is not None:
            cols = [{"name": d[0]} for d in cur.description]
            for row in cur.fetchall():
                cells = []
                for value in row:
                    if value is None:
                        cells.append({"type": "null"})
                    elif isinstance(value, int) and not isinstance(value, bool):
                        cells.append({"type": "integer", "value": str(value)})
                    else:
                        cells.append({"type": "text", "value": str(value)})
                rows.append(cells)
        return {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {"cols": cols, "rows": rows},
                    },
                }
            ]
        }


def _record(
    *,
    active: int = 1,
    billing_exempt: int = 1,
    trial_active: int = 0,
    billing_date: str | None = None,
) -> RecruiterRecord:
    return RecruiterRecord(
        id="abc",
        email="a@b.co",
        billing_date=billing_date,
        active=active,
        trial_active=trial_active,
        billing_exempt=billing_exempt,
        tier="basic",
        company=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


class TestRequireBillingPolicy(unittest.TestCase):
    def test_default_and_falsey_are_off(self):
        with patch.dict(os.environ, {"PATHWISE_REQUIRE_BILLING": "sentinel"}, clear=False):
            os.environ.pop("PATHWISE_REQUIRE_BILLING", None)
            self.assertFalse(require_billing_enabled())
        for raw in ("", "0", "false", "no", "FALSE", "No"):
            with patch.dict(os.environ, {"PATHWISE_REQUIRE_BILLING": raw}, clear=False):
                self.assertFalse(require_billing_enabled())

    def test_truthy_is_on(self):
        for raw in ("1", "true", "yes", "on", "TRUE"):
            with patch.dict(os.environ, {"PATHWISE_REQUIRE_BILLING": raw}, clear=False):
                self.assertTrue(require_billing_enabled())


class TestRecruiterSchemaAndSignup(unittest.TestCase):
    def setUp(self):
        self.db = FakePipeline()
        self.addCleanup(self.db.conn.close)
        apply_recruiter_schema(execute=self.db.execute)
        self._billing_env = os.environ.pop("PATHWISE_REQUIRE_BILLING", None)

    def tearDown(self):
        if self._billing_env is None:
            os.environ.pop("PATHWISE_REQUIRE_BILLING", None)
        else:
            os.environ["PATHWISE_REQUIRE_BILLING"] = self._billing_env

    def test_launch_signup_is_entitled_and_hashed(self):
        rec = create_recruiter(
            "  Foo@Bar.Example  ",
            "password1",
            execute=self.db.execute,
        )
        self.assertIsInstance(rec, RecruiterRecord)
        self.assertEqual(rec.email, "foo@bar.example")
        self.assertEqual(rec.active, 1)
        self.assertEqual(rec.billing_exempt, 1)
        self.assertEqual(rec.trial_active, 0)
        self.assertIsNone(rec.billing_date)
        self.assertIsNone(rec.company)
        self.assertEqual(rec.tier, "basic")
        self.assertTrue(can_generate_codes(rec))
        self.assertFalse(hasattr(rec, "password_hash"))
        self.assertNotIn("password", repr(rec).lower())
        self.assertNotIn("password", str(rec).lower())
        self.assertEqual(len(rec.id), 32)
        row = self.db.conn.execute(
            "SELECT password_hash, email, billing_exempt, active, "
            "trial_active, billing_date, company, tier FROM recruiters"
        ).fetchone()
        self.assertEqual(row[1], "foo@bar.example")
        self.assertTrue(str(row[0]).startswith("$argon2id$"))
        self.assertNotIn("password1", str(row[0]))
        self.assertEqual(row[2:], (1, 1, 0, None, None, "basic"))
        insert_sql = next(sql for sql, _ in self.db.calls if "INSERT INTO recruiters" in sql)
        self.assertIn("?", insert_sql)
        self.assertNotIn("password1", insert_sql)
        self.assertNotIn("Foo@Bar.Example", insert_sql)

    def test_login_returns_token_once_hashed_at_rest(self):
        create_recruiter("user@example.com", "password1", execute=self.db.execute)
        rec, token = authenticate_recruiter(
            "User@Example.com",
            "password1",
            execute=self.db.execute,
        )
        self.assertEqual(rec.email, "user@example.com")
        self.assertTrue(token)
        self.assertNotEqual(token, hashlib.sha256(token.encode("ascii")).hexdigest())
        stored = self.db.conn.execute(
            "SELECT token_hash, expires_at, created_at FROM recruiter_sessions"
        ).fetchone()
        self.assertEqual(stored[0], hashlib.sha256(token.encode("ascii")).hexdigest())
        self.assertNotEqual(stored[0], token)
        created = datetime.fromisoformat(stored[2].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(stored[1].replace("Z", "+00:00"))
        delta = expires - created
        self.assertGreaterEqual(delta, timedelta(days=7) - timedelta(seconds=2))
        self.assertLessEqual(delta, timedelta(days=7) + timedelta(seconds=2))

    def test_require_billing_on_new_signup_cannot_generate_grandfather_can(self):
        launch = create_recruiter(
            "launch@example.com",
            "password1",
            execute=self.db.execute,
        )
        self.assertTrue(can_generate_codes(launch))
        with patch.dict(os.environ, {"PATHWISE_REQUIRE_BILLING": "1"}, clear=False):
            billed = create_recruiter(
                "new@example.com",
                "password1",
                execute=self.db.execute,
            )
            self.assertEqual(billed.billing_exempt, 0)
            self.assertEqual(billed.active, 0)
            self.assertEqual(billed.trial_active, 0)
            self.assertIsNone(billed.billing_date)
            self.assertFalse(can_generate_codes(billed))
            launch_row = self.db.conn.execute(
                "SELECT billing_exempt, active FROM recruiters WHERE email = ?",
                ("launch@example.com",),
            ).fetchone()
            self.assertEqual(launch_row, (1, 1))
            self.assertTrue(can_generate_codes(launch))
            self.assertEqual(
                self.db.conn.execute("SELECT COUNT(*) FROM recruiters").fetchone()[0],
                2,
            )
            self.assertFalse(
                any("UPDATE recruiters" in sql for sql, _ in self.db.calls)
            )

    def test_duplicate_email_and_case_uniqueness(self):
        create_recruiter("Foo@Bar.example", "password1", execute=self.db.execute)
        with self.assertRaises(RecruiterDuplicateEmailError):
            create_recruiter("foo@bar.example", "password1", execute=self.db.execute)

    def test_short_password_and_invalid_email_rejected(self):
        with self.assertRaises(RecruiterValidationError):
            create_recruiter("ok@example.com", "short", execute=self.db.execute)
        with self.assertRaises(RecruiterValidationError):
            create_recruiter("ok@example.com", "", execute=self.db.execute)
        with self.assertRaises(RecruiterValidationError):
            create_recruiter("", "password1", execute=self.db.execute)
        with self.assertRaises(RecruiterValidationError):
            create_recruiter("not-an-email", "password1", execute=self.db.execute)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM recruiters").fetchone()[0],
            0,
        )

    def test_wrong_password_and_unknown_email_are_generic(self):
        create_recruiter("user@example.com", "password1", execute=self.db.execute)
        with self.assertRaises(RecruiterAuthError) as bad:
            authenticate_recruiter("user@example.com", "wrongpass", execute=self.db.execute)
        with self.assertRaises(RecruiterAuthError) as missing:
            authenticate_recruiter("nobody@example.com", "password1", execute=self.db.execute)
        self.assertEqual(str(bad.exception), str(missing.exception))
        self.assertNotIn("unknown", str(bad.exception).lower())
        self.assertNotIn("password", str(bad.exception).lower())

    def test_inactive_non_exempt_without_trial_or_billing_cannot_generate(self):
        rec = _record(active=0, billing_exempt=0, trial_active=0, billing_date=None)
        self.assertFalse(can_generate_codes(rec))
        self.assertFalse(can_generate_codes(_record(active=0, billing_exempt=1)))
        self.assertTrue(can_generate_codes(_record(active=1, billing_exempt=0, trial_active=1)))
        self.assertTrue(
            can_generate_codes(
                _record(active=1, billing_exempt=0, billing_date="2026-08-01T00:00:00Z")
            )
        )
        self.assertFalse(
            can_generate_codes(_record(active=1, billing_exempt=0, billing_date=""))
        )

    def test_corrupt_hash_is_generic_auth_error(self):
        create_recruiter("user@example.com", "password1", execute=self.db.execute)
        self.db.conn.execute(
            "UPDATE recruiters SET password_hash = ? WHERE email = ?",
            ("not-an-argon2-hash", "user@example.com"),
        )
        self.db.conn.commit()
        with self.assertRaises(RecruiterAuthError):
            authenticate_recruiter("user@example.com", "password1", execute=self.db.execute)


class TestPipelineParsing(unittest.TestCase):
    def test_non_unique_pipeline_error_raises_http_error(self):
        def boom(sql, args=()):
            return {"results": [{"type": "error", "error": {"message": "disk I/O error"}}]}

        with self.assertRaises(TursoHttpError):
            create_recruiter("ok@example.com", "password1", execute=boom)

    def test_error_payload_shapes_and_empty_result(self):
        from pathwise.recruiter_accounts import (
            _as_int,
            _cell_value,
            _pipeline_execute_result,
        )

        self.assertEqual(_pipeline_execute_result({}), {"cols": [], "rows": []})
        self.assertEqual(
            _pipeline_execute_result({"results": [{"type": "ok", "response": {}}]}),
            {"cols": [], "rows": []},
        )
        with self.assertRaises(TursoHttpError):
            _pipeline_execute_result({"results": [{"type": "error", "error": "nope"}]})
        self.assertEqual(_cell_value("raw"), "raw")
        self.assertEqual(_as_int(None), 0)
        self.assertEqual(_as_int(""), 0)


class TestBackwardCompatIsolation(unittest.TestCase):
    def test_accounts_module_does_not_import_pre_game_or_seed_codec(self):
        src = (ROOT / "pathwise" / "recruiter_accounts.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        blob = " ".join(imported)
        self.assertNotIn("pre_game", blob)
        self.assertNotIn("session_seed", blob)

    def test_game_start_does_not_auto_migrate(self):
        main_text = (ROOT / "main.py").read_text(encoding="utf-8")
        window_text = (ROOT / "pathwise" / "pathwise_window.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("apply_recruiter_schema", main_text)
        self.assertNotIn("apply_recruiter_schema", window_text)
        self.assertNotIn("recruiter_accounts", main_text)

    def test_encode_recruiter_seed_unchanged_by_this_slice(self):
        encoded = encode_recruiter_seed(424242, "hard", 4)
        self.assertEqual(encoded, "9420000424242")


if __name__ == "__main__":
    unittest.main()
