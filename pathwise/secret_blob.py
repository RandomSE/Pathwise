"""Stdlib-only env obfuscation for recruiter freeze (not a vault).

Pack time: random key, zlib-compress, XOR. Runtime recovers bytes. A determined
person can reverse PyInstaller; this only avoids a plaintext .env in the zip.
"""

from __future__ import annotations

import secrets
import zlib

MAGIC = b"PW01"
KEY_SIZE = 32


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key:
        raise ValueError("obfuscation key must not be empty")
    key_len = len(key)
    return bytes(byte ^ key[index % key_len] for index, byte in enumerate(data))


def obfuscate_env_bytes(plain: bytes, *, key: bytes | None = None) -> bytes:
    secret = key if key is not None else secrets.token_bytes(KEY_SIZE)
    if len(secret) != KEY_SIZE:
        raise ValueError("obfuscation key must be 32 bytes")
    compressed = zlib.compress(plain, level=9)
    payload = _xor_bytes(compressed, secret)
    return MAGIC + bytes([KEY_SIZE]) + secret + payload


def recover_env_bytes(blob: bytes) -> bytes:
    if len(blob) < 5 + KEY_SIZE or not blob.startswith(MAGIC):
        raise ValueError("unrecognized secret blob")
    key_len = blob[4]
    if key_len != KEY_SIZE:
        raise ValueError("unrecognized secret blob")
    key = blob[5 : 5 + key_len]
    payload = blob[5 + key_len :]
    if not payload:
        raise ValueError("unrecognized secret blob")
    try:
        return zlib.decompress(_xor_bytes(payload, key))
    except zlib.error as exc:
        raise ValueError("unrecognized secret blob") from exc
