"""Minimal Turso/libSQL SQL-over-HTTP client (stdlib only, no native libsql).

Store the official ``libsql://`` URL in ``.env``. HTTP calls convert it to
``https://.../v2/pipeline`` each request. That conversion is not a one-time
dashboard change.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class TursoConfigError(ValueError):
    """Missing URL, token, or unusable database URL."""


class TursoHttpError(RuntimeError):
    """Remote pipeline rejected the request."""


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


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[7:].strip()
    if "=" not in text:
        return None
    key, _, value = text.partition("=")
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def load_dotenv(path: str | Path | None = None) -> Path | None:
    """Load KEY=VALUE into os.environ when the key is unset. Does not override."""
    env_path = Path(path) if path is not None else Path.cwd() / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)
    return env_path


def _credentials(
    database_url: str | None,
    auth_token: str | None,
) -> tuple[str, str]:
    load_dotenv()
    url = (database_url if database_url is not None else os.environ.get("TURSO_DATABASE_URL", "")).strip()
    token = (auth_token if auth_token is not None else os.environ.get("TURSO_AUTH_TOKEN", "")).strip()
    if not url:
        raise TursoConfigError(
            "TURSO_DATABASE_URL is missing. Copy .env.example to .env and paste the libsql URL."
        )
    if not token:
        raise TursoConfigError(
            "TURSO_AUTH_TOKEN is missing. Paste a database token into .env (never commit it)."
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
    request = urllib.request.Request(
        pipeline_url(url),
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise TursoHttpError(f"Turso HTTP {exc.code}: {detail}") from exc


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
