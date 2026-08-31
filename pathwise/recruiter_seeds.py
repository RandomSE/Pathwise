"""Ownership of recruiter-generated shareable seeds (Turso SQL).

Apply schema via apply_recruiter_schema. Do not auto-migrate on game start.
Never print TURSO_AUTH_TOKEN.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pathwise.recruiter_accounts import (
    RecruiterDuplicateEmailError,
    RecruiterRecord,
    apply_recruiter_schema,
    _pipeline_execute_result,
    _record_from_row,
    _rows_as_dicts,
    _utc_now_iso,
)
from pathwise.turso_http import execute_sql

ExecuteFn = Callable[..., dict[str, Any]]


class RecruiterSeedConflictError(ValueError):
    """seed_code is already registered."""


def _missing_seeds_table(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "no such table" in message and "recruiter_seeds" in message


def register_recruiter_seed(
    seed_code: str,
    recruiter_id: str,
    *,
    execute: ExecuteFn | None = None,
) -> None:
    exec_fn = execute or execute_sql
    sql = (
        "INSERT INTO recruiter_seeds (seed_code, recruiter_id, created_at) "
        "VALUES (?, ?, ?)"
    )
    args = (str(seed_code).strip(), str(recruiter_id), _utc_now_iso())

    def _insert() -> None:
        payload = exec_fn(sql, args)
        try:
            _pipeline_execute_result(payload)
        except RecruiterDuplicateEmailError:
            raise RecruiterSeedConflictError("seed already registered") from None

    try:
        _insert()
    except RecruiterSeedConflictError:
        raise
    except Exception as exc:
        if not _missing_seeds_table(exc):
            raise
        apply_recruiter_schema(execute=exec_fn)
        _insert()


def lookup_recruiter_seed(
    seed_code: str,
    *,
    execute: ExecuteFn | None = None,
) -> RecruiterRecord | None:
    cleaned = str(seed_code).strip()
    if not cleaned:
        return None
    exec_fn = execute or execute_sql
    payload = exec_fn(
        "SELECT r.id, r.email, r.billing_date, r.active, r.trial_active, "
        "r.billing_exempt, r.tier, r.company, r.created_at, r.updated_at "
        "FROM recruiter_seeds s "
        "JOIN recruiters r ON r.id = s.recruiter_id "
        "WHERE s.seed_code = ?",
        (cleaned,),
    )
    rows = _rows_as_dicts(_pipeline_execute_result(payload))
    if not rows:
        return None
    return _record_from_row(rows[0])
