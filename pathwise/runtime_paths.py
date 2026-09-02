"""Frozen-aware folders, embedded secrets, sidecar override, and writable files.

Frozen Pathwise.exe loads an obfuscated blob first (setdefault). A sidecar
pathwise.env next to the exe may override blob keys for operator debug.
Process env always wins. load_runtime_env never prints token values.
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
EMBEDDED_BLOB_NAME = "embedded_env.bin"
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


def default_meipass() -> Path | None:
    bundle = getattr(sys, "_MEIPASS", None)
    if not bundle:
        return None
    return Path(bundle)


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


def parse_env_text(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in text.splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key not in mapping:
            mapping[key] = value
    return mapping


def apply_env_mapping(
    mapping: dict[str, str],
    *,
    protected: set[str] | None = None,
    overwrite: set[str] | None = None,
) -> set[str]:
    prot = protected if protected is not None else set()
    over = overwrite if overwrite is not None else set()
    written: set[str] = set()
    for key, value in mapping.items():
        if key in prot:
            continue
        if key in over:
            os.environ[key] = value
            written.add(key)
            continue
        if key not in os.environ:
            os.environ[key] = value
            written.add(key)
    return written


def apply_env_file(
    path: str | Path,
    *,
    protected: set[str] | None = None,
    overwrite: set[str] | None = None,
) -> Path | None:
    env_path = Path(path)
    if not env_path.is_file():
        return None
    mapping = parse_env_text(env_path.read_text(encoding="utf-8"))
    apply_env_mapping(mapping, protected=protected, overwrite=overwrite)
    return env_path


def resolve_embedded_blob_path(
    *,
    frozen: bool | None = None,
    meipass: str | Path | None = None,
    blob_path: str | Path | None = None,
) -> Path | None:
    if blob_path is not None:
        path = Path(blob_path)
        return path if path.is_file() else None
    bundle = Path(meipass) if meipass is not None else default_meipass()
    use_frozen = is_frozen() if frozen is None else bool(frozen)
    if bundle is None:
        return None
    if not use_frozen and meipass is None:
        return None
    path = Path(bundle) / EMBEDDED_BLOB_NAME
    return path if path.is_file() else None


def load_embedded_mapping(path: str | Path) -> dict[str, str]:
    from pathwise.secret_blob import recover_env_bytes

    blob_path = Path(path)
    if not blob_path.is_file():
        return {}
    try:
        recovered = recover_env_bytes(blob_path.read_bytes())
        return parse_env_text(recovered.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


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
    meipass: str | Path | None = None,
    blob_path: str | Path | None = None,
    apply_embedded: bool | None = None,
) -> Path | None:
    protected = set(os.environ)
    use_frozen = is_frozen() if frozen is None else bool(frozen)
    should_embed = apply_embedded
    if should_embed is None:
        should_embed = bool(use_frozen) or blob_path is not None or meipass is not None
    blob_keys: set[str] = set()
    if should_embed and explicit is None:
        embedded = resolve_embedded_blob_path(
            frozen=use_frozen,
            meipass=meipass,
            blob_path=blob_path,
        )
        if embedded is not None:
            blob_keys = apply_env_mapping(
                load_embedded_mapping(embedded),
                protected=protected,
            )
    first: Path | None = None
    remaining_overwrite = set(blob_keys)
    for candidate in env_candidate_paths(
        explicit=explicit,
        environ=environ,
        frozen=frozen,
        executable=executable,
        cwd=cwd,
    ):
        path = Path(candidate)
        if not path.is_file():
            continue
        mapping = parse_env_text(path.read_text(encoding="utf-8"))
        file_overwrite = remaining_overwrite & set(mapping)
        apply_env_mapping(mapping, protected=protected, overwrite=file_overwrite)
        remaining_overwrite -= file_overwrite
        if first is None:
            first = path
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
        "# Pathwise recruiter sidecar. Operator debug next to Pathwise.exe.",
        "# Never email TURSO_AUTH_TOKEN. It is full database access.",
        "# Recruiters should not need this file when the zip was packed with --env.",
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
