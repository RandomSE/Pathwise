"""Packaging spec, Windows zip workflow, and example env contracts."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "Pathwise.spec"
WORKFLOW = ROOT / ".github" / "workflows" / "recruiter-windows.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
EXAMPLE_ENV = ROOT / ".env.example"
EXAMPLE_PATHWISE = ROOT / "pathwise.env.example"
RECRUITER_DOC = ROOT / "docs" / "RECRUITER.md"
BUILD_SCRIPT = ROOT / "scripts" / "build_windows.ps1"
README = ROOT / "README.MD"

REQUIRED_KEYS = (
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

_SECRET_ASSIGN = re.compile(
    r"^(TURSO_AUTH_TOKEN|PATHWISE_SMTP_PASSWORD)[ \t]*=[ \t]*\S+",
    re.MULTILINE,
)


class TestExampleEnvFiles(unittest.TestCase):
    def test_both_example_files_exist_with_empty_secrets(self):
        for path in (EXAMPLE_ENV, EXAMPLE_PATHWISE):
            self.assertTrue(path.is_file(), f"missing {path.name}")
            text = path.read_text(encoding="utf-8")
            for key in REQUIRED_KEYS:
                self.assertIn(key, text)
            self.assertIsNone(
                _SECRET_ASSIGN.search(text),
                f"{path.name} must not assign a real token or SMTP password",
            )
            self.assertNotRegex(text, r"eyJ[A-Za-z0-9_-]{10,}")

    def test_pathwise_example_is_operator_local_input(self):
        text = EXAMPLE_PATHWISE.read_text(encoding="utf-8")
        self.assertIn("pathwise.env", text)
        self.assertIn("python -m pathwise.pack", text)


class TestPyinstallerSpec(unittest.TestCase):
    def test_onedir_entry_and_datas(self):
        self.assertTrue(SPEC.is_file())
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("COLLECT", text)
        self.assertIn("exclude_binaries=True", text)
        self.assertIn("main.py", text)
        self.assertIn("name=\"Pathwise\"", text)
        self.assertIn("arcade", text)
        self.assertIn("pathwise", text)
        self.assertIn("analytics", text)
        self.assertIn("map_generation", text)
        self.assertIn("argon2", text)
        self.assertIn("recruiter_schema.sql", text)
        self.assertIn("embedded_env.bin", text)
        self.assertNotIn('("pathwise.env.example"', text)
        self.assertNotIn('(".env.example"', text)
        self.assertNotIn("TURSO_AUTH_TOKEN=", text)
        self.assertNotIn("PATHWISE_SMTP_PASSWORD=", text)
        self.assertIn("filter_pyinstaller_datas", text)
        self.assertIn("a.datas", text)


class TestArcadeVersionClashFilter(unittest.TestCase):
    def test_drops_dest_dir_keeps_version_file_under_arcade(self):
        from pathwise.packaging import filter_pyinstaller_datas

        kept = filter_pyinstaller_datas(
            [
                (r"C:\Python\Lib\site-packages\arcade\VERSION", "arcade"),
                (r"C:\Python\Lib\site-packages\arcade\VERSION", "./arcade/VERSION"),
                (r"C:\Python\Lib\site-packages\arcade\VERSION", "arcade/VERSION"),
                (
                    r"C:\Python\Lib\site-packages\arcade\resources\system",
                    "./arcade/resources/system",
                ),
            ]
        )
        dests = [str(item[1]).replace("\\", "/") for item in kept]
        self.assertIn("arcade", dests)
        self.assertIn("./arcade/resources/system", dests)
        self.assertNotIn("./arcade/VERSION", dests)
        self.assertNotIn("arcade/VERSION", dests)
        self.assertFalse(any(d.replace("\\", "/").rstrip("/").lower().endswith("arcade/version") for d in dests))

    def test_analysis_toc_keeps_version_file_drops_nested_dir(self):
        from pathwise.packaging import filter_pyinstaller_datas

        kept = filter_pyinstaller_datas(
            [
                ("arcade/VERSION", r"C:\site\arcade\VERSION", "DATA"),
                ("arcade/VERSION/VERSION", r"C:\site\arcade\VERSION", "DATA"),
                ("arcade/resources/system/icon.png", r"C:\site\arcade\resources\system\icon.png", "DATA"),
                ("pyglet/info.py", r"C:\site\pyglet\info.py", "DATA"),
            ]
        )
        names = [item[0].replace("\\", "/") for item in kept]
        self.assertIn("arcade/VERSION", names)
        self.assertNotIn("arcade/VERSION/VERSION", names)
        self.assertIn("arcade/resources/system/icon.png", names)


class TestRecruiterWindowsWorkflow(unittest.TestCase):
    def test_windows_job_uploads_zip_and_keeps_pytest_ci(self):
        self.assertTrue(WORKFLOW.is_file())
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("windows-latest", text)
        self.assertIn("pathwise.pack", text)
        self.assertIn("recruiter_pack.env", text)
        self.assertIn("Pathwise-recruiter.zip", text)
        self.assertIn("upload-artifact", text)
        self.assertIn("ci-smoke", text.lower())
        self.assertNotIn("pathwise.env.example", text)
        self.assertTrue(CI.is_file())
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("windows-latest", ci)
        self.assertIn("python -m pytest tests/", ci)
        self.assertNotIn("Pathwise-recruiter.zip", ci)

    def test_local_windows_build_script_requires_env_file(self):
        self.assertTrue(BUILD_SCRIPT.is_file())
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("EnvFile", text)
        self.assertIn("pathwise.pack", text)
        self.assertIn("--env", text)
        self.assertNotIn("pathwise.env.example", text)


class TestRecruiterDocs(unittest.TestCase):
    def test_recruiter_one_pager_is_unzip_and_run_only(self):
        self.assertTrue(RECRUITER_DOC.is_file())
        doc = RECRUITER_DOC.read_text(encoding="utf-8")
        for needle in (
            "Pathwise.exe",
            "Generate seed",
            "Unzip",
            "Double-click",
        ):
            self.assertIn(needle, doc)
        self.assertNotIn("Put `pathwise.env`", doc)
        self.assertNotIn("pathwise.env.example", doc)
        self.assertNotIn("pip", doc.lower())
        readme = README.read_text(encoding="utf-8")
        self.assertLess(readme.lower().find("pathwise-recruiter.zip"), 400)
        self.assertIn("python -m pathwise.pack", readme)
        self.assertIn("--env", readme)
        self.assertIn("Pathwise.exe", readme)
        self.assertIn("venv", readme.lower())
        operator = ROOT / "docs" / "OPERATOR_PACK.md"
        self.assertTrue(operator.is_file())
        op = operator.read_text(encoding="utf-8")
        self.assertIn("python -m pathwise.pack --env", op)
        self.assertIn("obfuscat", op.lower())
        self.assertIn("PyInstaller", op)
        self.assertIn("never commit", op.lower())
        self.assertNotRegex(op, r"eyJ[A-Za-z0-9_-]{10,}")


class TestGeneratedBlobGitignored(unittest.TestCase):
    def test_gitignore_covers_generated_blob_and_operator_env(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("pathwise/_generated/", gitignore)
        self.assertIn("pathwise.env", gitignore)


if __name__ == "__main__":
    unittest.main()
