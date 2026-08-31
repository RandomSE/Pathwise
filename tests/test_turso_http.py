"""Turso HTTP helper: URL normalize, dotenv load, pipeline execute."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.turso_http import (
    TursoConfigError,
    TursoHttpError,
    _drop_connection,
    _http_post,
    execute_sql,
    load_dotenv,
    ping,
    pipeline_url,
    reset_http_connections,
)


def _https_patch(response_body: bytes, *, status: int = 200, captured: dict | None = None):
    conns: list[object] = []

    class FakeResp:
        def __init__(self):
            self.status = status

        def read(self):
            return response_body

    class FakeHTTPS:
        def __init__(self, host, port=443, timeout=20):
            conns.append(self)
            self.host = host
            self.port = port
            self.timeout = timeout

        def request(self, method, path, body=None, headers=None):
            hdrs = headers or {}
            if captured is not None:
                captured["url"] = f"https://{self.host}{path}"
                captured["auth"] = hdrs.get("Authorization")
                if body:
                    raw = body.decode() if isinstance(body, bytes) else body
                    captured["body"] = json.loads(raw)

        def getresponse(self):
            return FakeResp()

        def close(self):
            return None

    reset_http_connections()
    return patch("pathwise.turso_http.http.client.HTTPSConnection", FakeHTTPS), conns


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
    def setUp(self):
        reset_http_connections()

    def tearDown(self):
        reset_http_connections()

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
        https_patch, _conns = _https_patch(json.dumps(payload).encode(), captured=captured)
        with https_patch:
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
        https_patch, _conns = _https_patch(b'{"results":[]}', captured=captured)
        with https_patch:
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
        https_patch, _conns = _https_patch(b'{"results":[]}', captured=captured)
        with https_patch:
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
        https_patch, _conns = _https_patch(b'{"results":[]}', captured=captured)
        with https_patch:
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
        https_patch, _conns = _https_patch(b'{"error":"nope"}', status=401)
        with https_patch:
            with self.assertRaises(TursoHttpError):
                execute_sql(
                    "SELECT 1",
                    database_url="https://host.turso.io",
                    auth_token="bad",
                )

    def test_invalid_json_becomes_turso_http_error(self):
        https_patch, _conns = _https_patch(b"not-json")
        with https_patch:
            with self.assertRaises(TursoHttpError) as ctx:
                execute_sql(
                    "SELECT 1",
                    database_url="https://host.turso.io",
                    auth_token="tok",
                )
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_http_post_rejects_url_without_host(self):
        with self.assertRaises(TursoHttpError) as ctx:
            _http_post("https:///v2/pipeline", b"{}", {}, 1.0)
        self.assertIn("invalid Turso URL", str(ctx.exception))

    def test_http_post_keeps_query_string_on_path(self):
        captured = {}
        https_patch, _conns = _https_patch(b'{"ok":true}', captured=captured)
        with https_patch:
            data = _http_post(
                "https://host.turso.io/v2/pipeline?foo=1",
                b"{}",
                {"Content-Type": "application/json"},
                1.0,
            )
        self.assertEqual(data, b'{"ok":true}')
        self.assertEqual(captured["url"], "https://host.turso.io/v2/pipeline?foo=1")

    def test_http_post_retries_oserror_then_succeeds(self):
        class FlakyHTTPS:
            calls = 0

            def __init__(self, host, port=443, timeout=20):
                self.host = host
                self.port = port
                self.timeout = timeout

            def request(self, method, path, body=None, headers=None):
                FlakyHTTPS.calls += 1
                if FlakyHTTPS.calls == 1:
                    raise OSError("broken pipe")

            def getresponse(self):
                class FakeResp:
                    status = 200

                    def read(self):
                        return b'{"ok":true}'

                return FakeResp()

            def close(self):
                return None

        reset_http_connections()
        with patch("pathwise.turso_http.http.client.HTTPSConnection", FlakyHTTPS):
            data = _http_post(
                "https://host.turso.io/v2/pipeline",
                b"{}",
                {},
                1.0,
            )
        self.assertEqual(data, b'{"ok":true}')
        self.assertEqual(FlakyHTTPS.calls, 2)

    def test_http_post_raises_after_retry_exhausted(self):
        class AlwaysFail:
            def __init__(self, host, port=443, timeout=20):
                pass

            def request(self, method, path, body=None, headers=None):
                raise OSError("")

            def close(self):
                return None

        reset_http_connections()
        with patch("pathwise.turso_http.http.client.HTTPSConnection", AlwaysFail):
            with self.assertRaises(TursoHttpError) as ctx:
                _http_post("https://host.turso.io/v2/pipeline", b"{}", {}, 1.0)
        self.assertIn("network error", str(ctx.exception))

    def test_reset_and_drop_tolerate_close_errors(self):
        class BoomConn:
            def close(self):
                raise OSError("already closed")

        from pathwise import turso_http as mod

        with mod._pool_lock:
            mod._connections[("h", 443)] = BoomConn()
        reset_http_connections()
        _drop_connection("missing", 443)
        with mod._pool_lock:
            mod._connections[("h2", 443)] = BoomConn()
        _drop_connection("h2", 443)

    def test_second_execute_reuses_https_connection(self):
        https_patch, conns = _https_patch(b'{"results":[]}')
        with https_patch:
            execute_sql(
                "SELECT 1",
                database_url="https://host.turso.io",
                auth_token="tok",
            )
            execute_sql(
                "SELECT 2",
                database_url="https://host.turso.io",
                auth_token="tok",
            )
        self.assertEqual(len(conns), 1)


if __name__ == "__main__":
    unittest.main()
