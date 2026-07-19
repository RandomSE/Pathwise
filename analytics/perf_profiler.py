"""Round performance profiler: shareable lag diagnosis (JSONL + HTML report).

Enable with environment variable ``PATHWISE_PERF_PROFILE=1`` before launching the game.

Outputs (project root):
- ``perf_profile.jsonl``: sampled per-frame timings + growth counters
- ``perf_report.html`` : charts and regression summary (open in browser)

Share both files when reporting progressive FPS drops.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_JSONL_PATH = "perf_profile.jsonl"
DEFAULT_HTML_PATH = "perf_report.html"
SAMPLE_EVERY_N_FRAMES = 30


def perf_profile_enabled() -> bool:
    return os.environ.get("PATHWISE_PERF_PROFILE", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_ms(value: float) -> float:
    return round(value * 1000.0, 3)


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _linear_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope (y per x unit); 0 when undefined."""
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


@dataclass
class _PendingFrame:
    round_frame: int
    elapsed_s: float
    update_ms: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int | float] = field(default_factory=dict)


class PerfProfiler:
    """Low-overhead sampler; pairs update + draw into one record per frame."""

    def __init__(
        self,
        *,
        jsonl_path: str = DEFAULT_JSONL_PATH,
        html_path: str = DEFAULT_HTML_PATH,
        sample_stride: int = SAMPLE_EVERY_N_FRAMES,
        enabled: bool | None = None,
    ) -> None:
        self.enabled = perf_profile_enabled() if enabled is None else enabled
        self.jsonl_path = jsonl_path
        self.html_path = html_path
        self.sample_stride = max(1, sample_stride)
        self._pending: _PendingFrame | None = None
        self._samples: list[dict[str, Any]] = []
        self._round_index = 0
        self._session_meta: dict[str, Any] = {}
        self._round_meta: dict[str, Any] = {}
        self._local_sections: dict[str, float] = {}

    def begin_session(self, **meta: Any) -> None:
        if not self.enabled:
            return
        self._session_meta = dict(meta)
        self._samples.clear()
        with open(self.jsonl_path, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"event": "session_start", "utc": _now_utc(), **meta},
                    separators=(",", ":"),
                )
                + "\n"
            )

    def begin_round(self, round_index: int, **meta: Any) -> None:
        if not self.enabled:
            return
        self._round_index = round_index
        self._round_meta = dict(meta)
        self._samples.clear()
        self._pending = None
        self._append_event("round_start", round=round_index, **meta)

    def end_round(self, outcome: str, duration_s: float) -> str | None:
        if not self.enabled:
            return None
        summary = self._build_round_summary(outcome, duration_s)
        self._append_event("round_summary", **summary)
        html_path = build_perf_report_html(self.jsonl_path, self.html_path)
        return html_path

    @contextmanager
    def section(self, name: str):
        if not self.enabled:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._local_sections[name] = (
                self._local_sections.get(name, 0.0) + (time.perf_counter() - t0)
            )

    def finish_update(
        self,
        *,
        round_frame: int,
        elapsed_s: float,
        counters: dict[str, int | float],
    ) -> None:
        if not self.enabled:
            return
        update_ms = {k: _round_ms(v) for k, v in self._local_sections.items()}
        self._local_sections.clear()
        update_total = sum(update_ms.values())
        update_ms["update_total"] = round(update_total, 3)
        self._pending = _PendingFrame(
            round_frame=round_frame,
            elapsed_s=elapsed_s,
            update_ms=update_ms,
            counters=dict(counters),
        )

    def finish_draw(self, draw_seconds: float) -> None:
        if not self.enabled or self._pending is None:
            return
        pending = self._pending
        self._pending = None
        draw_ms = _round_ms(draw_seconds)
        update_total = pending.update_ms.get("update_total", 0.0)
        total_ms = round(update_total + draw_ms, 3)
        if pending.round_frame % self.sample_stride != 0:
            return
        sample = {
            "event": "frame_sample",
            "round": self._round_index,
            "frame": pending.round_frame,
            "t": round(pending.elapsed_s, 3),
            "update_ms": pending.update_ms,
            "draw_ms": draw_ms,
            "total_ms": total_ms,
            "counters": pending.counters,
        }
        self._samples.append(sample)
        self._append_event(**sample)

    def _append_event(self, event: str, **payload: Any) -> None:
        row = {"event": event, "utc": _now_utc(), **payload}
        with open(self.jsonl_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _build_round_summary(self, outcome: str, duration_s: float) -> dict[str, Any]:
        frames = [s["frame"] for s in self._samples]
        totals = [s["total_ms"] for s in self._samples]
        updates = [s["update_ms"].get("update_total", 0.0) for s in self._samples]
        draws = [s.get("draw_ms", 0.0) for s in self._samples]

        def _split_avg(values: list[float], frac: float = 0.1) -> tuple[float, float]:
            if not values:
                return 0.0, 0.0
            n = max(1, int(len(values) * frac))
            first = _mean(values[:n])
            last = _mean(values[-n:])
            return first, last

        total_first, total_last = _split_avg(totals)
        update_first, update_last = _split_avg(updates)
        draw_first, draw_last = _split_avg(draws)

        section_keys: set[str] = set()
        for sample in self._samples:
            section_keys.update(sample["update_ms"].keys())
        section_keys.discard("update_total")

        section_regression: list[dict[str, Any]] = []
        for key in sorted(section_keys):
            vals = [s["update_ms"].get(key, 0.0) for s in self._samples]
            first, last = _split_avg(vals)
            delta = last - first
            section_regression.append(
                {
                    "section": key,
                    "first_ms": round(first, 3),
                    "last_ms": round(last, 3),
                    "delta_ms": round(delta, 3),
                    "pct_change": round((delta / first * 100.0) if first > 0.01 else 0.0, 1),
                }
            )
        section_regression.sort(key=lambda row: row["delta_ms"], reverse=True)

        counter_keys: set[str] = set()
        for sample in self._samples:
            counter_keys.update(sample.get("counters", {}).keys())

        counter_growth: list[dict[str, Any]] = []
        for key in sorted(counter_keys):
            series = [float(s["counters"].get(key, 0)) for s in self._samples]
            if not series:
                continue
            first, last = series[0], series[-1]
            counter_growth.append(
                {
                    "counter": key,
                    "start": first,
                    "end": last,
                    "delta": round(last - first, 3),
                    "slope_per_frame": round(_linear_slope(frames, series), 5),
                }
            )
        counter_growth.sort(key=lambda row: abs(row["delta"]), reverse=True)

        likely_causes: list[str] = []
        if total_last > total_first * 1.25 and total_first > 1.0:
            likely_causes.append(
                f"Frame time rose ~{total_first:.1f}ms → ~{total_last:.1f}ms "
                f"(+{total_last - total_first:.1f}ms)."
            )
        for row in counter_growth[:4]:
            if row["delta"] > 0:
                likely_causes.append(
                    f"{row['counter']} grew {row['start']} → {row['end']} "
                    f"(+{row['delta']:.0f})."
                )
        for row in section_regression[:3]:
            if row["delta_ms"] > 0.5:
                likely_causes.append(
                    f"Section '{row['section']}' slowed "
                    f"{row['first_ms']:.2f}ms → {row['last_ms']:.2f}ms."
                )
        if not likely_causes:
            likely_causes.append("No strong in-round regression detected in sampled frames.")

        return {
            "round": self._round_index,
            "outcome": outcome,
            "duration_s": round(duration_s, 2),
            "samples": len(self._samples),
            "sample_stride": self.sample_stride,
            **self._round_meta,
            "timing": {
                "total_ms_first10pct": round(total_first, 3),
                "total_ms_last10pct": round(total_last, 3),
                "total_ms_delta": round(total_last - total_first, 3),
                "update_ms_first10pct": round(update_first, 3),
                "update_ms_last10pct": round(update_last, 3),
                "draw_ms_first10pct": round(draw_first, 3),
                "draw_ms_last10pct": round(draw_last, 3),
                "total_slope_ms_per_frame": round(_linear_slope(frames, totals), 5),
            },
            "section_regression": section_regression[:12],
            "counter_growth": counter_growth[:16],
            "likely_causes": likely_causes,
        }


def build_perf_report_html(
    jsonl_path: str = DEFAULT_JSONL_PATH,
    html_path: str = DEFAULT_HTML_PATH,
) -> str:
    """Build a self-contained HTML report from the JSONL log."""
    path = Path(jsonl_path)
    if not path.is_file():
        return html_path

    session_start: dict[str, Any] | None = None
    round_summary: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = []

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            event = row.get("event")
            if event == "session_start":
                session_start = row
            elif event == "frame_sample":
                samples.append(row)
            elif event == "round_summary":
                round_summary = row

    payload = {
        "session": session_start or {},
        "summary": round_summary or {},
        "samples": samples,
    }
    data_json = json.dumps(payload)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Pathwise perf report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f4f7fb; color: #1a1a1a; }}
    h1, h2 {{ margin-bottom: 0.35em; }}
    .sub {{ color: #555; margin-top: 0; }}
    .card {{ background: #fff; border-radius: 10px; padding: 16px 18px; margin: 16px 0; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    ul {{ margin: 0.4em 0; padding-left: 1.2em; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e0e0e0; text-align: left; padding: 6px 8px; }}
    canvas {{ width: 100%; max-width: 960px; height: 220px; background: #fafafa; border: 1px solid #ddd; border-radius: 6px; }}
    .tag {{ display: inline-block; background: #e8f0fe; color: #174ea6; padding: 2px 8px; border-radius: 999px; font-size: 12px; margin-right: 6px; }}
  </style>
</head>
<body>
  <h1>Pathwise performance report</h1>
  <p class="sub">Generated from <code>{jsonl_path}</code>: share this HTML + JSONL for lag diagnosis.</p>
  <div class="card" id="summary"></div>
  <div class="card"><h2>Frame time (ms)</h2><canvas id="chart-total" width="960" height="220"></canvas></div>
  <div class="card"><h2>Update vs draw (ms)</h2><canvas id="chart-split" width="960" height="220"></canvas></div>
  <div class="card"><h2>Growth counters</h2><canvas id="chart-counters" width="960" height="220"></canvas></div>
  <div class="card" id="sections"></div>
  <div class="card" id="counters"></div>
  <script>
    const DATA = {data_json};
    function esc(s) {{ return String(s).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
    function drawSeries(canvas, seriesList, labels) {{
      const ctx = canvas.getContext('2d');
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);
      if (!seriesList.length || !seriesList[0].values.length) {{
        ctx.fillStyle = '#888'; ctx.fillText('No samples', 12, 24); return;
      }}
      const pad = 28;
      let minX = Infinity, maxX = -Infinity, minY = 0, maxY = 0;
      for (const s of seriesList) {{
        for (let i = 0; i < s.values.length; i++) {{
          minX = Math.min(minX, s.xs[i]); maxX = Math.max(maxX, s.xs[i]);
          maxY = Math.max(maxY, s.values[i]);
        }}
      }}
      maxY = Math.max(maxY, 1);
      const plotW = W - pad * 2, plotH = H - pad * 2;
      const colors = ['#2563eb','#dc2626','#16a34a','#ca8a04','#7c3aed','#0891b2'];
      seriesList.forEach((s, idx) => {{
        ctx.strokeStyle = colors[idx % colors.length];
        ctx.lineWidth = 2;
        ctx.beginPath();
        s.values.forEach((v, i) => {{
          const x = pad + ((s.xs[i] - minX) / Math.max(1, maxX - minX)) * plotW;
          const y = H - pad - (v / maxY) * plotH;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }});
        ctx.stroke();
      }});
      ctx.fillStyle = '#333'; ctx.font = '12px system-ui';
      labels.forEach((lab, idx) => {{
        ctx.fillStyle = colors[idx % colors.length];
        ctx.fillRect(pad + idx * 120, 8, 12, 12);
        ctx.fillStyle = '#333';
        ctx.fillText(lab, pad + 18 + idx * 120, 18);
      }});
    }}
    const samples = DATA.samples || [];
    const xs = samples.map(s => s.frame);
    const summary = DATA.summary || {{}};
    const causes = (summary.likely_causes || []).map(c => '<li>' + esc(c) + '</li>').join('');
    const timing = summary.timing || {{}};
    document.getElementById('summary').innerHTML =
      '<h2>Round ' + esc(summary.round || '?') + ': ' + esc(summary.outcome || '') + '</h2>' +
      '<p><span class="tag">' + esc(summary.duration_s || 0) + 's</span>' +
      '<span class="tag">' + esc(summary.samples || 0) + ' samples</span></p>' +
      '<p>Total frame: <strong>' + esc(timing.total_ms_first10pct) + 'ms</strong> (early) → ' +
      '<strong>' + esc(timing.total_ms_last10pct) + 'ms</strong> (late), slope ' +
      esc(timing.total_slope_ms_per_frame) + ' ms/frame</p>' +
      '<ul>' + causes + '</ul>';

    drawSeries(document.getElementById('chart-total'), [{{
      xs, values: samples.map(s => s.total_ms), name: 'total'
    }}], ['total ms']);

    drawSeries(document.getElementById('chart-split'), [
      {{ xs, values: samples.map(s => (s.update_ms && s.update_ms.update_total) || 0) }},
      {{ xs, values: samples.map(s => s.draw_ms || 0) }},
    ], ['update', 'draw']);

    const counterKeys = new Set();
    samples.forEach(s => Object.keys(s.counters || {{}}).forEach(k => counterKeys.add(k)));
    const pick = Array.from(counterKeys).slice(0, 4);
    drawSeries(document.getElementById('chart-counters'),
      pick.map(k => ({{ xs, values: samples.map(s => (s.counters && s.counters[k]) || 0) }})),
      pick);

    const secRows = (summary.section_regression || []).map(r =>
      '<tr><td>' + esc(r.section) + '</td><td>' + esc(r.first_ms) + '</td><td>' + esc(r.last_ms) +
      '</td><td>' + esc(r.delta_ms) + '</td><td>' + esc(r.pct_change) + '%</td></tr>'
    ).join('');
    document.getElementById('sections').innerHTML =
      '<h2>Slowest-growing update sections</h2><table><thead><tr><th>Section</th><th>Early ms</th><th>Late ms</th><th>Δ ms</th><th>%</th></tr></thead><tbody>' +
      secRows + '</tbody></table>';

    const ctrRows = (summary.counter_growth || []).map(r =>
      '<tr><td>' + esc(r.counter) + '</td><td>' + esc(r.start) + '</td><td>' + esc(r.end) +
      '</td><td>' + esc(r.delta) + '</td><td>' + esc(r.slope_per_frame) + '</td></tr>'
    ).join('');
    document.getElementById('counters').innerHTML =
      '<h2>Counter growth (memory / workload)</h2><table><thead><tr><th>Counter</th><th>Start</th><th>End</th><th>Δ</th><th>Slope/frame</th></tr></thead><tbody>' +
      ctrRows + '</tbody></table>';
  </script>
</body>
</html>
"""
    out = Path(html_path)
    out.write_text(html, encoding="utf-8")
    return str(out)
