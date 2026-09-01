"""Frozen-aware folders, recruiter sidecar discovery, and writable session files.

Sidecar secrets live in pathwise.env (or .env) next to Pathwise.exe. They are
never baked into the binary. load_runtime_env uses setdefault and does not
override keys already present in os.environ.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RECRUITER_ENV_FILENAME = "pathwise.env"
ENV_BASENAMES = (RECRUITER_ENV_FILENAME, ".env")
SESSION_LOG_NAME = "logs.json"
DASHBOARD_HTML_NAME = "logs_dashboard.html"
CAR_DIAGNOSTICS_NAME = "car_diagnostics.jsonl"
REQUIRED_TURSO_KEYS = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")
SIDECAR_KEYS = (
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "PATHWISE_SMTP_HOST",
    "PATHWISE_SMTP_PORT",
    "PATHWISE_SMTP_USER",
    "PATHWISE_SMTP_PASSWORD",
    "PATHWISE_SMTP_FROM",
    "PATHWISE_REQUIRE_BILLING",
    "PATHWISE_SEED",
)

_ENV_COMMENTS = {
    "TURSO_DATABASE_URL": "libsql URL from the Turso dashboard (required for recruiter login)",
    "TURSO_AUTH_TOKEN": "database token; this is full DB access (never email it)",
    "PATHWISE_SMTP_HOST": "SMTP host for candidate-finish mail (optional)",
    "PATHWISE_SMTP_PORT": "SMTP port (default 587)",
    "PATHWISE_SMTP_USER": "SMTP username (optional)",
    "PATHWISE_SMTP_PASSWORD": "SMTP password (optional; email stays off until set)",
    "PATHWISE_SMTP_FROM": "From address for recruiter notify mail (optional)",
    "PATHWISE_REQUIRE_BILLING": "set 1 to require billing flags (optional, default off)",
    "PATHWISE_SEED": "fairness pin for scripted runs, not a recruiter secret (optional)",
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def parse_env_line(line: str) -> tuple[str, str] | None:
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


def apply_env_file(path: str | Path) -> Path | None:
    env_path = Path(path)
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)
    return env_path


def env_candidate_paths(
    *,
    explicit: str | Path | None = None,
    environ: dict[str, str] | None = None,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> list[Path]:
    if explicit is not None:
        return [Path(explicit)]
    env = environ if environ is not None else os.environ
    use_frozen = is_frozen() if frozen is None else bool(frozen)
    cwd_path = Path(cwd) if cwd is not None else Path.cwd()
    exe_path = Path(executable) if executable is not None else Path(sys.executable)
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    def add_folder(folder: Path) -> None:
        for name in ENV_BASENAMES:
            add(folder / name)

    raw = str(env.get("PATHWISE_ENV_FILE", "") or "").strip()
    if raw:
        named = Path(raw)
        if named.is_dir():
            add_folder(named)
        else:
            add(named)
    if use_frozen:
        add_folder(exe_path.resolve().parent)
    add_folder(cwd_path)
    return paths


def load_runtime_env(
    *,
    explicit: str | Path | None = None,
    environ: dict[str, str] | None = None,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path | None:
    first: Path | None = None
    for candidate in env_candidate_paths(
        explicit=explicit,
        environ=environ,
        frozen=frozen,
        executable=executable,
        cwd=cwd,
    ):
        loaded = apply_env_file(candidate)
        if loaded is not None and first is None:
            first = loaded
    return first


def writable_dir(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path:
    use_frozen = is_frozen() if frozen is None else bool(frozen)
    if use_frozen:
        exe = Path(executable) if executable is not None else Path(sys.executable)
        return exe.resolve().parent
    return Path(cwd) if cwd is not None else Path.cwd()


def env_setup_folder(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path:
    return writable_dir(frozen=frozen, executable=executable, cwd=cwd)


def session_log_path(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path:
    return writable_dir(frozen=frozen, executable=executable, cwd=cwd) / SESSION_LOG_NAME


def car_diagnostics_path(
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path:
    return writable_dir(frozen=frozen, executable=executable, cwd=cwd) / CAR_DIAGNOSTICS_NAME


def dashboard_hint_path(session_path: str | Path | None = None) -> Path:
    if session_path is None:
        session_path = session_log_path()
    path = Path(session_path)
    parent = path.parent
    if str(parent) in ("", "."):
        parent = Path.cwd()
    stem = path.stem or "logs"
    return parent / f"{stem}_dashboard.html"


def package_resource(*parts: str, meipass: str | Path | None = None) -> Path:
    bundle = meipass if meipass is not None else getattr(sys, "_MEIPASS", None)
    if bundle:
        candidate = Path(bundle).joinpath(*parts)
        if candidate.is_file():
            return candidate
    here = Path(__file__).resolve().parent
    if parts and parts[0] == "pathwise":
        local = here.joinpath(*parts[1:])
        if local.is_file():
            return local
    repo = here.parent.joinpath(*parts)
    if repo.is_file():
        return repo
    return here.joinpath(*parts)


def turso_ready(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    url = str(env.get("TURSO_DATABASE_URL", "") or "").strip()
    token = str(env.get("TURSO_AUTH_TOKEN", "") or "").strip()
    return bool(url and token)


def recruiter_setup_message(folder: str | Path | None = None) -> str:
    target = Path(folder) if folder is not None else env_setup_folder()
    return (
        f"Place {RECRUITER_ENV_FILENAME} in {target} "
        "(the folder that contains Pathwise.exe, not _internal). "
        "Required keys: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN."
    )


def _env_value_line(key: str, value: str) -> str:
    cleaned = str(value).replace("\r", "").replace("\n", "").strip()
    if any(ch in cleaned for ch in " #\t") or cleaned == "":
        if key == "PATHWISE_SMTP_PORT" and cleaned == "":
            cleaned = "587"
        if " " in cleaned or "#" in cleaned:
            cleaned = '"' + cleaned.replace('"', '\\"') + '"'
    return f"{key}={cleaned}"


def open_path_in_browser(path: str | Path) -> None:
    import webbrowser

    target = Path(path).expanduser()
    webbrowser.open(target.resolve().as_uri())


def write_pathwise_env(folder: str | Path, values: dict[str, str]) -> Path:
    target_dir = Path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / RECRUITER_ENV_FILENAME
    supplied = {str(key): "" if value is None else str(value) for key, value in values.items()}
    lines = [
        "# Pathwise recruiter sidecar. Keep this file next to Pathwise.exe.",
        "# Never email TURSO_AUTH_TOKEN. It is full database access.",
        "# Do not put this file inside _internal.",
        "",
    ]
    for key in SIDECAR_KEYS:
        comment = _ENV_COMMENTS.get(key)
        if comment:
            lines.append(f"# {comment}")
        lines.append(_env_value_line(key, supplied.get(key, "")))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
