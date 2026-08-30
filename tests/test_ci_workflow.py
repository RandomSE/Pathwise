"""Lock the GitHub Actions regression workflow contract."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class TestCiWorkflow(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), "CI workflow file is missing")
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_triggers_on_pull_request(self):
        self.assertIn("pull_request:", self.text)

    def test_includes_ubuntu_and_windows_runners(self):
        self.assertIn("ubuntu-latest", self.text)
        self.assertIn("windows-latest", self.text)

    def test_windows_python_matches_local_3_14(self):
        self.assertIn('python-version: "3.14"', self.text)

    def test_ubuntu_keeps_3_12_coverage_gate(self):
        self.assertIn('python-version: "3.12"', self.text)
        self.assertIn("--cov-config=.coveragerc", self.text)
        self.assertIn("xvfb-run", self.text)

    def test_matrix_does_not_fail_fast(self):
        self.assertIn("fail-fast: false", self.text)
