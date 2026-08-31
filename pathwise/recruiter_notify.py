"""Email a recruiter when someone else finishes a registered seed run.

Transport is stdlib smtplib. Inject send and execute in tests.
Never log PATHWISE_SMTP_PASSWORD or TURSO_AUTH_TOKEN.

Env (load_dotenv does not override set keys): PATHWISE_SMTP_HOST,
PATHWISE_SMTP_PORT (default 587), PATHWISE_SMTP_USER, PATHWISE_SMTP_PASSWORD,
PATHWISE_SMTP_FROM.
"""

from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from pathwise.recruiter_seeds import lookup_recruiter_seed
from pathwise.turso_http import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_SMTP_PORT = 587


def notify_recruiter_of_seed_use(
    *,
    recruiter_seed_code: str | None,
    candidate_label: str | None,
    used_at_utc: str,
    completed_at_utc: str,
    dashboard_path: str | Path | None,
    player_recruiter_id: str | None = None,
    execute: Callable[..., dict[str, Any]] | None = None,
    send: Callable[..., Any] | None = None,
) -> bool:
    code = str(recruiter_seed_code or "").strip()
    if not code:
        return False
    try:
        owner = lookup_recruiter_seed(code, execute=execute)
    except Exception:
        logger.warning("Recruiter seed lookup failed; skipping notify")
        return False
    if owner is None:
        return False
    if player_recruiter_id and str(player_recruiter_id) == str(owner.id):
        return False

    label = (candidate_label or "a candidate").strip() or "a candidate"
    subject = f"Pathwise session from {label}"
    body = (
        f"candidate: {label}\n"
        f"seed: {code}\n"
        f"used_at_utc: {used_at_utc}\n"
        f"completed_at_utc: {completed_at_utc}\n"
        "\n"
        "Download and open the attached logs_dashboard.html in a desktop browser. "
        "Use the in-page replay and round controls. This file is that one run only. "
        "Later runs arrive as separate mails.\n"
    )
    html_path = Path(dashboard_path) if dashboard_path is not None else None
    try:
        attachment_bytes = html_path.read_bytes() if html_path is not None else b""
    except OSError:
        logger.warning("Dashboard attachment missing; skipping notify")
        return False
    if not attachment_bytes:
        logger.warning("Dashboard attachment empty; skipping notify")
        return False

    payload = {
        "to": owner.email,
        "subject": subject,
        "body": body,
        "attachment_filename": "logs_dashboard.html",
        "attachment_bytes": attachment_bytes,
        "from_addr": _smtp_from_addr(),
    }
    sender = send if send is not None else _smtp_send
    if send is None and not _smtp_ready():
        logger.warning("SMTP is not configured; skipping recruiter notify")
        return False
    try:
        sender(**payload)
    except Exception:
        logger.warning("Recruiter notify send failed; session finish continues")
        return False
    return True


def _smtp_from_addr() -> str:
    load_dotenv()
    return os.environ.get("PATHWISE_SMTP_FROM", "").strip()


def _smtp_ready() -> bool:
    load_dotenv()
    host = os.environ.get("PATHWISE_SMTP_HOST", "").strip()
    password = os.environ.get("PATHWISE_SMTP_PASSWORD", "")
    from_addr = os.environ.get("PATHWISE_SMTP_FROM", "").strip()
    return bool(host and from_addr and password)


def _smtp_send(
    *,
    to: str,
    subject: str,
    body: str,
    attachment_filename: str,
    attachment_bytes: bytes,
    from_addr: str = "",
) -> None:
    load_dotenv()
    host = os.environ.get("PATHWISE_SMTP_HOST", "").strip()
    port_raw = os.environ.get("PATHWISE_SMTP_PORT", str(_DEFAULT_SMTP_PORT)).strip()
    try:
        port = int(port_raw or _DEFAULT_SMTP_PORT)
    except ValueError:
        port = _DEFAULT_SMTP_PORT
    user = os.environ.get("PATHWISE_SMTP_USER", "").strip()
    password = os.environ.get("PATHWISE_SMTP_PASSWORD", "")
    sender = (from_addr or os.environ.get("PATHWISE_SMTP_FROM", "")).strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(
        attachment_bytes,
        maintype="text",
        subtype="html",
        filename=attachment_filename,
    )
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if port == _DEFAULT_SMTP_PORT:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)
