"""Operator pack CLI: require --env, write obfuscated blob, never ship plaintext env."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.pack import (
    FORBIDDEN_ZIP_NAMES,
    PackError,
    main as pack_main,
    require_turso_keys,
    stage_recruiter_dist,
    write_embedded_blob_from_env,
)
from pathwise.runtime_paths import parse_env_text
from pathwise.secret_blob import recover_env_bytes

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ENV = ROOT / "tests" / "fixtures" / "recruiter_pack.env"
FAKE_TOKEN = "ci-not-a-real-token"


class TestFixtureEnvIsSynthetic(unittest.TestCase):
    def test_ci_fixture_is_obviously_fake(self):
        self.assertTrue(FIXTURE_ENV.is_file())
        text = FIXTURE_ENV.read_text(encoding="utf-8")
        self.assertIn("TURSO_DATABASE_URL", text)
        self.assertIn("TURSO_AUTH_TOKEN", text)
        self.assertIn(FAKE_TOKEN, text)
        self.assertIn("example.invalid", text)
        self.assertNotIn("turso.io", text)
        self.assertNotRegex(text, r"eyJ[A-Za-z0-9_-]{10,}")


class TestPackRequiresEnv(unittest.TestCase):
    def test_refuses_recruiter_zip_without_env_flag(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = pack_main([])
        self.assertEqual(code, 2)
        err = stderr.getvalue()
        self.assertIn("--env", err)
        self.assertIn("recruiter", err.lower())

    def test_refuses_skip_build_without_env_flag(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = pack_main(["--skip-build"])
        self.assertEqual(code, 2)
        self.assertIn("--env", stderr.getvalue())

    def test_refuses_missing_env_file(self):
        stderr = io.StringIO()
        missing = Path(tempfile.gettempdir()) / "pathwise-no-such-operator.env"
        with patch("sys.stderr", stderr):
            code = pack_main(["--env", str(missing), "--skip-build"])
        self.assertEqual(code, 2)
        self.assertIn("not found", stderr.getvalue().lower())

    def test_refuses_env_without_turso_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "pathwise.env"
            env_path.write_text("PATHWISE_SEED=1\n", encoding="utf-8")
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                code = pack_main(["--env", str(env_path), "--skip-build"])
            self.assertEqual(code, 2)
            err = stderr.getvalue()
            self.assertIn("TURSO_DATABASE_URL", err)
            self.assertIn("TURSO_AUTH_TOKEN", err)
            self.assertNotIn("ci-not-a-real-token", err)


class TestPackWritesObfuscatedBlob(unittest.TestCase):
    def test_skip_build_writes_blob_and_does_not_print_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_path = repo / "pathwise.env"
            env_path.write_text(FIXTURE_ENV.read_text(encoding="utf-8"), encoding="utf-8")
            dest = repo / "pathwise" / "_generated" / "embedded_env.bin"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                code = pack_main(
                    [
                        "--env",
                        str(env_path),
                        "--skip-build",
                        "--repo",
                        str(repo),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(dest.is_file())
            blob = dest.read_bytes()
            self.assertNotIn(FAKE_TOKEN.encode("utf-8"), blob)
            recovered = recover_env_bytes(blob).decode("utf-8")
            mapping = parse_env_text(recovered)
            self.assertEqual(mapping["TURSO_AUTH_TOKEN"], FAKE_TOKEN)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(FAKE_TOKEN, combined)
            self.assertNotIn("ci-not-a-real-smtp", combined)
            self.assertIn("TURSO_AUTH_TOKEN", combined)
            self.assertTrue(dest.is_file())

    def test_write_helper_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PackError):
                write_embedded_blob_from_env(
                    Path(tmp) / "missing.env",
                    Path(tmp) / "embedded_env.bin",
                )

    def test_log_packed_keys_does_not_print_values(self):
        from pathwise.pack import log_packed_keys

        buf = io.StringIO()
        log_packed_keys({"TURSO_AUTH_TOKEN": FAKE_TOKEN, "PATHWISE_SEED": "1"}, stream=buf)
        text = buf.getvalue()
        self.assertIn("TURSO_AUTH_TOKEN", text)
        self.assertNotIn(FAKE_TOKEN, text)

    def test_write_zip_replaces_existing(self):
        from pathwise.pack import write_zip

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Pathwise"
            folder.mkdir()
            (folder / "Pathwise.exe").write_bytes(b"mz")
            zip_path = Path(tmp) / "Pathwise-recruiter.zip"
            zip_path.write_bytes(b"old")
            wrote = write_zip(folder, zip_path)
            self.assertTrue(wrote.is_file())
            self.assertGreater(wrote.stat().st_size, 4)

    def test_one_pager_prefers_repo_docs(self):
        from pathwise.pack import recruiter_one_pager_source

        self.assertTrue(recruiter_one_pager_source(ROOT).is_file())

    def test_default_meipass_reads_sys(self):
        from pathwise.runtime_paths import default_meipass, load_embedded_mapping

        with patch("pathwise.runtime_paths.sys") as fake_sys:
            fake_sys._MEIPASS = None
            self.assertIsNone(default_meipass())
            fake_sys._MEIPASS = "/tmp/mei"
            self.assertEqual(default_meipass(), Path("/tmp/mei"))
        self.assertEqual(load_embedded_mapping(Path("/no/such/embedded_env.bin")), {})

    def test_write_helper_rejects_empty_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "pathwise.env"
            env_path.write_text(
                "TURSO_DATABASE_URL=libsql://x.example.invalid\nTURSO_AUTH_TOKEN=\n",
                encoding="utf-8",
            )
            with self.assertRaises(PackError):
                write_embedded_blob_from_env(env_path, Path(tmp) / "embedded_env.bin")

    def test_require_turso_keys_names_missing(self):
        with self.assertRaises(PackError) as ctx:
            require_turso_keys({"TURSO_DATABASE_URL": "libsql://x.example.invalid"})
        self.assertIn("TURSO_AUTH_TOKEN", str(ctx.exception))
        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))


class TestStageRecruiterDist(unittest.TestCase):
    def test_strips_plaintext_env_and_copies_unzip_run_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "Pathwise"
            dist.mkdir()
            (dist / "Pathwise.exe").write_bytes(b"mz")
            (dist / "pathwise.env").write_text(
                f"TURSO_AUTH_TOKEN={FAKE_TOKEN}\n",
                encoding="utf-8",
            )
            (dist / "pathwise.env.example").write_text("TURSO_AUTH_TOKEN=\n", encoding="utf-8")
            (dist / ".env").write_text("x=1\n", encoding="utf-8")
            (dist / ".env.example").write_text("x=\n", encoding="utf-8")
            stage_recruiter_dist(dist, one_pager=ROOT / "docs" / "RECRUITER.md")
            for name in FORBIDDEN_ZIP_NAMES:
                self.assertFalse((dist / name).exists(), name)
            page = dist / "RECRUITER.md"
            self.assertTrue(page.is_file())
            text = page.read_text(encoding="utf-8")
            self.assertIn("Double-click", text)
            self.assertNotIn("Put `pathwise.env`", text)
            self.assertNotIn(FAKE_TOKEN, text)


class TestPackZipRefusesWithoutEnvEvenIfDistExists(unittest.TestCase):
    def test_full_pack_without_env_does_not_call_pyinstaller(self):
        with patch("pathwise.pack.run_pyinstaller") as run_pi:
            code = pack_main(["--zip-name", "Pathwise-recruiter.zip"])
        self.assertEqual(code, 2)
        run_pi.assert_not_called()


class TestPackFreezeAndZip(unittest.TestCase):
    def test_run_pyinstaller_invokes_module(self):
        from pathwise.pack import run_pyinstaller

        with patch("subprocess.call", return_value=0) as call:
            code = run_pyinstaller(Path("/repo"))
        self.assertEqual(code, 0)
        args = call.call_args.args[0]
        self.assertEqual(args[1:4], ["-m", "PyInstaller", "--noconfirm"])
        self.assertEqual(args[4], "Pathwise.spec")
        self.assertEqual(call.call_args.kwargs.get("cwd"), Path("/repo"))

    def test_mocked_freeze_zips_without_plaintext_env(self):
        from pathwise.pack import recruiter_one_pager_source

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_path = repo / "pathwise.env"
            env_path.write_text(FIXTURE_ENV.read_text(encoding="utf-8"), encoding="utf-8")
            dist = repo / "dist" / "Pathwise"

            def fake_pi(root):
                dist.mkdir(parents=True)
                (dist / "Pathwise.exe").write_bytes(b"mz")
                (dist / "pathwise.env").write_text(
                    f"TURSO_AUTH_TOKEN={FAKE_TOKEN}\n",
                    encoding="utf-8",
                )
                return 0

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("pathwise.pack.run_pyinstaller", side_effect=fake_pi):
                with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                    code = pack_main(
                        [
                            "--env",
                            str(env_path),
                            "--repo",
                            str(repo),
                        ]
                    )
            self.assertEqual(code, 0)
            zip_path = repo / "Pathwise-recruiter.zip"
            self.assertTrue(zip_path.is_file())
            self.assertFalse((dist / "pathwise.env").exists())
            self.assertTrue((dist / "RECRUITER.md").is_file())
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(FAKE_TOKEN, combined)
            self.assertTrue(recruiter_one_pager_source(repo).is_file())

    def test_pyinstaller_failure_is_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_path = repo / "pathwise.env"
            env_path.write_text(FIXTURE_ENV.read_text(encoding="utf-8"), encoding="utf-8")
            with patch("pathwise.pack.run_pyinstaller", return_value=7):
                code = pack_main(["--env", str(env_path), "--repo", str(repo)])
            self.assertEqual(code, 7)

    def test_missing_exe_after_freeze_is_pack_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env_path = repo / "pathwise.env"
            env_path.write_text(FIXTURE_ENV.read_text(encoding="utf-8"), encoding="utf-8")

            def fake_pi(root):
                (repo / "dist" / "Pathwise").mkdir(parents=True)
                return 0

            stderr = io.StringIO()
            with patch("pathwise.pack.run_pyinstaller", side_effect=fake_pi):
                with patch("sys.stderr", stderr):
                    code = pack_main(["--env", str(env_path), "--repo", str(repo)])
            self.assertEqual(code, 2)
            self.assertIn("Pathwise.exe", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
