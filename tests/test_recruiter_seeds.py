"""Recruiter seed ownership: schema, register, lookup, UNIQUE conflict."""

from __future__ import annotations

import unittest

from pathwise.recruiter_accounts import apply_recruiter_schema, create_recruiter
from pathwise.recruiter_seeds import (
    RecruiterSeedConflictError,
    lookup_recruiter_seed,
    register_recruiter_seed,
)
from pathwise.session_seed import encode_recruiter_seed
from tests.test_recruiter_accounts import FakePipeline


class TestRecruiterSeeds(unittest.TestCase):
    def setUp(self):
        self.db = FakePipeline()
        self.addCleanup(self.db.conn.close)
        apply_recruiter_schema(execute=self.db.execute)
        self.owner = create_recruiter(
            "owner@example.com",
            "password1",
            execute=self.db.execute,
        )
        self.seed_code = encode_recruiter_seed(4242, "normal", 1)

    def test_schema_apply_creates_recruiter_seeds_table(self):
        row = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'recruiter_seeds'"
        ).fetchone()
        self.assertIsNotNone(row)
        cols = {
            info[1]
            for info in self.db.conn.execute("PRAGMA table_info(recruiter_seeds)").fetchall()
        }
        self.assertEqual(cols, {"seed_code", "recruiter_id", "created_at"})

    def test_register_and_lookup_returns_owner(self):
        register_recruiter_seed(
            self.seed_code,
            self.owner.id,
            execute=self.db.execute,
        )
        found = lookup_recruiter_seed(self.seed_code, execute=self.db.execute)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, self.owner.id)
        self.assertEqual(found.email, "owner@example.com")
        stored = self.db.conn.execute(
            "SELECT recruiter_id, created_at FROM recruiter_seeds WHERE seed_code = ?",
            (self.seed_code,),
        ).fetchone()
        self.assertEqual(stored[0], self.owner.id)
        self.assertRegex(stored[1], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_unknown_code_returns_none(self):
        self.assertIsNone(
            lookup_recruiter_seed("9120000000001", execute=self.db.execute)
        )

    def test_unique_seed_code_raises_conflict(self):
        register_recruiter_seed(
            self.seed_code,
            self.owner.id,
            execute=self.db.execute,
        )
        other = create_recruiter(
            "other@example.com",
            "password1",
            execute=self.db.execute,
        )
        with self.assertRaises(RecruiterSeedConflictError):
            register_recruiter_seed(
                self.seed_code,
                other.id,
                execute=self.db.execute,
            )
        row = self.db.conn.execute(
            "SELECT recruiter_id FROM recruiter_seeds WHERE seed_code = ?",
            (self.seed_code,),
        ).fetchone()
        self.assertEqual(row[0], self.owner.id)

    def test_lookup_blank_code_returns_none(self):
        self.assertIsNone(lookup_recruiter_seed("", execute=self.db.execute))
        self.assertIsNone(lookup_recruiter_seed("   ", execute=self.db.execute))

    def test_register_reraises_when_error_is_not_missing_table(self):
        def boom(_sql, _args=(), **_kwargs):
            raise RuntimeError("disk I/O error")

        with self.assertRaises(RuntimeError):
            register_recruiter_seed(self.seed_code, self.owner.id, execute=boom)

    def test_register_applies_schema_when_seeds_table_missing(self):
        self.db.conn.execute("DROP TABLE recruiter_seeds")
        self.db.conn.commit()
        register_recruiter_seed(
            self.seed_code,
            self.owner.id,
            execute=self.db.execute,
        )
        found = lookup_recruiter_seed(self.seed_code, execute=self.db.execute)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, self.owner.id)


if __name__ == "__main__":
    unittest.main()
