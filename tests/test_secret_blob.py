"""Stdlib obfuscation round-trip: recover keys, never leave UTF-8 tokens in the blob."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.secret_blob import obfuscate_env_bytes, recover_env_bytes
from pathwise.runtime_paths import load_runtime_env, parse_env_text, turso_ready

# Obvious fake; never a JWT. Tests assert this UTF-8 string is absent from the blob.
FAKE_TOKEN = "ci-not-a-real-token"
FAKE_URL = "libsql://ci-placeholder.example.invalid"
FAKE_ENV = (
    f"TURSO_DATABASE_URL={FAKE_URL}\n"
    f"TURSO_AUTH_TOKEN={FAKE_TOKEN}\n"
    "PATHWISE_SMTP_PASSWORD=ci-not-a-real-smtp\n"
)


class TestObfuscateRecover(unittest.TestCase):
    def test_round_trip_recovers_keys(self):
        blob = obfuscate_env_bytes(FAKE_ENV.encode("utf-8"))
        recovered = recover_env_bytes(blob).decode("utf-8")
        mapping = parse_env_text(recovered)
        self.assertEqual(mapping["TURSO_DATABASE_URL"], FAKE_URL)
        self.assertEqual(mapping["TURSO_AUTH_TOKEN"], FAKE_TOKEN)
        self.assertEqual(mapping["PATHWISE_SMTP_PASSWORD"], "ci-not-a-real-smtp")

    def test_blob_is_not_plaintext_utf8(self):
        blob = obfuscate_env_bytes(FAKE_ENV.encode("utf-8"))
        self.assertNotIn(FAKE_TOKEN.encode("utf-8"), blob)
        self.assertNotIn(b"ci-not-a-real-smtp", blob)
        self.assertNotIn(FAKE_URL.encode("utf-8"), blob)
        self.assertFalse(blob.decode("utf-8", errors="replace").count(FAKE_TOKEN))

    def test_xor_rejects_empty_key(self):
        from pathwise.secret_blob import _xor_bytes

        with self.assertRaises(ValueError):
            _xor_bytes(b"abc", b"")

    def test_recover_rejects_wrong_key_len_and_empty_payload(self):
        with self.assertRaises(ValueError):
            recover_env_bytes(b"PW01" + bytes([1]) + b"x" * 32)
        with self.assertRaises(ValueError):
            recover_env_bytes(b"PW01" + bytes([32]) + b"k" * 32)

    def test_obfuscate_rejects_wrong_key_size(self):
        with self.assertRaises(ValueError):
            obfuscate_env_bytes(b"x=1\n", key=b"short")

    def test_corrupt_payload_raises(self):
        blob = obfuscate_env_bytes(FAKE_ENV.encode("utf-8"))
        corrupt = blob[:6] + bytes(b ^ 0xFF for b in blob[6:])
        with self.assertRaises(ValueError):
            recover_env_bytes(corrupt)

    def test_load_embedded_mapping_swallows_bad_blob(self):
        from pathwise.runtime_paths import load_embedded_mapping, resolve_embedded_blob_path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "embedded_env.bin"
            path.write_bytes(b"nope")
            self.assertEqual(load_embedded_mapping(path), {})
            self.assertIsNone(resolve_embedded_blob_path(blob_path=path.parent / "missing.bin"))
            self.assertEqual(resolve_embedded_blob_path(blob_path=path), path)


class TestFrozenLoaderAppliesEmbeddedKeys(unittest.TestCase):
    def test_frozen_load_applies_blob_with_setdefault(self):
        blob = obfuscate_env_bytes(FAKE_ENV.encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "mei"
            meipass.mkdir()
            (meipass / "embedded_env.bin").write_bytes(blob)
            exe_dir = Path(tmp) / "exe"
            exe_dir.mkdir()
            with patch.dict(os.environ, {"PATHWISE_KEEP": "from-process"}, clear=True):
                loaded = load_runtime_env(
                    frozen=True,
                    executable=exe_dir / "Pathwise.exe",
                    cwd=exe_dir,
                    meipass=meipass,
                )
                self.assertIsNone(loaded)
                self.assertEqual(os.environ["TURSO_DATABASE_URL"], FAKE_URL)
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], FAKE_TOKEN)
                self.assertEqual(os.environ["PATHWISE_KEEP"], "from-process")
                self.assertTrue(turso_ready())

    def test_sidecar_overrides_blob_not_process_env(self):
        blob = obfuscate_env_bytes(FAKE_ENV.encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "mei"
            meipass.mkdir()
            (meipass / "embedded_env.bin").write_bytes(blob)
            exe_dir = Path(tmp) / "exe"
            exe_dir.mkdir()
            (exe_dir / "pathwise.env").write_text(
                "TURSO_AUTH_TOKEN=from-sidecar\nSIDECAR_ONLY=1\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"TURSO_DATABASE_URL": "libsql://from-shell.example.invalid"},
                clear=True,
            ):
                load_runtime_env(
                    frozen=True,
                    executable=exe_dir / "Pathwise.exe",
                    cwd=exe_dir,
                    meipass=meipass,
                )
                self.assertEqual(
                    os.environ["TURSO_DATABASE_URL"],
                    "libsql://from-shell.example.invalid",
                )
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "from-sidecar")
                self.assertEqual(os.environ["SIDECAR_ONLY"], "1")

    def test_unfrozen_without_blob_path_does_not_scan_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch.dict(os.environ, {}, clear=True):
                load_runtime_env(cwd=folder, frozen=False)
                self.assertFalse(turso_ready())
                self.assertNotIn("TURSO_AUTH_TOKEN", os.environ)


if __name__ == "__main__":
    unittest.main()
