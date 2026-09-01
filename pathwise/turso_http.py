"""Minimal Turso/libSQL SQL-over-HTTP client (stdlib only, no native libsql).

Store the official ``libsql://`` URL in ``pathwise.env`` (or ``.env``) next
to Pathwise.exe. HTTP calls convert it to ``https://.../v2/pipeline`` each
request. That conversion is not a one-time dashboard change.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class TursoConfigError(ValueError):
    """Missing URL, token, or unusable database URL."""


class TursoHttpError(RuntimeError):
    """Remote pipeline rejected the request."""


_pool_lock = threading.Lock()
_connections: dict[tuple[str, int], http.client.HTTPSConnection] = {}


def pipeline_url(database_url: str) -> str:
    """Return Hrana ``/v2/pipeline`` URL. Accepts ``libsql://`` or ``https://``."""
    raw = (database_url or "").strip()
    if not raw:
        raise TursoConfigError("TURSO_DATABASE_URL is empty")
    if raw.startswith("libsql://"):
        raw = "https://" + raw[len("libsql://") :]
    raw = raw.rstrip("/")
    if raw.endswith("/v2/pipeline"):
        return raw
    return raw + "/v2/pipeline"


def reset_http_connections() -> None:
    """Close pooled HTTPS connections. Tests call this between cases."""
    with _pool_lock:
        conns = list(_connections.values())
        _connections.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:
            pass


def _drop_connection(host: str, port: int) -> None:
    with _pool_lock:
        conn = _connections.pop((host, port), None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def _get_connection(host: str, port: int, timeout: float) -> http.client.HTTPSConnection:
    key = (host, port)
    with _pool_lock:
        conn = _connections.get(key)
        if conn is None:
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
            _connections[key] = conn
        return conn


def _http_post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise TursoHttpError("invalid Turso URL")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    last_exc: BaseException | None = None
    for attempt in range(2):
        conn = _get_connection(host, port, timeout)
        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            if response.status >= 400:
                detail = data.decode("utf-8", errors="replace")[:400]
                raise TursoHttpError(f"Turso HTTP {response.status}: {detail}")
            return data
        except TursoHttpError:
            raise
        except (http.client.HTTPException, OSError) as exc:
            last_exc = exc
            _drop_connection(host, port)
            if attempt == 0:
                continue
            raise TursoHttpError(str(exc) or "network error") from exc
    raise TursoHttpError(str(last_exc) or "network error")


def _parse_env_line(line: str) -> tuple[str, str] | None:
    from pathwise.runtime_paths import parse_env_line

    return parse_env_line(line)


def load_dotenv(path: str | Path | None = None) -> Path | None:
    """Load KEY=VALUE into os.environ when the key is unset. Does not override.

    With an explicit path, only that file is read. With path=None, search
    PATHWISE_ENV_FILE, the frozen exe folder, then cwd; in each folder try
    pathwise.env then .env.
    """
    from pathwise.runtime_paths import load_runtime_env

    return load_runtime_env(explicit=path)


def _credentials(
    database_url: str | None,
    auth_token: str | None,
) -> tuple[str, str]:
    load_dotenv()
    url = (database_url if database_url is not None else os.environ.get("TURSO_DATABASE_URL", "")).strip()
    token = (auth_token if auth_token is not None else os.environ.get("TURSO_AUTH_TOKEN", "")).strip()
    if not url:
        from pathwise.runtime_paths import recruiter_setup_message

        raise TursoConfigError(
            "TURSO_DATABASE_URL is missing. " + recruiter_setup_message()
        )
    if not token:
        from pathwise.runtime_paths import recruiter_setup_message

        raise TursoConfigError(
            "TURSO_AUTH_TOKEN is missing. " + recruiter_setup_message()
        )
    return url, token


def _hrana_arg(value: Any) -> dict[str, Any]:
    """Encode a Python value as a Hrana pipeline argument (never inlined into SQL)."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    return {"type": "text", "value": str(value)}


def execute_sql(
    sql: str,
    args: Sequence[Any] = (),
    *,
    database_url: str | None = None,
    auth_token: str | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Run one SQL statement over HTTP and return the pipeline JSON."""
    url, token = _credentials(database_url, auth_token)
    stmt = {"sql": sql, "args": [_hrana_arg(item) for item in args]}
    body = json.dumps(
        {
            "requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"},
            ]
        }
    ).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        raw = _http_post(pipeline_url(url), body, headers, timeout_s)
        return json.loads(raw.decode())
    except TursoHttpError:
        raise
    except json.JSONDecodeError as exc:
        raise TursoHttpError("Turso returned invalid JSON") from exc


def ping(
    *,
    database_url: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Cheap connectivity check."""
    return execute_sql(
        "SELECT 1 AS ok",
        database_url=database_url,
        auth_token=auth_token,
    )


if __name__ == "__main__":
    print(json.dumps(ping(), indent=2))
