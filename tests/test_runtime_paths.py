"""Env discovery order, frozen vs cwd paths, sidecar write, no override."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathwise.runtime_paths import (
    ENV_BASENAMES,
    RECRUITER_ENV_FILENAME,
    REQUIRED_TURSO_KEYS,
    apply_env_file,
    car_diagnostics_path,
    dashboard_hint_path,
    env_candidate_paths,
    env_setup_folder,
    load_runtime_env,
    package_resource,
    recruiter_setup_message,
    session_log_path,
    turso_ready,
    writable_dir,
    write_pathwise_env,
)
from pathwise.turso_http import load_dotenv


class TestEnvCandidateOrder(unittest.TestCase):
    def test_explicit_path_is_only_candidate(self):
        explicit = Path("/tmp/custom.env")
        paths = env_candidate_paths(explicit=explicit, cwd=Path("/cwd"), frozen=False)
        self.assertEqual(paths, [explicit])

    def test_pathwise_env_before_dot_env_in_each_folder(self):
        self.assertEqual(ENV_BASENAMES, ("pathwise.env", ".env"))
        folder = Path("/app")
        paths = env_candidate_paths(cwd=folder, frozen=False)
        self.assertEqual(paths[0], folder / "pathwise.env")
        self.assertEqual(paths[1], folder / ".env")

    def test_env_file_var_before_frozen_exe_before_cwd(self):
        exe_dir = Path("/exe")
        cwd = Path("/cwd")
        named = Path("/named/pathwise.env")
        paths = env_candidate_paths(
            environ={"PATHWISE_ENV_FILE": str(named)},
            frozen=True,
            executable=exe_dir / "Pathwise.exe",
            cwd=cwd,
        )
        self.assertEqual(paths[0], named)
        self.assertEqual(paths[1], exe_dir / "pathwise.env")
        self.assertEqual(paths[2], exe_dir / ".env")
        self.assertEqual(paths[3], cwd / "pathwise.env")
        self.assertEqual(paths[4], cwd / ".env")

    def test_env_file_var_directory_searches_basenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            paths = env_candidate_paths(
                environ={"PATHWISE_ENV_FILE": str(folder)},
                frozen=False,
                cwd=Path("/cwd"),
            )
            self.assertEqual(paths[0], folder / "pathwise.env")
            self.assertEqual(paths[1], folder / ".env")

    def test_unfrozen_skips_executable_dir(self):
        cwd = Path("/cwd")
        paths = env_candidate_paths(
            frozen=False,
            executable=Path("/exe/Pathwise.exe"),
            cwd=cwd,
        )
        self.assertEqual(paths, [cwd / "pathwise.env", cwd / ".env"])


class TestLoadRuntimeEnv(unittest.TestCase):
    def test_pathwise_env_wins_over_dot_env_in_same_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "pathwise.env").write_text(
                "TURSO_AUTH_TOKEN=from-pathwise\nTURSO_DATABASE_URL=libsql://a\n",
                encoding="utf-8",
            )
            (folder / ".env").write_text(
                "TURSO_AUTH_TOKEN=from-dot\nEXTRA=1\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_runtime_env(cwd=folder, frozen=False)
                self.assertEqual(loaded, folder / "pathwise.env")
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "from-pathwise")
                self.assertEqual(os.environ["TURSO_DATABASE_URL"], "libsql://a")
                self.assertEqual(os.environ["EXTRA"], "1")

    def test_frozen_exe_dir_wins_over_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe_dir = root / "exe"
            cwd = root / "cwd"
            exe_dir.mkdir()
            cwd.mkdir()
            (exe_dir / "pathwise.env").write_text(
                "TURSO_AUTH_TOKEN=from-exe\n",
                encoding="utf-8",
            )
            (cwd / "pathwise.env").write_text(
                "TURSO_AUTH_TOKEN=from-cwd\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                load_runtime_env(
                    frozen=True,
                    executable=exe_dir / "Pathwise.exe",
                    cwd=cwd,
                )
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "from-exe")

    def test_does_not_override_already_set_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pathwise.env"
            path.write_text("TURSO_AUTH_TOKEN=from-file\nALSO=file\n", encoding="utf-8")
            with patch.dict(os.environ, {"TURSO_AUTH_TOKEN": "from-shell"}, clear=True):
                load_runtime_env(explicit=path)
                self.assertEqual(os.environ["TURSO_AUTH_TOKEN"], "from-shell")
                self.assertEqual(os.environ["ALSO"], "file")

    def test_load_dotenv_explicit_missing_is_noop(self):
        missing = Path(tempfile.gettempdir()) / "pathwise-no-such-sidecar.env"
        self.assertIsNone(load_dotenv(missing))

    def test_load_dotenv_none_uses_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "pathwise.env").write_text("DISCOVERED=1\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with patch("pathwise.runtime_paths.is_frozen", return_value=False):
                    with patch("pathwise.runtime_paths.Path.cwd", return_value=folder):
                        loaded = load_dotenv()
                self.assertEqual(os.environ["DISCOVERED"], "1")
                self.assertEqual(loaded, folder / "pathwise.env")


class TestWritableAndResources(unittest.TestCase):
    def test_unfrozen_writable_dir_is_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(writable_dir(frozen=False, cwd=folder), folder)
            self.assertEqual(session_log_path(frozen=False, cwd=folder), folder / "logs.json")
            self.assertEqual(
                car_diagnostics_path(frozen=False, cwd=folder),
                folder / "car_diagnostics.jsonl",
            )
            self.assertEqual(
                dashboard_hint_path(folder / "logs.json"),
                folder / "logs_dashboard.html",
            )

    def test_frozen_writable_dir_is_exe_folder_not_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe_dir = root / "dist"
            cwd = root / "other"
            exe_dir.mkdir()
            cwd.mkdir()
            self.assertEqual(
                writable_dir(frozen=True, executable=exe_dir / "Pathwise.exe", cwd=cwd),
                exe_dir,
            )
            self.assertEqual(
                session_log_path(frozen=True, executable=exe_dir / "Pathwise.exe", cwd=cwd),
                exe_dir / "logs.json",
            )

    def test_package_resource_prefers_meipass_then_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "meipass"
            packaged = meipass / "pathwise"
            packaged.mkdir(parents=True)
            target = packaged / "recruiter_schema.sql"
            target.write_text("-- frozen\n", encoding="utf-8")
            found = package_resource(
                "pathwise",
                "recruiter_schema.sql",
                meipass=meipass,
            )
            self.assertEqual(found, target)

    def test_duplicate_candidates_are_deduped(self):
        cwd = Path("/same")
        paths = env_candidate_paths(
            environ={"PATHWISE_ENV_FILE": str(cwd / "pathwise.env")},
            frozen=False,
            cwd=cwd,
        )
        self.assertEqual(paths.count(cwd / "pathwise.env"), 1)

    def test_dashboard_hint_defaults_and_relative_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("pathwise.runtime_paths.writable_dir", return_value=folder):
                self.assertEqual(
                    dashboard_hint_path(None),
                    folder / "logs_dashboard.html",
                )
        self.assertEqual(
            dashboard_hint_path("logs.json"),
            Path.cwd() / "logs_dashboard.html",
        )

    def test_package_resource_repo_and_missing_fallback(self):
        found = package_resource("docs", "COMPLIANCE.md", meipass=None)
        self.assertTrue(found.is_file())
        missing = package_resource("no_such_pkg", "missing.txt", meipass=None)
        self.assertEqual(missing.name, "missing.txt")


class TestTursoReadyAndSidecarWrite(unittest.TestCase):
    def test_turso_ready_false_without_keys(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(turso_ready())

    def test_turso_ready_true_when_both_set(self):
        with patch.dict(
            os.environ,
            {"TURSO_DATABASE_URL": "libsql://x", "TURSO_AUTH_TOKEN": "tok"},
            clear=True,
        ):
            self.assertTrue(turso_ready())

    def test_write_pathwise_env_lists_keys_and_does_not_return_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = write_pathwise_env(
                folder,
                {
                    "TURSO_DATABASE_URL": "libsql://example.turso.io",
                    "TURSO_AUTH_TOKEN": "secret-token-value",
                },
            )
            self.assertEqual(path, folder / RECRUITER_ENV_FILENAME)
            text = path.read_text(encoding="utf-8")
            self.assertIn("TURSO_DATABASE_URL=libsql://example.turso.io", text)
            self.assertIn("TURSO_AUTH_TOKEN=secret-token-value", text)
            for key in REQUIRED_TURSO_KEYS:
                self.assertIn(key, text)
            self.assertIn("PATHWISE_SMTP_HOST=", text)
            self.assertIn("PATHWISE_SMTP_PASSWORD=", text)
            self.assertNotIn("secret-token-value", str(path))

    def test_setup_message_names_folder_and_filename(self):
        folder = Path("/unzipped/Pathwise")
        message = recruiter_setup_message(folder)
        self.assertIn("pathwise.env", message)
        self.assertIn(str(folder), message)
        self.assertIn("TURSO_DATABASE_URL", message)
        self.assertIn("TURSO_AUTH_TOKEN", message)
        self.assertIn("not _internal", message.lower())
        self.assertIn(RECRUITER_ENV_FILENAME, message)
        self.assertEqual(env_setup_folder(frozen=False, cwd=folder), folder)

    def test_open_path_in_browser_uses_file_uri(self):
        from pathwise.runtime_paths import open_path_in_browser

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs_dashboard.html"
            path.write_text("<html></html>", encoding="utf-8")
            with patch("webbrowser.open") as opened:
                open_path_in_browser(path)
            opened.assert_called_once()
            self.assertTrue(opened.call_args.args[0].startswith("file:"))

    def test_is_frozen_reads_sys(self):
        from pathwise.runtime_paths import is_frozen

        with patch("pathwise.runtime_paths.sys") as fake_sys:
            fake_sys.frozen = True
            self.assertTrue(is_frozen())
            fake_sys.frozen = False
            self.assertFalse(is_frozen())

    def test_package_resource_falls_back_when_meipass_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            meipass = Path(tmp) / "empty"
            meipass.mkdir()
            found = package_resource(
                "pathwise",
                "recruiter_schema.sql",
                meipass=meipass,
            )
            self.assertTrue(found.is_file())

    def test_write_quotes_values_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = write_pathwise_env(
                folder,
                {"PATHWISE_SMTP_FROM": "Pathwise Recruiter <a@b.co>"},
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn('PATHWISE_SMTP_FROM="Pathwise Recruiter <a@b.co>"', text)


if __name__ == "__main__":
    unittest.main()
