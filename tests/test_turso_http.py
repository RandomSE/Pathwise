"""Turso HTTP helper: URL normalize, dotenv load, pipeline execute."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.turso_http import (
    TursoConfigError,
    TursoHttpError,
    execute_sql,
    load_dotenv,
    ping,
    pipeline_url,
)


class TestPipelineUrl(unittest.TestCase):
    def test_libsql_becomes_https_pipeline(self):
        self.assertEqual(
            pipeline_url("libsql://pathwise-org.aws-eu-west-1.turso.io"),
            "https://pathwise-org.aws-eu-west-1.turso.io/v2/pipeline",
        )

    def test_https_gains_pipeline_suffix(self):
        self.assertEqual(
            pipeline_url("https://pathwise-org.turso.io"),
            "https://pathwise-org.turso.io/v2/pipeline",
        )

    def test_already_pipeline_is_idempotent(self):
        url = "https://pathwise-org.turso.io/v2/pipeline"
        self.assertEqual(pipeline_url(url), url)

    def test_trailing_slash_stripped(self):
        self.assertEqual(
            pipeline_url("libsql://host.turso.io/"),
            "https://host.turso.io/v2/pipeline",
        )

    def test_empty_raises(self):
        with self.assertRaises(TursoConfigError):
            pipeline_url("  ")


class TestLoadDotenv(unittest.TestCase):
    def test_loads_unset_keys_and_skips_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# comment\n"
                "not-a-pair\n"
                "=emptykey\n"
                "TURSO_DATABASE_URL=libsql://example.turso.io\n"
                "TURSO_AUTH_TOKEN='tok-from-file'\n"
                "export EXTRA=1\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv(path)
                self.assertEqual(
                    os.environ["TURSO_DATABASE_URL"],
                    "libsql://example.turso.io",
                )
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "tok-from-file")
                self.assertEqual(os.environ["EXTRA"], "1")
                self.assertEqual(loaded, path)

    def test_does_not_override_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TURSO_AUTH_TOKEN=from-file\n", encoding="utf-8")
            with patch.dict(os.environ, {"TURSO_AUTH_TOKEN": "from-shell"}, clear=True):
                load_dotenv(path)
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "from-shell")

    def test_missing_file_is_noop(self):
        missing = Path(tempfile.gettempdir()) / "pathwise-no-such.env"
        self.assertIsNone(load_dotenv(missing))


class TestExecuteSql(unittest.TestCase):
    def test_posts_pipeline_and_returns_json(self):
        payload = {
            "results": [
                {
                    "type": "ok",
                    "response": {
                        "type": "execute",
                        "result": {
                            "cols": [{"name": "ok"}],
                            "rows": [[{"type": "integer", "value": "1"}]],
                        },
                    },
                }
            ]
        }
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            captured["body"] = json.loads(req.data.decode())
            return io.BytesIO(json.dumps(payload).encode())

        with patch("pathwise.turso_http.urllib.request.urlopen", fake_urlopen):
            out = execute_sql(
                "SELECT 1 AS ok",
                database_url="libsql://host.turso.io",
                auth_token="secret-token",
            )
            ping_out = ping(
                database_url="libsql://host.turso.io",
                auth_token="secret-token",
            )
        self.assertEqual(out, payload)
        self.assertEqual(ping_out, payload)
        self.assertEqual(captured["url"], "https://host.turso.io/v2/pipeline")
        self.assertEqual(captured["auth"], "Bearer secret-token")
        self.assertEqual(
            captured["body"]["requests"][0]["stmt"]["sql"],
            "SELECT 1 AS ok",
        )
        self.assertEqual(captured["body"]["requests"][0]["stmt"]["args"], [])

    def test_empty_args_are_posted_without_changing_sql(self):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode())
            return io.BytesIO(b'{"results":[]}')

        with patch("pathwise.turso_http.urllib.request.urlopen", fake_urlopen):
            execute_sql(
                "SELECT 1 AS ok",
                (),
                database_url="libsql://host.turso.io",
                auth_token="secret-token",
            )
        stmt = captured["body"]["requests"][0]["stmt"]
        self.assertEqual(stmt["sql"], "SELECT 1 AS ok")
        self.assertEqual(stmt["args"], [])
        self.assertNotIn("()", stmt["sql"])

    def test_bound_value_with_quotes_is_not_concatenated_into_sql(self):
        captured = {}
        sql = "SELECT * FROM recruiters WHERE email = ?"
        injected = "o'reilly@example.com; DROP TABLE recruiters;--"

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode())
            return io.BytesIO(b'{"results":[]}')

        with patch("pathwise.turso_http.urllib.request.urlopen", fake_urlopen):
            execute_sql(
                sql,
                [injected],
                database_url="libsql://host.turso.io",
                auth_token="secret-token",
            )
        stmt = captured["body"]["requests"][0]["stmt"]
        self.assertEqual(stmt["sql"], sql)
        self.assertNotIn(injected, stmt["sql"])
        self.assertNotIn("o'reilly", stmt["sql"])
        self.assertEqual(stmt["args"], [{"type": "text", "value": injected}])

    def test_null_and_integer_args_use_hrana_types(self):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode())
            return io.BytesIO(b'{"results":[]}')

        with patch("pathwise.turso_http.urllib.request.urlopen", fake_urlopen):
            execute_sql(
                "INSERT INTO recruiters (email, active, company, flag) VALUES (?, ?, ?, ?)",
                ["a@b.co", 1, None, True],
                database_url="libsql://host.turso.io",
                auth_token="secret-token",
            )
        args = captured["body"]["requests"][0]["stmt"]["args"]
        self.assertEqual(
            args,
            [
                {"type": "text", "value": "a@b.co"},
                {"type": "integer", "value": "1"},
                {"type": "null"},
                {"type": "integer", "value": "1"},
            ],
        )

    def test_missing_token_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TursoConfigError):
                execute_sql(
                    "SELECT 1",
                    database_url="libsql://host.turso.io",
                    auth_token="",
                )

    def test_missing_url_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TursoConfigError):
                execute_sql("SELECT 1", database_url="", auth_token="tok")

    def test_http_error_becomes_turso_http_error(self):
        from urllib.error import HTTPError

        def boom(req, timeout=0):
            raise HTTPError(
                req.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"error":"nope"}'),
            )

        with patch("pathwise.turso_http.urllib.request.urlopen", boom):
            with self.assertRaises(TursoHttpError):
                execute_sql(
                    "SELECT 1",
                    database_url="https://host.turso.io",
                    auth_token="bad",
                )


if __name__ == "__main__":
    unittest.main()
