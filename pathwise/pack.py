"""Pack Pathwise-recruiter.zip with obfuscated operator secrets (not a vault).

Usage: python -m pathwise.pack --env pathwise.env

Reads a gitignored operator env file, writes a generated blob for PyInstaller,
builds the onedir freeze, and zips it. Refuses to ship a recruiter zip without
--env. Never prints TURSO_AUTH_TOKEN or SMTP password values.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from pathwise.runtime_paths import REQUIRED_TURSO_KEYS, parse_env_text
from pathwise.secret_blob import obfuscate_env_bytes

FORBIDDEN_ZIP_NAMES = frozenset(
    {
        "pathwise.env",
        ".env",
        "pathwise.env.example",
        ".env.example",
    }
)
SECRET_VALUE_KEYS = frozenset({"TURSO_AUTH_TOKEN", "PATHWISE_SMTP_PASSWORD"})
EMBEDDED_BLOB_REL = Path("pathwise") / "_generated" / "embedded_env.bin"
DEFAULT_ZIP_NAME = "Pathwise-recruiter.zip"
MISSING_ENV_MESSAGE = (
    "Refusing to write a recruiter zip without --env. "
    "Pass your gitignored operator env: python -m pathwise.pack --env pathwise.env"
)


class PackError(ValueError):
    """Operator pack failed before or during freeze."""


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]


def require_turso_keys(mapping: dict[str, str]) -> None:
    missing = [
        key
        for key in REQUIRED_TURSO_KEYS
        if not str(mapping.get(key, "") or "").strip()
    ]
    if missing:
        raise PackError(
            "Recruiter zip needs non-empty " + " and ".join(missing) + " in --env."
        )


def write_embedded_blob_from_env(env_path: Path, dest: Path) -> Path:
    if not env_path.is_file():
        raise PackError(f"Env file not found: {env_path}")
    text = env_path.read_text(encoding="utf-8")
    mapping = parse_env_text(text)
    require_turso_keys(mapping)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(obfuscate_env_bytes(text.encode("utf-8")))
    return dest


def packed_key_names(mapping: dict[str, str]) -> list[str]:
    return sorted(key for key, value in mapping.items() if str(value or "").strip())


def log_packed_keys(mapping: dict[str, str], stream=None) -> None:
    out = stream if stream is not None else sys.stdout
    names = packed_key_names(mapping)
    print("Packed keys (values not printed): " + ", ".join(names), file=out)
    leaked = [key for key in SECRET_VALUE_KEYS if key in names]
    if leaked:
        print("Secret values were obfuscated; they are not printed.", file=out)


def recruiter_one_pager_source(repo_root: Path) -> Path:
    candidate = repo_root / "docs" / "RECRUITER.md"
    if candidate.is_file():
        return candidate
    bundled = repo_root_from_here() / "docs" / "RECRUITER.md"
    if bundled.is_file():
        return bundled
    raise PackError("docs/RECRUITER.md is missing")


def strip_plaintext_env_from_dist(dist_root: Path) -> list[str]:
    removed: list[str] = []
    for name in FORBIDDEN_ZIP_NAMES:
        path = dist_root / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    return removed


def stage_recruiter_dist(dist_root: Path, *, one_pager: Path) -> None:
    dist_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(one_pager, dist_root / "RECRUITER.md")
    strip_plaintext_env_from_dist(dist_root)


def frozen_entry(dist_root: Path) -> Path | None:
    for name in ("Pathwise.exe", "Pathwise"):
        path = dist_root / name
        if path.is_file():
            return path
    return None


def run_pyinstaller(repo_root: Path) -> int:
    return subprocess.call(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "Pathwise.spec"],
        cwd=repo_root,
    )


def write_zip(source_dir: Path, zip_path: Path) -> Path:
    if zip_path.exists():
        zip_path.unlink()
    archive = shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=source_dir.parent,
        base_dir=source_dir.name,
    )
    return Path(archive)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Pathwise-recruiter.zip with obfuscated secrets from --env. "
            "This is obfuscation, not a vault."
        )
    )
    parser.add_argument(
        "--env",
        dest="env_file",
        default=None,
        help="Operator pathwise.env (required for a recruiter zip)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Write the generated blob only (no PyInstaller, no zip)",
    )
    parser.add_argument(
        "--repo",
        dest="repo_root",
        default=None,
        help="Repository root (default: inferred from this module)",
    )
    parser.add_argument(
        "--zip-name",
        default=DEFAULT_ZIP_NAME,
        help="Zip filename written at the repo root",
    )
    parser.add_argument(
        "--blob-out",
        default=None,
        help="Override generated blob path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.env_file:
        print(MISSING_ENV_MESSAGE, file=sys.stderr)
        return 2
    repo_root = Path(args.repo_root) if args.repo_root else repo_root_from_here()
    env_path = Path(args.env_file)
    if not env_path.is_file():
        print(f"Env file not found: {env_path}", file=sys.stderr)
        return 2
    blob_dest = (
        Path(args.blob_out)
        if args.blob_out
        else repo_root / EMBEDDED_BLOB_REL
    )
    try:
        mapping = parse_env_text(env_path.read_text(encoding="utf-8"))
        require_turso_keys(mapping)
        write_embedded_blob_from_env(env_path, blob_dest)
        log_packed_keys(mapping)
        print(f"Wrote obfuscated blob {blob_dest} (gitignored; do not commit).", file=sys.stdout)
        if args.skip_build:
            return 0
        code = run_pyinstaller(repo_root)
        if code != 0:
            print("PyInstaller failed.", file=sys.stderr)
            return code
        dist_root = repo_root / "dist" / "Pathwise"
        if frozen_entry(dist_root) is None:
            raise PackError(f"Freeze output missing Pathwise.exe under {dist_root}")
        stage_recruiter_dist(
            dist_root,
            one_pager=recruiter_one_pager_source(repo_root),
        )
        zip_path = repo_root / args.zip_name
        write_zip(dist_root, zip_path)
        print(
            f"Wrote {zip_path}. Recruiter: unzip and double-click Pathwise.exe. "
            "Do not commit this zip or pathwise.env.",
            file=sys.stdout,
        )
        return 0
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
