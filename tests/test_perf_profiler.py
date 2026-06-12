import json
import os
import tempfile
import unittest

from analytics.perf_profiler import (
    PerfProfiler,
    build_perf_report_html,
    perf_profile_enabled,
)


class TestPerfProfileEnabled(unittest.TestCase):
    def test_disabled_by_default(self):
        env = os.environ.pop("PATHWISE_PERF_PROFILE", None)
        try:
            self.assertFalse(perf_profile_enabled())
        finally:
            if env is not None:
                os.environ["PATHWISE_PERF_PROFILE"] = env

    def test_enabled_with_flag(self):
        os.environ["PATHWISE_PERF_PROFILE"] = "1"
        try:
            self.assertTrue(perf_profile_enabled())
        finally:
            os.environ.pop("PATHWISE_PERF_PROFILE", None)


class TestPerfProfiler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jsonl = os.path.join(self.tmp.name, "perf.jsonl")
        self.html = os.path.join(self.tmp.name, "perf.html")
        self.profiler = PerfProfiler(
            jsonl_path=self.jsonl,
            html_path=self.html,
            sample_stride=1,
            enabled=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_update_draw_sample(self):
        self.profiler.begin_round(1, map_id="test")
        self.profiler.finish_update(
            round_frame=1,
            elapsed_s=0.1,
            counters={"cars_alive": 5, "replay_frames": 2},
        )
        self.profiler.finish_draw(0.002)
        rows = self._read_rows()
        samples = [r for r in rows if r.get("event") == "frame_sample"]
        self.assertEqual(len(samples), 1)
        self.assertIn("update_ms", samples[0])
        self.assertEqual(samples[0]["draw_ms"], 2.0)
        self.assertEqual(samples[0]["counters"]["cars_alive"], 5)

    def test_round_summary_detects_growth(self):
        self.profiler.begin_round(1)
        for i in range(20):
            self.profiler._local_sections = {"frame_recorder": 0.001 + i * 0.0005}
            self.profiler.finish_update(
                round_frame=i,
                elapsed_s=i / 60.0,
                counters={"replay_frames": i * 3, "cars_alive": 10 + i},
            )
            self.profiler.finish_draw(0.004)
        summary_path = self.profiler.end_round("timeout", 30.0)
        self.assertTrue(os.path.isfile(summary_path))
        summary = [r for r in self._read_rows() if r.get("event") == "round_summary"][0]
        self.assertGreater(summary["timing"]["total_ms_last10pct"], 0.0)
        self.assertTrue(summary["likely_causes"])
        self.assertTrue(summary["counter_growth"])
        html = build_perf_report_html(self.jsonl, self.html)
        self.assertTrue(os.path.isfile(html))
        with open(html, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("Pathwise performance report", body)

    def test_disabled_has_no_file(self):
        off = PerfProfiler(jsonl_path=self.jsonl, enabled=False)
        off.begin_round(1)
        off.finish_update(round_frame=1, elapsed_s=0.0, counters={})
        off.finish_draw(0.01)
        self.assertFalse(os.path.isfile(self.jsonl))

    def _read_rows(self) -> list[dict]:
        if not os.path.isfile(self.jsonl):
            return []
        rows = []
        with open(self.jsonl, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows


if __name__ == "__main__":
    unittest.main()
