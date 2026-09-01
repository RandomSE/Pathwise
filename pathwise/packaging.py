"""PyInstaller helpers. Sidecar secrets are never baked into the freeze."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Sequence)


def _norm(value: object) -> str:
    return str(value).replace("\\", "/").rstrip("/").lower()


def _is_arcade_version_dest_dir(dest: object) -> bool:
    """True when collect_all dest is the folder arcade/VERSION (Windows clash)."""
    norm = _norm(dest)
    return norm.endswith("/arcade/version") or norm == "arcade/version"


def _is_nested_arcade_version_toc(dest_name: object) -> bool:
    """True when Analysis TOC dest is a file *inside* arcade/VERSION/."""
    parts = [part for part in _norm(dest_name).split("/") if part]
    try:
        index = parts.index("arcade")
    except ValueError:
        return False
    return index + 2 < len(parts) and parts[index + 1] == "version"


def filter_pyinstaller_datas(entries: Iterable[T]) -> list[T]:
    """Drop dest dirs that clash with the arcade VERSION file on Windows.

    collect_all places the VERSION *file* at dest ``arcade`` (arcade/VERSION).
    Arcade's PyInstaller hook also adds dest ``./arcade/VERSION`` as a
    *directory*. On a case-insensitive filesystem COLLECT then fails:
    file exists, directory needed. Keep the file; drop the directory dest.

    collect_all tuples are ``(src, dest)``. Analysis TOC items are
    ``(dest_name, src, typecode)``.
    """
    kept: list[T] = []
    for entry in entries:
        if len(entry) >= 3:
            if _is_nested_arcade_version_toc(entry[0]):
                continue
            kept.append(entry)
            continue
        dest = entry[1] if len(entry) > 1 else ""
        if _is_arcade_version_dest_dir(dest):
            continue
        kept.append(entry)
    return kept
