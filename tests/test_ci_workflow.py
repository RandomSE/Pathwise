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

    def test_windows_job_does_not_force_pyglet_headless(self):
        self.assertNotIn(
            "PYGLET_HEADLESS",
            self.text,
            "PYGLET_HEADLESS loads EGL; Windows hosted runners do not ship EGL",
        )

    def test_windows_job_skips_coverage_gate(self):
        win = self.text.split("if: runner.os == 'Windows'", 1)[1]
        self.assertNotIn(
            "--cov-config=.coveragerc",
            win,
            "Windows hosted runners lack OpenGL 2.0; coverage gate stays on Linux",
        )
        self.assertNotIn("--cov=", win)

    def test_windows_ci_gl2_skip_list_covers_failed_draw_tests(self):
        from tests.conftest import WINDOWS_CI_SKIP_GL2

        required = {
            "test_draw_perf.py::TestDrawPerfRegression::test_headless_draw_warmup_stays_under_relaxed_budget",
            "test_draw_viewport.py::TestGameplayDrawSurface::test_identity_layout_sets_sim_projection",
            "test_draw_viewport.py::TestGameplayDrawSurface::test_scaled_layout_uses_fixed_fbo",
            "test_game_entry.py::TestGameEntry::test_launch_draw_path_with_baked_map_tiles",
            "test_graphics_perf.py::TestGameplaySurface::test_blit_builds_geometry_on_first_frame",
            "test_weather_draw_smoke.py::TestWeatherDrawSmoke::test_draw_weather_overlay_does_not_raise",
        }
        self.assertTrue(required.issubset(WINDOWS_CI_SKIP_GL2))
