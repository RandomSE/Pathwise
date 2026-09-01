"""Email a recruiter when someone else finishes a registered seed run.

Transport is stdlib smtplib. Inject send and execute in tests.
Never log PATHWISE_SMTP_PASSWORD or TURSO_AUTH_TOKEN.

The dashboard is zipped (application/zip) rather than attached as text/html.
HTML-plus-script attachments and "download the attached html" copy are common
junk-folder triggers. Date, Message-ID, a Pathwise From display name, Reply-To,
and a matching envelope sender are set on the wire message.

Inbox placement still needs SPF/DKIM/DMARC on PATHWISE_SMTP_FROM. This module
cannot publish DNS.

Env (load_dotenv does not override set keys): PATHWISE_SMTP_HOST,
PATHWISE_SMTP_PORT (default 587), PATHWISE_SMTP_USER, PATHWISE_SMTP_PASSWORD,
PATHWISE_SMTP_FROM.
"""

from __future__ import annotations

import io
import logging
import os
import smtplib
import zipfile
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any

from pathwise.recruiter_seeds import lookup_recruiter_seed
from pathwise.turso_http import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_SMTP_PORT = 587
_DASHBOARD_INNER_NAME = "logs_dashboard.html"
_DASHBOARD_ZIP_NAME = "logs_dashboard.zip"


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
        f"A Pathwise session finished.\n"
        f"\n"
        f"Candidate: {label}\n"
        f"Seed: {code}\n"
        f"Started (UTC): {used_at_utc}\n"
        f"Finished (UTC): {completed_at_utc}\n"
        f"\n"
        f"The zip file contains logs_dashboard.html for this run only. "
        f"Unzip it, then open that HTML file in a desktop browser to use replay "
        f"and round controls. Later sessions arrive as separate messages.\n"
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
        "attachment_filename": _DASHBOARD_ZIP_NAME,
        "attachment_bytes": _zip_dashboard_bytes(attachment_bytes),
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


def _zip_dashboard_bytes(html_bytes: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_DASHBOARD_INNER_NAME, html_bytes)
    return buffer.getvalue()


def _bare_email(addr: str) -> str:
    _name, parsed = parseaddr(addr)
    return (parsed or addr).strip()


def _from_header(addr: str) -> str:
    bare = _bare_email(addr)
    name, parsed = parseaddr(addr)
    display = name or "Pathwise"
    return formataddr((display, parsed or bare))


def _smtp_from_addr() -> str:
    load_dotenv()
    configured = os.environ.get("PATHWISE_SMTP_FROM", "").strip()
    if configured:
        return _bare_email(configured)
    user = os.environ.get("PATHWISE_SMTP_USER", "").strip()
    if "@" in user:
        return user
    return ""


def _smtp_ready() -> bool:
    load_dotenv()
    host = os.environ.get("PATHWISE_SMTP_HOST", "").strip()
    password = os.environ.get("PATHWISE_SMTP_PASSWORD", "")
    from_addr = _smtp_from_addr()
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
    sender = (from_addr or _smtp_from_addr()).strip()
    bare_from = _bare_email(sender)
    message = EmailMessage()
    message["From"] = _from_header(sender)
    message["To"] = to
    message["Subject"] = subject
    message["Reply-To"] = bare_from
    message["Date"] = formatdate(usegmt=True)
    domain = bare_from.rsplit("@", 1)[-1] if "@" in bare_from else "localhost"
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(body)
    message.add_attachment(
        attachment_bytes,
        maintype="application",
        subtype="zip",
        filename=attachment_filename or _DASHBOARD_ZIP_NAME,
    )
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if port == _DEFAULT_SMTP_PORT:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(message, from_addr=bare_from, to_addrs=[to])
