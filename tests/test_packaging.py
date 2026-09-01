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

    def test_pathwise_example_tells_recruiter_the_visible_filename(self):
        text = EXAMPLE_PATHWISE.read_text(encoding="utf-8")
        self.assertIn("pathwise.env", text)


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
        self.assertIn("pathwise.env.example", text)
        self.assertNotIn("TURSO_AUTH_TOKEN=", text)
        self.assertNotIn("PATHWISE_SMTP_PASSWORD=", text)


class TestRecruiterWindowsWorkflow(unittest.TestCase):
    def test_windows_job_uploads_zip_and_keeps_pytest_ci(self):
        self.assertTrue(WORKFLOW.is_file())
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("windows-latest", text)
        self.assertIn("pyinstaller", text.lower())
        self.assertIn("Pathwise.spec", text)
        self.assertIn("Pathwise-recruiter.zip", text)
        self.assertIn("upload-artifact", text)
        self.assertIn("pathwise.env.example", text)
        self.assertTrue(CI.is_file())
        ci = CI.read_text(encoding="utf-8")
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("windows-latest", ci)
        self.assertIn("python -m pytest tests/", ci)
        self.assertNotIn("Pathwise-recruiter.zip", ci)

    def test_local_windows_build_script_exists(self):
        self.assertTrue(BUILD_SCRIPT.is_file())
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Pathwise.spec", text)
        self.assertIn("pathwise.env.example", text)


class TestRecruiterDocs(unittest.TestCase):
    def test_recruiter_one_pager_and_readme_zip_path(self):
        self.assertTrue(RECRUITER_DOC.is_file())
        doc = RECRUITER_DOC.read_text(encoding="utf-8")
        for needle in (
            "pathwise.env",
            "Pathwise.exe",
            "Generate seed",
            "_internal",
            "TURSO_AUTH_TOKEN",
            "full",
        ):
            self.assertIn(needle, doc)
        readme = README.read_text(encoding="utf-8")
        self.assertLess(readme.lower().find("pathwise-recruiter.zip"), 400)
        self.assertIn("pathwise.env", readme)
        self.assertIn("Pathwise.exe", readme)
        self.assertIn("venv", readme.lower())


if __name__ == "__main__":
    unittest.main()
