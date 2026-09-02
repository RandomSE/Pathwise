"""Recruiter account library (Turso SQL).

In-game login/register views may call this module. A future API process can
too. Never print TURSO_AUTH_TOKEN, raw passwords, or password_hash.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from pathwise.turso_http import TursoHttpError, execute_sql

ExecuteFn = Callable[..., dict[str, Any]]

MIN_PASSWORD_LENGTH = 8
SESSION_TTL_DAYS = 7
TIER_BASIC = "basic"
_AUTH_FAIL_MESSAGE = "Invalid credentials"
_TRUE_BILLING_FLAGS = frozenset({"1", "true", "yes", "on"})
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_HASHER = PasswordHasher()
_SCHEMA_PATH = Path(__file__).with_name("recruiter_schema.sql")


class RecruiterValidationError(ValueError):
    """Empty or invalid email, or password shorter than MIN_PASSWORD_LENGTH."""


class RecruiterDuplicateEmailError(ValueError):
    """Normalized email already exists."""


class RecruiterAuthError(ValueError):
    """Generic invalid credentials (unknown email or bad password)."""


@dataclass(frozen=True)
class RecruiterRecord:
    id: str
    email: str
    billing_date: str | None
    active: int
    trial_active: int
    billing_exempt: int
    tier: str
    company: str | None
    created_at: str
    updated_at: str


def require_billing_enabled() -> bool:
    """PATHWISE_REQUIRE_BILLING; default off (unset, 0, false, no)."""
    raw = os.environ.get("PATHWISE_REQUIRE_BILLING")
    if raw is None:
        return False
    return raw.strip().lower() in _TRUE_BILLING_FLAGS


def apply_recruiter_schema(*, execute: ExecuteFn | None = None) -> None:
    """Create recruiters and recruiter_sessions. Admin/API only, not game start."""
    from pathwise.runtime_paths import package_resource

    exec_fn = execute or execute_sql
    schema = package_resource("pathwise", "recruiter_schema.sql")
    text = schema.read_text(encoding="utf-8")
    for statement in _sql_statements(text):
        _pipeline_execute_result(exec_fn(statement, ()))


def create_recruiter(
    email: str,
    password: str,
    *,
    execute: ExecuteFn | None = None,
) -> RecruiterRecord:
    exec_fn = execute or execute_sql
    normalized = _normalize_email(email)
    _validate_email(normalized)
    _validate_password(password)
    now = _utc_now_iso()
    recruiter_id = uuid.uuid4().hex
    require_billing = require_billing_enabled()
    billing_exempt = 0 if require_billing else 1
    active = 0 if require_billing else 1
    payload = exec_fn(
        "INSERT INTO recruiters ("
        "id, email, password_hash, billing_date, active, trial_active, "
        "billing_exempt, tier, company, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            recruiter_id,
            normalized,
            _PASSWORD_HASHER.hash(password),
            None,
            active,
            0,
            billing_exempt,
            TIER_BASIC,
            None,
            now,
            now,
        ),
    )
    _pipeline_execute_result(payload)
    return RecruiterRecord(
        id=recruiter_id,
        email=normalized,
        billing_date=None,
        active=active,
        trial_active=0,
        billing_exempt=billing_exempt,
        tier=TIER_BASIC,
        company=None,
        created_at=now,
        updated_at=now,
    )


def authenticate_recruiter(
    email: str,
    password: str,
    *,
    execute: ExecuteFn | None = None,
) -> tuple[RecruiterRecord, str]:
    exec_fn = execute or execute_sql
    normalized = _normalize_email(email)
    payload = exec_fn(
        "SELECT id, email, password_hash, billing_date, active, trial_active, "
        "billing_exempt, tier, company, created_at, updated_at "
        "FROM recruiters WHERE email = ?",
        (normalized,),
    )
    rows = _rows_as_dicts(_pipeline_execute_result(payload))
    if not rows:
        raise RecruiterAuthError(_AUTH_FAIL_MESSAGE)
    row = rows[0]
    try:
        _PASSWORD_HASHER.verify(str(row["password_hash"]), password)
    except (VerifyMismatchError, InvalidHashError, TypeError, ValueError):
        raise RecruiterAuthError(_AUTH_FAIL_MESSAGE) from None
    record = _record_from_row(row)
    created = datetime.now(timezone.utc).replace(microsecond=0)
    expires = created + timedelta(days=SESSION_TTL_DAYS)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    session_payload = exec_fn(
        "INSERT INTO recruiter_sessions ("
        "id, recruiter_id, token_hash, expires_at, created_at"
        ") VALUES (?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            record.id,
            token_hash,
            _iso_z(expires),
            _iso_z(created),
        ),
    )
    _pipeline_execute_result(session_payload)
    return record, token


def can_generate_codes(record: RecruiterRecord) -> bool:
    if int(record.active) != 1:
        return False
    if int(record.billing_exempt) == 1:
        return True
    if int(record.trial_active) == 1:
        return True
    billing = record.billing_date
    return billing is not None and str(billing).strip() != ""


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _validate_email(email: str) -> None:
    if not email or _EMAIL_RE.match(email) is None:
        raise RecruiterValidationError("Invalid email")


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RecruiterValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )


def _utc_now_iso() -> str:
    return _iso_z(datetime.now(timezone.utc).replace(microsecond=0))


def _iso_z(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    for chunk in text.split(";"):
        kept: list[str] = []
        for line in chunk.splitlines():
            if line.strip().startswith("--"):
                continue
            kept.append(line)
        statement = "\n".join(kept).strip()
        if statement:
            statements.append(statement)
    return statements


def _raise_for_pipeline_message(message: str) -> None:
    if "UNIQUE" in message.upper():
        raise RecruiterDuplicateEmailError("Email already registered")
    raise TursoHttpError(message)


def _pipeline_execute_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or []
    if not results:
        return {"cols": [], "rows": []}
    first = results[0]
    if first.get("type") == "error":
        err = first.get("error") or {}
        if isinstance(err, dict):
            message = str(err.get("message") or "Turso pipeline error")
        else:
            message = str(err)
        _raise_for_pipeline_message(message)
    response = first.get("response") or {}
    result = response.get("result")
    if not isinstance(result, dict):
        return {"cols": [], "rows": []}
    return result


def _cell_value(cell: Any) -> Any:
    if not isinstance(cell, dict):
        return cell
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell.get("value", 0))
    return cell.get("value")


def _rows_as_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    cols = [column.get("name") for column in result.get("cols") or []]
    rows: list[dict[str, Any]] = []
    for raw_row in result.get("rows") or []:
        values = [_cell_value(cell) for cell in raw_row]
        rows.append(dict(zip(cols, values)))
    return rows


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def _record_from_row(row: dict[str, Any]) -> RecruiterRecord:
    billing = row.get("billing_date")
    company = row.get("company")
    return RecruiterRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        billing_date=None if billing is None or billing == "" else str(billing),
        active=_as_int(row.get("active")),
        trial_active=_as_int(row.get("trial_active")),
        billing_exempt=_as_int(row.get("billing_exempt")),
        tier=str(row.get("tier") or TIER_BASIC),
        company=None if company is None or company == "" else str(company),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
