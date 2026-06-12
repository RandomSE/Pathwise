"""Generate a recruiter-facing HTML dashboard from a Pathwise session log."""

import argparse
import json
import os

from analytics.archetype_scoring import score_session
from analytics.replay_playback import (
    MAX_PLAYBACK_GAP_S,
    MIN_PLAYBACK_GAP_S,
    REPLAY_STEP_S,
)


def build_dashboard_html(
    session_path,
    output_path=None,
    *,
    default_playback_rate: float = 1.0,
    spectate_anomalies: list | None = None,
    spectate_metrics: dict | None = None,
):
    with open(session_path, encoding="utf-8") as f:
        payload = json.load(f)

    def _is_risk_mark(m):
        return m.get("action") in ("risk_event", "car_honk") or bool(m.get("risk"))

    def _split_marks(sess):
        decision_marks = sess.get("decision_marks", [])
        risk_marks = sess.get("risk_marks", [])
        if not risk_marks and decision_marks:
            risk_marks = [m for m in decision_marks if _is_risk_mark(m)]
            decision_marks = [m for m in decision_marks if not _is_risk_mark(m)]
        return decision_marks, risk_marks

    def _round_view(entry):
        if isinstance(entry, dict) and entry.get("session"):
            sess = entry["session"]
            round_n = entry.get("round", 1)
            outcome = entry.get("outcome", sess.get("outcome"))
            archetypes = entry.get("archetypes")
        else:
            sess = entry
            round_n = sess.get("round_index", 1)
            outcome = sess.get("outcome")
            archetypes = None
        decision_marks, risk_marks = _split_marks(sess)
        if archetypes is None:
            archetypes = score_session(sess)
        return {
            "round": round_n,
            "outcome": outcome,
            "session": sess,
            "archetypes": archetypes,
            "duration": sess.get("duration_s", 1),
            "frames": sess.get("replay_frames", []),
            "decision_marks": decision_marks,
            "risk_marks": risk_marks,
            "map_layout": sess.get("map_layout"),
            "car_archetypes": sess.get("car_archetypes", []),
        }

    round_entries = payload.get("rounds")
    if round_entries:
        rounds_ui = [_round_view(r) for r in round_entries]
    else:
        session = payload.get("session", payload)
        archetypes = payload.get("archetypes") or score_session(session)
        rounds_ui = [
            _round_view(
                {
                    "session": session,
                    "round": session.get("round_index", 1),
                    "outcome": payload.get("outcome", session.get("outcome")),
                    "archetypes": archetypes,
                }
            )
        ]

    last = rounds_ui[-1]
    session = last["session"]
    archetypes = payload.get("archetypes") or last["archetypes"]

    if output_path is None:
        base = os.path.splitext(os.path.basename(session_path))[0]
        output_path = os.path.join(os.path.dirname(session_path) or ".", f"{base}_dashboard.html")

    data_json = json.dumps(
        {
            "rounds": rounds_ui,
            "num_rounds": len(rounds_ui),
            "session": session,
            "archetypes": archetypes,
            "duration": last["duration"],
            "map_layout": last["map_layout"],
            "frames": last["frames"],
            "decision_marks": last["decision_marks"],
            "risk_marks": last["risk_marks"],
            "car_archetypes": last["car_archetypes"],
            "spectate_anomalies": spectate_anomalies or [],
            "spectate_metrics": spectate_metrics or {},
        }
    )
    playback_selected = {0.5: "", 1: "", 2: "", 4: "", 8: ""}
    rate_key = (
        8.0
        if default_playback_rate >= 6
        else 4.0
        if default_playback_rate >= 3
        else 2.0
        if default_playback_rate >= 1.5
        else 1.0
        if default_playback_rate >= 0.75
        else 0.5
    )
    playback_selected[rate_key] = " selected"
    replay_step_s = REPLAY_STEP_S
    replay_min_gap_s = MIN_PLAYBACK_GAP_S
    replay_max_gap_s = MAX_PLAYBACK_GAP_S

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pathwise Recruiter Dashboard</title>
  <style>
    :root {{
      --bg: #0f1419;
      --card: #1a2332;
      --text: #e8eef4;
      --muted: #8b9cb3;
      --accent: #3d8bfd;
      --success: #3dd68c;
      --warn: #f5a524;
      --danger: #f2555a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    header {{
      padding: 1.5rem 2rem;
      border-bottom: 1px solid #2a3548;
      background: linear-gradient(135deg, #1a2332 0%, #121820 100%);
    }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.5rem; }}
    .subtitle {{ color: var(--muted); font-size: 0.95rem; }}
    main {{ padding: 1.5rem 2rem 3rem; max-width: 1200px; margin: 0 auto; }}
    .grid {{ display: grid; gap: 1.25rem; }}
  @media (min-width: 900px) {{
      .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    }}
    .card {{
      background: var(--card);
      border-radius: 12px;
      padding: 1.25rem;
      border: 1px solid #2a3548;
    }}
    .card h2 {{ margin: 0 0 1rem; font-size: 1.1rem; }}
    .stat-row {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; }}
    .stat {{
      flex: 1;
      min-width: 120px;
      background: #121820;
      border-radius: 8px;
      padding: 0.75rem 1rem;
    }}
    .stat .value {{ font-size: 1.4rem; font-weight: 600; }}
    .stat .label {{ color: var(--muted); font-size: 0.8rem; }}
    .archetype-primary {{
      font-size: 1.35rem;
      font-weight: 600;
      color: var(--accent);
    }}
  .bar-row {{ margin-bottom: 0.65rem; }}
    .bar-label {{ display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 0.2rem; }}
    .bar-track {{ height: 8px; background: #121820; border-radius: 4px; overflow: hidden; }}
    .bar-fill {{ height: 100%; background: var(--accent); border-radius: 4px; transition: width 0.3s; }}
    .insights {{ list-style: none; padding: 0; margin: 0; }}
    .insights li {{
      padding: 0.6rem 0;
      border-bottom: 1px solid #2a3548;
      font-size: 0.9rem;
    }}
    .insights li:last-child {{ border-bottom: none; }}
    .card-wide {{ margin-top: 1.25rem; }}
    .replay-viewport {{
      width: 100%;
      background: #121820;
      border-radius: 10px;
      overflow: hidden;
      cursor: grab;
      touch-action: none;
      user-select: none;
    }}
    .replay-viewport.is-dragging {{ cursor: grabbing; }}
    .map-replay-wrap {{
      width: 100%;
      padding: 0.5rem;
    }}
    .replay-svg {{
      width: 100%;
      height: auto;
      min-height: 320px;
      max-height: 520px;
      display: block;
      pointer-events: none;
    }}
    .replay-zoom-bar {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-top: 0.5rem;
      flex-wrap: wrap;
    }}
    .replay-zoom-bar button {{
      background: #121820;
      border: 1px solid #2a3548;
      color: var(--text);
      border-radius: 8px;
      min-width: 36px;
      height: 32px;
      cursor: pointer;
      font-size: 1rem;
    }}
    .replay-zoom-bar button:hover {{ border-color: var(--accent); }}
    #zoom-level {{
      color: var(--muted);
      font-size: 0.85rem;
      min-width: 3.5rem;
    }}
    .replay-zoom-hint {{
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .scrubber {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 1rem;
    }}
    .scrubber button {{
      background: #121820;
      border: 1px solid #2a3548;
      color: var(--text);
      border-radius: 8px;
      width: 40px;
      height: 40px;
      cursor: pointer;
      font-size: 1rem;
    }}
    .scrubber button:hover {{ border-color: var(--accent); }}
    #frame-play {{
      width: 48px;
      font-size: 1.1rem;
    }}
    #frame-play.is-playing {{
      border-color: var(--accent);
      color: var(--accent);
    }}
    .scrub-track {{
      flex: 1;
      position: relative;
      padding-top: 18px;
    }}
    #frame-slider {{
      width: 100%;
      accent-color: var(--accent);
    }}
    #decision-ticks {{
      position: absolute;
      left: 0;
      right: 0;
      top: 0;
      height: 14px;
      pointer-events: none;
    }}
    .decision-tick {{
      position: absolute;
      width: 3px;
      height: 14px;
      background: var(--warn);
      border-radius: 2px;
      transform: translateX(-50%);
      pointer-events: auto;
      cursor: pointer;
    }}
    .decision-tick:hover {{ background: #ffc766; height: 16px; }}
    .decision-log .decision-id {{ color: var(--muted); font-size: 0.7rem; }}
    .scrub-track-risks {{ padding-top: 4px; margin-top: 2px; }}
    .risk-tick {{ background: #e85d5d; }}
    .risk-tick:hover {{ background: #ff7a7a; height: 14px; }}
    .replay-events {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-top: 0.75rem;
    }}
    @media (max-width: 720px) {{
      .replay-events {{ grid-template-columns: 1fr; }}
    }}
    .replay-events h3 {{
      margin: 0 0 0.5rem;
      font-size: 0.95rem;
      color: var(--text);
    }}
    .event-log {{
      max-height: 140px;
      overflow-y: auto;
      font-family: ui-monospace, monospace;
      font-size: 0.72rem;
      background: #121820;
      border-radius: 8px;
      padding: 0.6rem;
    }}
    .event-log div {{ padding: 0.12rem 0; color: var(--muted); }}
    .risk-log div {{ color: #ff9b9b; }}
    .event-jump {{
      width: 100%;
      margin-bottom: 0.5rem;
      background: #121820;
      border: 1px solid #2a3548;
      color: var(--text);
      border-radius: 6px;
      padding: 0.35rem 0.5rem;
      font-size: 0.85rem;
    }}
    .light-timer {{
      font-size: 9px;
      fill: #333;
      font-family: ui-monospace, monospace;
    }}
    .round-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin: 0.75rem 0 0.25rem;
    }}
    .round-tab {{
      padding: 0.45rem 0.9rem;
      border-radius: 8px;
      border: 1px solid #2a3548;
      background: #121820;
      color: var(--text);
      cursor: pointer;
      font-size: 0.85rem;
    }}
    .round-tab.active {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .round-tab.outcome-success {{ border-color: var(--success); }}
    .round-tab.outcome-collision {{ border-color: var(--danger); }}
    .round-tab.outcome-timeout {{ border-color: var(--warn); }}
    .round-tab.active.outcome-success {{ background: var(--success); border-color: var(--success); }}
    .round-tab.active.outcome-collision {{ background: var(--danger); border-color: var(--danger); }}
    .round-tab.active.outcome-timeout {{ background: var(--warn); border-color: var(--warn); color: #1a1208; }}
    .event-log div.event-active {{ opacity: 1; color: var(--text); font-weight: 600; }}
    .event-log div.event-row {{ cursor: pointer; opacity: 0.72; }}
    .event-log div.event-row:hover {{ opacity: 1; }}
    .replay-shortcuts {{
      color: var(--muted);
      font-size: 0.8rem;
      margin-top: 0.25rem;
    }}
    .replay-controls {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 1rem;
      margin: 0.75rem 0 0.25rem;
      font-size: 0.9rem;
    }}
    .frame-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 1rem;
      margin-top: 0.5rem;
      font-size: 0.9rem;
    }}
    #frame-decision-label {{ color: var(--warn); font-weight: 600; }}
    #frame-decision-jump, #playback-rate {{
      background: #121820;
      border: 1px solid #2a3548;
      color: var(--text);
      border-radius: 6px;
      padding: 0.35rem 0.5rem;
    }}
    .decision-log {{
      max-height: 220px;
      overflow-y: auto;
      font-family: ui-monospace, monospace;
      font-size: 0.75rem;
      background: #121820;
      border-radius: 8px;
      padding: 0.75rem;
    }}
    .decision-log div {{ padding: 0.15rem 0; color: var(--muted); }}
    .decision-log strong {{ color: var(--text); }}
  </style>
</head>
<body>
  <header>
    <h1>Pathwise Recruiter Dashboard</h1>
    <p class="subtitle">Behavioral archetypes and a frame-by-frame replay of the candidate run (cars, lights, decisions).</p>
  </header>
  <main>
    <div class="stat-row" id="stats"></div>
    <div class="grid grid-2">
      <section class="card">
        <h2>Role-Tailored Scoring</h2>
        <p class="archetype-primary" id="primary-archetype"></p>
        <p class="subtitle" id="secondary-archetype"></p>
        <div id="archetype-bars"></div>
        <ul class="insights" id="insights"></ul>
      </section>
      <section class="card">
        <h2>Decision Summary</h2>
        <div id="decision-summary"></div>
        <div class="decision-log" id="decision-log"></div>
      </section>
    </div>
    <section class="card card-wide">
      <h2>Run Replay</h2>
      <p class="subtitle">Press Play for real-time replay, scrub the slider, or use arrows. Scroll or +/- to zoom, drag to pan. Select a round, then scrub or play. Orange ticks = decisions; red ticks = risks.</p>
      <div id="round-tabs" class="round-tabs"></div>
      <div id="replay-viewport" class="replay-viewport">
        <div id="map-replay" class="map-replay-wrap"></div>
      </div>
      <div class="replay-zoom-bar">
        <button type="button" id="zoom-out" title="Zoom out">−</button>
        <button type="button" id="zoom-reset" title="Reset zoom">Reset</button>
        <button type="button" id="zoom-in" title="Zoom in">+</button>
        <span id="zoom-level">100%</span>
        <span class="replay-zoom-hint">Scroll to zoom · drag to pan</span>
      </div>
      <div class="scrubber">
        <button type="button" id="frame-play" title="Play replay" aria-label="Play replay">&#9654;</button>
        <button type="button" id="frame-prev" title="Previous frame">&#9664;</button>
        <div class="scrub-track">
          <div id="decision-ticks"></div>
          <input type="range" id="frame-slider" min="0" max="0" value="0" step="1" />
          <div class="scrub-track-risks" id="risk-ticks"></div>
        </div>
        <button type="button" id="frame-next" title="Next frame">&#9654;</button>
      </div>
      <div class="replay-controls">
        <label class="subtitle" for="playback-rate">Playback speed</label>
        <select id="playback-rate" title="Playback speed">
          <option value="0.5"{playback_selected[0.5]}>0.5×</option>
          <option value="1"{playback_selected[1]}>1×</option>
          <option value="2"{playback_selected[2]}>2×</option>
          <option value="4"{playback_selected[4]}>4×</option>
          <option value="8"{playback_selected[8]}>8×</option>
        </select>
        <span class="replay-shortcuts">Space play · ←→ scrub · [ ] speed · D / R jump decisions / risks</span>
      </div>
      <div class="frame-meta">
        <span id="frame-time">0.0s</span>
        <span id="frame-index">Frame 0 / 0</span>
        <span id="frame-decision-label"></span>
      </div>
      <div class="replay-events">
        <div>
          <h3>Decisions</h3>
          <select id="frame-decision-jump" class="event-jump"><option value="">Jump to decision…</option></select>
          <div id="replay-decision-log" class="event-log"></div>
        </div>
        <div>
          <h3>Risks</h3>
          <select id="frame-risk-jump" class="event-jump"><option value="">Jump to risk…</option></select>
          <div id="replay-risk-log" class="event-log risk-log"></div>
        </div>
        <div id="spectate-anomaly-panel" style="display:none">
          <h3>Spectate anomalies</h3>
          <p id="spectate-metrics-line" class="spectate-metrics" style="display:none"></p>
          <select id="spectate-anomaly-jump" class="event-jump"><option value="">Jump to anomaly…</option></select>
          <div id="spectate-anomaly-log" class="event-log"></div>
        </div>
      </div>
    </section>
  </main>
  
<script>
    const DATA = {data_json};
    let currentFrameIndex = 0;
    let isPlaying = false;
    let playRafId = null;
    let playheadT = 0;
    let playAnchorWall = 0;
    let playAnchorSim = 0;
    const DEFAULT_PLAYBACK_RATE = {default_playback_rate};
    let playbackRate = DEFAULT_PLAYBACK_RATE;
    const REPLAY_STEP_S = {replay_step_s};
    const REPLAY_MIN_GAP_S = {replay_min_gap_s};
    const REPLAY_MAX_GAP_S = {replay_max_gap_s};
    let replayZoom = 1;
    let replayPanX = 0;
    let replayPanY = 0;
    let replayBaseBounds = null;
    let replayDrag = null;

    let activeRoundIndex = 0;
    let scrubberInitialized = false;
    let jumpDropdownListenersReady = false;

    function applyRoundToData(idx) {{
      const rounds = DATA.rounds || [];
      if (!rounds.length) return;
      activeRoundIndex = Math.max(0, Math.min(idx, rounds.length - 1));
      const r = rounds[activeRoundIndex];
      DATA.session = r.session;
      DATA.archetypes = r.archetypes;
      DATA.duration = r.duration;
      DATA.frames = r.frames;
      DATA.map_layout = r.map_layout;
      DATA.decision_marks = r.decision_marks;
      DATA.risk_marks = r.risk_marks;
      DATA.car_archetypes = r.car_archetypes;
      replayBaseBounds = null;
      initReplayBounds();
    }}

    function selectRound(idx) {{
      stopPlayback();
      applyRoundToData(idx);
      buildRoundTabs();
      renderRoundPanels();
      refreshFrameScrubber();
    }}

    function buildRoundTabs() {{
      const el = document.getElementById("round-tabs");
      const rounds = DATA.rounds || [];
      if (!el) return;
      if (rounds.length <= 1) {{
        el.style.display = "none";
        return;
      }}
      el.style.display = "flex";
      el.innerHTML = rounds.map((r, i) => {{
        const active = i === activeRoundIndex ? " active" : "";
        const oc = r.outcome ? ` outcome-${{r.outcome}}` : "";
        return `<button type="button" class="round-tab${{active}}${{oc}}" data-idx="${{i}}">Round ${{r.round}} — ${{r.outcome || "?"}}</button>`;
      }}).join("");
      el.querySelectorAll(".round-tab").forEach(btn => {{
        btn.addEventListener("click", () => selectRound(Number(btn.dataset.idx)));
      }});
    }}

    function initReplayBounds() {{
      const L = DATA.map_layout;
      if (L && L.bounds) replayBaseBounds = L.bounds;
    }}

    function replayViewBox() {{
      const b = replayBaseBounds;
      if (!b) return "0 0 800 600";
      const vw = b.w / replayZoom;
      const vh = b.h / replayZoom;
      const cx = b.x + b.w / 2 + replayPanX;
      const cy = b.y + b.h / 2 + replayPanY;
      return `${{cx - vw / 2}} ${{cy - vh / 2}} ${{vw}} ${{vh}}`;
    }}

    function applyReplayViewBox() {{
      const svg = document.querySelector("#map-replay svg");
      if (svg) svg.setAttribute("viewBox", replayViewBox());
      const label = document.getElementById("zoom-level");
      if (label) label.textContent = Math.round(replayZoom * 100) + "%";
    }}

    function parseViewBox(vb) {{
      const p = vb.trim().split(/\\s+/).map(Number);
      return {{ x: p[0], y: p[1], w: p[2], h: p[3] }};
    }}

    function frameIndexForDecisionId(id, marks) {{
      if (!id) return null;
      const hit = (marks || []).find(m => m.id === id);
      return hit != null ? hit.frame : null;
    }}

    function setPlaybackRate(rate) {{
      playbackRate = Math.max(0.25, Math.min(8, rate));
      const sel = document.getElementById("playback-rate");
      if (sel) sel.value = String(playbackRate);
      if (isPlaying) {{
        if (playTimeoutId !== null) clearTimeout(playTimeoutId);
        scheduleNextFrame();
      }}
    }}

    function jumpAlongMarks(marks, direction) {{
      if (!marks.length) return;
      const targets = marks.map(m => m.frame).sort((a, b) => a - b);
      if (direction > 0) {{
        const next = targets.find(f => f > currentFrameIndex);
        if (next != null) updateFrameUI(next);
        else if (targets.length) updateFrameUI(targets[0]);
      }} else {{
        const prev = targets.filter(f => f < currentFrameIndex).pop();
        if (prev != null) updateFrameUI(prev);
        else if (targets.length) updateFrameUI(targets[targets.length - 1]);
      }}
    }}

    function bindReplayLog(container) {{
      if (!container) return;
      container.querySelectorAll(".event-row").forEach(row => {{
        row.addEventListener("click", () => {{
          const frame = row.dataset.frame;
          if (frame !== "") updateFrameUI(Number(frame));
        }});
      }});
    }}

    function highlightReplayLogs(frame) {{
      const dec = frame.decision;
      const decId = dec && !isRiskAction(dec.action, dec.risk) ? (dec.id || "") : "";
      const riskId = dec && isRiskAction(dec.action, dec.risk) ? (dec.id || "") : "";
      document.querySelectorAll("#replay-decision-log .event-row").forEach(el => {{
        el.classList.toggle("event-active", !!decId && el.dataset.decisionId === decId);
      }});
      document.querySelectorAll("#replay-risk-log .event-row").forEach(el => {{
        el.classList.toggle("event-active", !!riskId && el.dataset.decisionId === riskId);
      }});
    }}

    function replayEventRow(d, marks, formatter) {{
      const frame = frameIndexForDecisionId(d.id, marks);
      const frameAttr = frame != null ? frame : "";
      return `<div class="event-row" data-decision-id="${{d.id || ""}}" data-frame="${{frameAttr}}">${{formatter(d)}}</div>`;
    }}

    function zoomReplayAt(factor, clientX, clientY) {{
      if (!replayBaseBounds) return;
      const viewport = document.getElementById("replay-viewport");
      const svg = document.querySelector("#map-replay svg");
      if (!viewport || !svg) return;

      const rect = viewport.getBoundingClientRect();
      const nx = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const ny = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
      const before = parseViewBox(svg.getAttribute("viewBox") || replayViewBox());
      const focusX = before.x + nx * before.w;
      const focusY = before.y + ny * before.h;

      replayZoom = Math.min(6, Math.max(0.4, replayZoom * factor));
      const after = parseViewBox(replayViewBox());
      replayPanX += focusX - (after.x + nx * after.w);
      replayPanY += focusY - (after.y + ny * after.h);
      applyReplayViewBox();
    }}

    function resetReplayZoom() {{
      replayZoom = 1;
      replayPanX = 0;
      replayPanY = 0;
      applyReplayViewBox();
    }}

    function initReplayZoom() {{
      initReplayBounds();
      const viewport = document.getElementById("replay-viewport");
      document.getElementById("zoom-in").addEventListener("click", () => {{
        const r = viewport.getBoundingClientRect();
        zoomReplayAt(1.25, r.left + r.width / 2, r.top + r.height / 2);
      }});
      document.getElementById("zoom-out").addEventListener("click", () => {{
        const r = viewport.getBoundingClientRect();
        zoomReplayAt(0.8, r.left + r.width / 2, r.top + r.height / 2);
      }});
      document.getElementById("zoom-reset").addEventListener("click", resetReplayZoom);

      viewport.addEventListener("wheel", (e) => {{
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.12 : 0.89;
        zoomReplayAt(factor, e.clientX, e.clientY);
      }}, {{ passive: false }});

      viewport.addEventListener("mousedown", (e) => {{
        if (e.button !== 0) return;
        replayDrag = {{ startX: e.clientX, startY: e.clientY, panX: replayPanX, panY: replayPanY }};
        viewport.classList.add("is-dragging");
      }});
      window.addEventListener("mousemove", (e) => {{
        if (!replayDrag) return;
        const svg = document.querySelector("#map-replay svg");
        const rect = viewport.getBoundingClientRect();
        if (!svg || !rect.width) return;
        const vb = parseViewBox(svg.getAttribute("viewBox") || replayViewBox());
        const dx = e.clientX - replayDrag.startX;
        const dy = e.clientY - replayDrag.startY;
        replayPanX = replayDrag.panX - (dx / rect.width) * vb.w;
        replayPanY = replayDrag.panY - (dy / rect.height) * vb.h;
        applyReplayViewBox();
      }});
      window.addEventListener("mouseup", () => {{
        if (!replayDrag) return;
        replayDrag = null;
        viewport.classList.remove("is-dragging");
      }});
    }}

    function outcomeColor(outcome) {{
      if (outcome === "success") return "var(--success)";
      if (outcome === "collision") return "var(--danger)";
      return "var(--warn)";
    }}


    function isRiskAction(action, risk) {{
      return action === "risk_event" || action === "car_honk" || !!risk;
    }}

    function lightPhase(light) {{
      if (!light) return {{ state: "green", in: 0, next: "yellow", turnState: "red", turnIn: 0, turnNext: "green" }};
      if (typeof light === "string") return {{ state: light, in: 0, next: "yellow", turnState: "red", turnIn: 0, turnNext: "green" }};
      return {{
        state: light.s || "green",
        in: light.in || 0,
        next: light.next || "yellow",
        turnState: light.ts || "red",
        turnIn: light.tin || 0,
        turnNext: light.tnext || "green",
      }};
    }}

    function formatDecisionLine(d) {{
      const idSpan = d.id ? `<span class="decision-id">${{d.id}}</span> ` : "";
      const extra = d.commit_time_s != null ? " (" + d.commit_time_s + "s)" : "";
      return `${{idSpan}}<strong>${{d.t}}s</strong> ${{d.action}}${{extra}}`;
    }}

    function formatRiskLine(d) {{
      const idSpan = d.id ? `<span class="decision-id">${{d.id}}</span> ` : "";
      const riskText = d.risk_label || d.risk || d.action;
      return `${{idSpan}}<strong>${{d.t}}s</strong> Risk: ${{riskText}}`;
    }}

    function bulbColors(state) {{
      return [
        state === "red" ? "#dc1e1e" : "#501414",
        state === "yellow" ? "#ebb828" : "#554618",
        state === "green" ? "#28c828" : "#145014",
      ];
    }}

    function rgbHex(rgb) {{
      if (!rgb || rgb.length < 3) return "#c62828";
      const h = (n) => Math.max(0, Math.min(255, n)).toString(16).padStart(2, "0");
      return `#${{h(rgb[0])}}${{h(rgb[1])}}${{h(rgb[2])}}`;
    }}

    function archetypeForCar(car) {{
      const list = DATA.car_archetypes || [];
      const idx = car.a != null ? car.a : 0;
      return list[idx] || list[0] || {{ style: "sedan" }};
    }}

    function paletteForCar(car) {{
      const p = archetypeForCar(car);
      if (!p || !p.body) return {{ body: "#c62828", cabin: "#e53935", trim: "#8b1a1a", glass: "#b3e5fc", style: "sedan" }};
      return {{
        style: p.style || "sedan",
        body: rgbHex(p.body),
        cabin: rgbHex(p.cabin),
        trim: rgbHex(p.trim),
        glass: rgbHex(p.glass),
        accent: p.accent ? rgbHex(p.accent) : null,
        stripe: !!p.stripe,
        roof_rack: !!p.roof_rack,
      }};
    }}

    function layoutForStyle(style, vertical) {{
      const layouts = {{
        sport: vertical ? [0.12, 0.76, 0.26, 0.48] : [0.26, 0.48, 0.12, 0.76],
        compact: vertical ? [0.14, 0.72, 0.24, 0.50] : [0.24, 0.50, 0.14, 0.72],
        suv: vertical ? [0.08, 0.84, 0.12, 0.78] : [0.12, 0.78, 0.08, 0.84],
        wagon: vertical ? [0.10, 0.82, 0.14, 0.76] : [0.14, 0.76, 0.10, 0.82],
        pickup: vertical ? [0.10, 0.80, 0.14, 0.42] : [0.14, 0.42, 0.10, 0.80],
        van: vertical ? [0.08, 0.86, 0.10, 0.80] : [0.10, 0.80, 0.08, 0.86],
        hatch: vertical ? [0.12, 0.78, 0.18, 0.58] : [0.18, 0.58, 0.12, 0.78],
        sedan: vertical ? [0.12, 0.78, 0.18, 0.64] : [0.18, 0.64, 0.12, 0.78],
      }};
      const L = layouts[style] || layouts.sedan;
      return {{ cx: L[0], cw: L[1], cy: L[2], ch: L[3] }};
    }}

    function honkSvg(cx, cy) {{
      return `<g transform="translate(${{cx}},${{cy}})">
        <rect x="-30" y="-36" width="60" height="22" rx="8" fill="#fff3cd" stroke="#f5a524" stroke-width="2"/>
        <text x="0" y="-21" text-anchor="middle" font-size="11" font-weight="700" fill="#7a4a00">HONK!</text>
        <path d="M-22 -14 C-28 -6 -20 0" stroke="#f5a524" fill="none" stroke-width="2"/>
        <path d="M22 -14 C28 -6 20 0" stroke="#f5a524" fill="none" stroke-width="2"/>
      </g>`;
    }}

    function carBodyContent(w, h, vertical, pal, car, frameTime) {{
      const L = layoutForStyle(pal.style, vertical);
      const wheel = "#212121";
      const rx = Math.min(6, (vertical ? w : h) / 3);
      let svg = `<g>`;
      if (!vertical) {{
        svg += `<rect x="1" y="5" width="${{w - 2}}" height="${{h - 10}}" rx="${{rx}}" fill="${{pal.body}}" stroke="${{pal.trim}}" stroke-width="1"/>`;
        if (pal.style === "pickup") {{
          svg += `<rect x="${{Math.floor(w * 0.48)}}" y="7" width="${{w - Math.floor(w * 0.48) - 2}}" height="${{h - 14}}" rx="2" fill="${{pal.trim}}"/>`;
        }}
        const cabX = Math.floor(w * L.cx), cabY = Math.floor(h * L.cy), cabW = Math.floor(w * L.cw), cabH = Math.floor(h * L.ch);
        svg += `<rect x="${{cabX}}" y="${{cabY}}" width="${{cabW}}" height="${{cabH}}" rx="3" fill="${{pal.cabin}}"/>`;
        svg += `<rect x="${{cabX + Math.floor(cabW * 0.14)}}" y="${{cabY + 2}}" width="${{Math.floor(cabW * 0.72)}}" height="${{cabH - 4}}" rx="2" fill="${{pal.glass}}" opacity="0.9"/>`;
        if (pal.stripe && pal.accent) svg += `<rect x="2" y="${{h / 2 - 1}}" width="${{w - 4}}" height="2" fill="${{pal.accent}}"/>`;
        if (pal.roof_rack) svg += `<line x1="${{cabX}}" y1="${{cabY - 2}}" x2="${{cabX + cabW}}" y2="${{cabY - 2}}" stroke="${{pal.trim}}" stroke-width="2"/>`;
        svg += `<ellipse cx="7" cy="3" rx="4" ry="2.5" fill="${{wheel}}"/><ellipse cx="${{w - 7}}" cy="3" rx="4" ry="2.5" fill="${{wheel}}"/>`;
        svg += `<ellipse cx="7" cy="${{h - 3}}" rx="4" ry="2.5" fill="${{wheel}}"/><ellipse cx="${{w - 7}}" cy="${{h - 3}}" rx="4" ry="2.5" fill="${{wheel}}"/>`;
        svg += `<circle cx="${{w - 5}}" cy="${{h / 2}}" r="2" fill="#fff9c4"/><circle cx="5" cy="${{h / 2}}" r="1.5" fill="#ff8f00" opacity="0.75"/>`;
        if (car.ts) {{
          const blink = (Math.floor((frameTime || 0) * 10) % 2) === 0;
          const col = blink ? "#ffd640" : "#b48c28";
          let ly = car.ts < 0 ? 4 : h - 5;
          const dir = car.dir != null ? car.dir : 1;
          if (dir < 0) ly = h - ly;
          svg += `<circle cx="${{w / 2}}" cy="${{ly}}" r="3" fill="${{col}}"/>`;
        }}
      }} else {{
        svg += `<rect x="5" y="1" width="${{w - 10}}" height="${{h - 2}}" rx="${{rx}}" fill="${{pal.body}}" stroke="${{pal.trim}}" stroke-width="1"/>`;
        if (pal.style === "pickup") {{
          svg += `<rect x="7" y="${{Math.floor(h * 0.48)}}" width="${{w - 14}}" height="${{h - Math.floor(h * 0.48) - 2}}" rx="2" fill="${{pal.trim}}"/>`;
        }}
        const cabX = Math.floor(w * L.cx), cabY = Math.floor(h * L.cy), cabW = Math.floor(w * L.cw), cabH = Math.floor(h * L.ch);
        svg += `<rect x="${{cabX}}" y="${{cabY}}" width="${{cabW}}" height="${{cabH}}" rx="3" fill="${{pal.cabin}}"/>`;
        svg += `<rect x="${{cabX + 2}}" y="${{cabY + Math.floor(cabH * 0.14)}}" width="${{cabW - 4}}" height="${{Math.floor(cabH * 0.72)}}" rx="2" fill="${{pal.glass}}" opacity="0.9"/>`;
        if (pal.stripe && pal.accent) svg += `<rect x="${{w / 2 - 1}}" y="2" width="2" height="${{h - 4}}" fill="${{pal.accent}}"/>`;
        if (pal.roof_rack) svg += `<line x1="${{cabX - 2}}" y1="${{cabY}}" x2="${{cabX - 2}}" y2="${{cabY + cabH}}" stroke="${{pal.trim}}" stroke-width="2"/>`;
        svg += `<ellipse cx="3" cy="7" rx="2.5" ry="4" fill="${{wheel}}"/><ellipse cx="${{w - 3}}" cy="7" rx="2.5" ry="4" fill="${{wheel}}"/>`;
        svg += `<ellipse cx="3" cy="${{h - 7}}" rx="2.5" ry="4" fill="${{wheel}}"/><ellipse cx="${{w - 3}}" cy="${{h - 7}}" rx="2.5" ry="4" fill="${{wheel}}"/>`;
        svg += `<circle cx="${{w / 2}}" cy="5" r="2" fill="#fff9c4"/><circle cx="${{w / 2}}" cy="${{h - 5}}" r="1.5" fill="#ff8f00" opacity="0.75"/>`;
        if (car.ts) {{
          const blink = (Math.floor((frameTime || 0) * 10) % 2) === 0;
          const col = blink ? "#ffd640" : "#b48c28";
          let lx = car.ts < 0 ? 4 : w - 5;
          const dir = car.dir != null ? car.dir : 1;
          if (dir < 0) lx = w - lx;
          svg += `<circle cx="${{lx}}" cy="${{h / 2}}" r="3" fill="${{col}}"/>`;
        }}
      }}
      svg += `</g>`;
      return svg;
    }}

    function carSvg(car, frameTime) {{
      const w = car.w, h = car.h;
      const pal = paletteForCar(car);
      if (car.ang != null && car.cx != null && car.cy != null) {{
        // Match PIL rotate() in sprites.make_car_rotated_in_box (CCW); SVG is CW.
        const body = carBodyContent(w, h, false, pal, car, frameTime);
        const svgAng = -car.ang;
        return `<g transform="translate(${{car.cx}},${{car.cy}}) rotate(${{svgAng}}) translate(${{-w / 2}},${{-h / 2}})">${{body}}</g>`;
      }}
      const vertical = car.v === 1;
      const body = carBodyContent(w, h, vertical, pal, car, frameTime);
      return `<g transform="translate(${{car.x}},${{car.y}})">${{body}}</g>`;
    }}

    function playerSvg(p) {{
      const size = p.s || 28;
      const cx = p.x;
      const cy = p.y;
      const fill = "#26a69a";
      const stroke = "#ffffff";
      const headR = size * 0.24;
      const shoulderW = size * 0.62;
      const bodyH = size * 0.42;
      const headCy = cy - size * 0.14;
      const bodyCy = cy + size * 0.12;
      return `<g>
        <ellipse cx="${{cx}}" cy="${{bodyCy}}" rx="${{shoulderW / 2}}" ry="${{bodyH / 2}}" fill="${{fill}}" stroke="${{stroke}}" stroke-width="1.5"/>
        <circle cx="${{cx}}" cy="${{headCy}}" r="${{headR}}" fill="${{fill}}" stroke="${{stroke}}" stroke-width="1.5"/>
      </g>`;
    }}

    function drawFrame(frame) {{
      const el = document.getElementById("map-replay");
      const L = DATA.map_layout;
      const frames = DATA.frames || [];
      if (!L || !frames.length) {{
        el.innerHTML = "<p class='subtitle'>Frame replay needs a new game run. Play again, then reopen this dashboard.</p>";
        return;
      }}
      if (!replayBaseBounds) initReplayBounds();
      let svg = `<svg viewBox="${{replayViewBox()}}" class="replay-svg" xmlns="http://www.w3.org/2000/svg">`;
      const b = L.bounds;
      svg += `<defs><pattern id="crosswalkStripe" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="12" fill="#f0f0f0"/><rect x="6" width="6" height="12" fill="#d8d8d8"/></pattern></defs>`;
      svg += `<rect x="${{b.x}}" y="${{b.y}}" width="${{b.w}}" height="${{b.h}}" fill="#c8dcc4"/>`;
      const blockFills = {{
        park: "#4a8050",
        residential: "#c4b498",
        commercial: "#7888a8",
        plaza: "#d2c8bc",
      }};
      for (const blk of (L.city_blocks || [])) {{
        const fill = blockFills[blk.kind] || "#b8b0a4";
        svg += `<rect x="${{blk.x}}" y="${{blk.y}}" width="${{blk.w}}" height="${{blk.h}}" fill="${{fill}}" stroke="#9a9488" stroke-width="1" rx="4"/>`;
      }}
      for (const d of (L.decorations || [])) {{
        if (d.type === "tree") {{
          const sc = d.scale || 1;
          const r = 10 * sc;
          svg += `<circle cx="${{d.x}}" cy="${{d.y - 4}}" r="${{r}}" fill="#3a8a48"/>`;
          svg += `<rect x="${{d.x - 3}}" y="${{d.y}}" width="6" height="${{14 * sc}}" fill="#6b4a2e"/>`;
        }} else if (d.type === "lamp") {{
          svg += `<line x1="${{d.x}}" y1="${{d.y}}" x2="${{d.x}}" y2="${{d.y - 22}}" stroke="#555" stroke-width="3"/>`;
          svg += `<circle cx="${{d.x}}" cy="${{d.y - 24}}" r="5" fill="#fff6c8"/>`;
        }} else if (d.type === "bench") {{
          if (d.wide) {{
            svg += `<rect x="${{d.x - 14}}" y="${{d.y - 4}}" width="28" height="8" fill="#8a6848" rx="2"/>`;
          }} else {{
            svg += `<rect x="${{d.x - 4}}" y="${{d.y - 12}}" width="8" height="24" fill="#8a6848" rx="2"/>`;
          }}
        }}
      }}
      const zoneColors = {{
        intersection: "rgba(245, 165, 36, 0.14)",
        crossing: "rgba(38, 166, 154, 0.12)",
        choke: "rgba(220, 80, 80, 0.12)",
        spawn: "rgba(80, 120, 220, 0.1)",
        goal: "rgba(34, 68, 204, 0.12)",
      }};
      for (const zone of (L.analytics_zones || [])) {{
        const r = zone.rect;
        if (!r || r.length < 4) continue;
        const fill = zoneColors[zone.type] || "rgba(120, 120, 120, 0.1)";
        svg += `<rect x="${{r[0]}}" y="${{r[1]}}" width="${{r[2]}}" height="${{r[3]}}" fill="${{fill}}" stroke="none"/>`;
      }}
      for (const road of L.roads) {{
        svg += `<rect x="${{road.x}}" y="${{road.y}}" width="${{road.w}}" height="${{road.h}}" fill="#3a3f44" stroke="#2e3236" stroke-width="1"/>`;
        if (road.direction === "vertical" && road.w > 80) {{
          const cy = road.y + road.h / 2;
          for (let x = road.x + 12; x < road.x + road.w - 12; x += 22) {{
            svg += `<line x1="${{x}}" y1="${{cy}}" x2="${{x + 10}}" y2="${{cy}}" stroke="#dcc846" stroke-width="2"/>`;
          }}
        }} else if (road.direction === "horizontal" && road.h > 80) {{
          const cx = road.x + road.w / 2;
          for (let y = road.y + 12; y < road.y + road.h - 12; y += 22) {{
            svg += `<line x1="${{cx}}" y1="${{y}}" x2="${{cx}}" y2="${{y + 10}}" stroke="#dcc846" stroke-width="2"/>`;
          }}
        }}
      }}
      function signalBulbCenters(housing, direction, approach) {{
        const hx = housing[0], hy = housing[1], hw = housing[2], hh = housing[3];
        if (direction === "vertical") {{
          const bx = approach === "east" ? hx + hw - 11 : hx + 11;
          return [
            [bx, hy + 10], [bx, hy + 28], [bx, hy + 46],
          ];
        }}
        const by = approach === "south" ? hy + hh - 11 : hy + 11;
        return [
          [hx + 10, by], [hx + 28, by], [hx + 46, by],
        ];
      }}
      function signalTurnBulb(housing, direction, approach) {{
        const hx = housing[0], hy = housing[1], hw = housing[2], hh = housing[3];
        if (direction === "vertical") {{
          const bx = approach === "east" ? hx + hw - 11 : hx + 11;
          return [bx + 18, hy + 28];
        }}
        const by = approach === "south" ? hy + hh - 11 : hy + 11;
        return [hx + 28, by - 18];
      }}
      const signals = L.crosswalks || [];
      const lights = frame.lights || [];
      signals.forEach((cw, i) => {{
        svg += `<rect x="${{cw.x}}" y="${{cw.y}}" width="${{cw.w}}" height="${{cw.h}}" fill="url(#crosswalkStripe)" stroke="#bdbdbd"/>`;
        const housing = cw.housing;
        if (!housing) return;
        const approach = cw.approach || "west";
        const phase = lightPhase(lights[i]);
        const colors = bulbColors(phase.state);
        svg += `<rect x="${{housing[0]}}" y="${{housing[1]}}" width="${{housing[2]}}" height="${{housing[3]}}" fill="#191919" stroke="#464646" stroke-width="2" rx="5"/>`;
        signalBulbCenters(housing, cw.direction, approach).forEach(([bx, by], idx) => {{
          svg += `<circle cx="${{bx}}" cy="${{by}}" r="6" fill="${{colors[idx]}}"/>`;
        }});
        if (phase.turnState === "green" && phase.state === "red") {{
          const [tx, ty] = signalTurnBulb(housing, cw.direction, approach);
          svg += `<circle cx="${{tx}}" cy="${{ty}}" r="7" fill="#2de685"/>`;
        }}
        let timerX, timerY, timerAnchor;
        if (cw.direction === "vertical") {{
          timerX = approach === "east" ? housing[0] - 8 : housing[0] + housing[2] + 8;
          timerY = housing[1] + housing[3] / 2;
          timerAnchor = approach === "east" ? "end" : "start";
        }} else {{
          timerX = housing[0] + housing[2] / 2;
          timerY = approach === "south" ? housing[1] - 6 : housing[1] + housing[3] + 14;
          timerAnchor = "middle";
        }}
        const timerLabel = phase.turnState === "green" && phase.state === "red"
          ? `turn ${{phase.turnIn.toFixed(1)}}s → ${{phase.turnNext}}`
          : `${{phase.in.toFixed(1)}}s → ${{phase.next}}`;
        svg += `<text class="light-timer" x="${{timerX}}" y="${{timerY}}" text-anchor="${{timerAnchor}}">${{timerLabel}}</text>`;
      }});
      const goal = L.goal;
      svg += `<rect x="${{goal.x - 8}}" y="${{goal.y - 8}}" width="${{goal.w + 16}}" height="${{goal.h + 16}}" fill="#ffdc50" opacity="0.5" rx="10"/>`;
      svg += `<rect x="${{goal.x}}" y="${{goal.y}}" width="${{goal.w}}" height="${{goal.h}}" fill="#2258d8" stroke="#fff" stroke-width="2" rx="6"/>`;
      for (const car of frame.cars || []) {{
        svg += carSvg(car, frame.t);
        if (car.honk) {{
          const hx = car.cx != null ? car.cx : car.x + car.w / 2;
          const hy = car.cy != null ? car.cy - car.h / 2 - 4 : car.y - 4;
          svg += honkSvg(hx, hy);
        }}
      }}
      const p = frame.player;
      const pSize = p.s || 28;
      svg += playerSvg(p);
      if (frame.decision) {{
        svg += `<circle cx="${{p.x}}" cy="${{p.y - pSize * 0.55}}" r="8" fill="#f5a524" stroke="#fff" stroke-width="2"/>`;
      }}
      svg += `</svg>`;
      el.innerHTML = svg;
      applyReplayViewBox();
    }}

    function lerpNum(a, b, alpha) {{
      return a + (b - a) * alpha;
    }}

    function lerpAngleDeg(a, b, alpha) {{
      let delta = ((b - a + 180) % 360) - 180;
      return a + delta * alpha;
    }}

    function framePairAtTime(t) {{
      const frames = DATA.frames || [];
      if (!frames.length) return {{ left: 0, right: 0, alpha: 0 }};
      if (t <= frames[0].t) return {{ left: 0, right: 0, alpha: 0 }};
      const last = frames.length - 1;
      if (t >= frames[last].t) return {{ left: last, right: last, alpha: 0 }};
      let lo = 0;
      let hi = last;
      while (lo + 1 < hi) {{
        const mid = Math.floor((lo + hi) / 2);
        if (frames[mid].t <= t) lo = mid;
        else hi = mid;
      }}
      const span = frames[hi].t - frames[lo].t;
      const alpha = span > 1e-9 ? (t - frames[lo].t) / span : 0;
      return {{ left: lo, right: hi, alpha: Math.max(0, Math.min(1, alpha)) }};
    }}

    function lerpReplayFrame(left, right, alpha, t) {{
      if (alpha <= 0) return left;
      if (alpha >= 1) return right;
      const simT = t != null ? t : lerpNum(left.t, right.t, alpha);
      const lp = left.player || {{}};
      const rp = right.player || {{}};
      const player = {{
        x: Math.round(lerpNum(lp.x || 0, rp.x || 0, alpha)),
        y: Math.round(lerpNum(lp.y || 0, rp.y || 0, alpha)),
        s: lp.s || rp.s || 28,
      }};
      const leftCars = {{}};
      (left.cars || []).forEach(c => {{ leftCars[c.id] = c; }});
      const rightCars = {{}};
      (right.cars || []).forEach(c => {{ rightCars[c.id] = c; }});
      const cars = [];
      const ids = new Set([...Object.keys(leftCars), ...Object.keys(rightCars)].map(Number));
      ids.forEach(id => {{
        const lc = leftCars[id];
        const rc = rightCars[id];
        if (lc && rc) {{
          const merged = {{ ...lc }};
          ["x", "y", "cx", "cy"].forEach(k => {{
            if (lc[k] != null && rc[k] != null) merged[k] = Math.round(lerpNum(lc[k], rc[k], alpha));
          }});
          if (lc.ang != null && rc.ang != null) merged.ang = Math.round(lerpAngleDeg(lc.ang, rc.ang, alpha) * 10) / 10;
          if (lc.sp != null && rc.sp != null) merged.sp = Math.round(lerpNum(lc.sp, rc.sp, alpha) * 100) / 100;
          cars.push(merged);
        }} else if (lc && alpha < 0.5) {{
          cars.push({{ ...lc }});
        }} else if (rc && alpha >= 0.5) {{
          cars.push({{ ...rc }});
        }}
      }});
      const out = {{
        id: left.id,
        seq: left.seq,
        t: simT,
        player,
        cars,
        lights: left.lights || right.lights || [],
        interpolated: true,
      }};
      if (alpha >= 0.5 && right.decision) {{
        out.decision = right.decision;
        out.is_decision = !!right.is_decision;
      }} else if (left.decision && alpha < 0.5) {{
        out.decision = left.decision;
        out.is_decision = !!left.is_decision;
      }}
      return out;
    }}

    function frameAtTime(t) {{
      const frames = DATA.frames || [];
      if (!frames.length) return {{}};
      const pair = framePairAtTime(t);
      if (pair.left === pair.right) return frames[pair.left];
      return lerpReplayFrame(frames[pair.left], frames[pair.right], pair.alpha, t);
    }}

    function nearestFrameIndex(t) {{
      const frames = DATA.frames || [];
      if (!frames.length) return 0;
      let best = 0;
      let bestDist = Infinity;
      for (let i = 0; i < frames.length; i++) {{
        const d = Math.abs(frames[i].t - t);
        if (d < bestDist) {{
          bestDist = d;
          best = i;
        }}
      }}
      return best;
    }}

    function renderPlayhead(t, fromPlayback = false) {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      playheadT = t;
      const frame = frameAtTime(t);
      const idx = nearestFrameIndex(t);
      currentFrameIndex = idx;
      const slider = document.getElementById("frame-slider");
      if (slider) slider.value = String(idx);
      document.getElementById("frame-time").textContent = t.toFixed(1) + "s";
      document.getElementById("frame-index").textContent = `Frame ${{idx + 1}} / ${{frames.length}}`;
      const dec = frame.decision;
      let decLabel = "";
      if (dec && !isRiskAction(dec.action, dec.risk)) {{
        decLabel = (dec.id ? dec.id + " — " : "") + dec.label;
      }}
      document.getElementById("frame-decision-label").textContent = decLabel;
      if (!fromPlayback) highlightReplayLogs(frames[idx]);
      drawFrame(frame);
    }}

    function stopPlayback() {{
      isPlaying = false;
      if (playRafId !== null) {{
        cancelAnimationFrame(playRafId);
        playRafId = null;
      }}
      const playBtn = document.getElementById("frame-play");
      if (playBtn) {{
        playBtn.textContent = "\u25B6";
        playBtn.title = "Play replay";
        playBtn.setAttribute("aria-label", "Play replay");
        playBtn.classList.remove("is-playing");
      }}
    }}

    function playbackLoop(wallNow) {{
      if (!isPlaying) return;
      const frames = DATA.frames || [];
      if (!frames.length) {{
        stopPlayback();
        return;
      }}
      const elapsed = (wallNow - playAnchorWall) / 1000 * playbackRate;
      const t = playAnchorSim + elapsed;
      const endT = frames[frames.length - 1].t;
      if (t >= endT) {{
        renderPlayhead(endT, true);
        stopPlayback();
        return;
      }}
      renderPlayhead(t, true);
      playRafId = requestAnimationFrame(playbackLoop);
    }}

    function startPlaybackLoop() {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      playAnchorWall = performance.now();
      playAnchorSim = playheadT;
      if (playRafId !== null) cancelAnimationFrame(playRafId);
      playRafId = requestAnimationFrame(playbackLoop);
    }}

    function togglePlayback() {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      if (isPlaying) {{
        stopPlayback();
        return;
      }}
      if (currentFrameIndex >= frames.length - 1 || playheadT >= frames[frames.length - 1].t) {{
        playheadT = frames[0].t;
        updateFrameUI(0, true);
      }}
      isPlaying = true;
      const playBtn = document.getElementById("frame-play");
      playBtn.textContent = "\u23F8";
      playBtn.title = "Pause replay";
      playBtn.setAttribute("aria-label", "Pause replay");
      playBtn.classList.add("is-playing");
      startPlaybackLoop();
    }}

    function updateFrameUI(index, fromPlayback = false) {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      if (!fromPlayback) stopPlayback();
      currentFrameIndex = Math.max(0, Math.min(index, frames.length - 1));
      playheadT = frames[currentFrameIndex].t;
      renderPlayhead(playheadT, fromPlayback);
      if (!fromPlayback) highlightReplayLogs(frames[currentFrameIndex]);
    }}

    function buildDecisionTicks() {{
      const ticksEl = document.getElementById("decision-ticks");
      const marks = DATA.decision_marks || [];
      const frames = DATA.frames || [];
      if (!frames.length) {{
        ticksEl.innerHTML = "";
        return;
      }}
      const max = frames.length - 1;
      ticksEl.innerHTML = marks.map(m => {{
        const pct = (m.frame / max) * 100;
        const tip = (m.id ? m.id + " — " : "") + m.label + " @ " + m.t + "s";
        return `<button type="button" class="decision-tick" style="left:${{pct}}%" title="${{tip}}" data-frame="${{m.frame}}" data-decision-id="${{m.id || ""}}"></button>`;
      }}).join("");
      ticksEl.querySelectorAll(".decision-tick").forEach(btn => {{
        btn.addEventListener("click", () => updateFrameUI(Number(btn.dataset.frame)));
      }});
    }}


    function frameForSimTime(simT) {{
      const frames = DATA.frames || [];
      if (!frames.length) return 0;
      let best = 0;
      let bestD = 1e9;
      for (let i = 0; i < frames.length; i++) {{
        const ft = frames[i].t;
        if (ft == null) continue;
        const d = Math.abs(ft - simT);
        if (d < bestD) {{
          bestD = d;
          best = i;
        }}
      }}
      return best;
    }}

    function buildSpectateAnomalyTicks() {{
      const ticksEl = document.getElementById("decision-ticks");
      const anomalies = DATA.spectate_anomalies || [];
      const frames = DATA.frames || [];
      if (!ticksEl || !frames.length || !anomalies.length) return;
      const max = frames.length - 1;
      const extra = anomalies.map(a => {{
        const frame = frameForSimTime(a.sim_t);
        const pct = (frame / max) * 100;
        const tip = (a.kind || "anomaly") + " @ " + a.sim_t + "s — " + (a.summary || "");
        return `<button type="button" class="decision-tick spectate-tick" style="left:${{pct}}%;background:#b86bff" title="${{tip}}" data-frame="${{frame}}"></button>`;
      }}).join("");
      ticksEl.insertAdjacentHTML("beforeend", extra);
      ticksEl.querySelectorAll(".spectate-tick").forEach(btn => {{
        btn.addEventListener("click", () => updateFrameUI(Number(btn.dataset.frame)));
      }});
    }}

    function buildSpectateAnomalyPanel() {{
      const panel = document.getElementById("spectate-anomaly-panel");
      const jump = document.getElementById("spectate-anomaly-jump");
      const log = document.getElementById("spectate-anomaly-log");
      const metricsLine = document.getElementById("spectate-metrics-line");
      const anomalies = DATA.spectate_anomalies || [];
      const metrics = DATA.spectate_metrics || {{}};
      if (!panel || (!anomalies.length && !Object.keys(metrics).length)) return;
      panel.style.display = "block";
      if (metricsLine && Object.keys(metrics).length) {{
        const arcPre = metrics.turn_arc_pre_separation_frames ?? 0;
        const arcPost = metrics.turn_arc_overlap_frames ?? 0;
        const preSep = metrics.pre_separation_overlap_frames ?? 0;
        metricsLine.style.display = "block";
        metricsLine.textContent =
          `Turn arc overlap: pre=${{arcPre}} post=${{arcPost}} · pre-sep shells=${{preSep}} · anomalies=${{metrics.anomaly_count ?? 0}}`;
      }}
      if (jump) {{
        jump.innerHTML = '<option value="">Jump to anomaly…</option>' +
          anomalies.map((a, i) => {{
            const frame = frameForSimTime(a.sim_t);
            return `<option value="${{frame}}">${{a.sim_t.toFixed(1)}}s — ${{a.kind}} — ${{a.summary || ""}}</option>`;
          }}).join("");
      }}
      if (log) {{
        log.innerHTML = anomalies.length
          ? anomalies.map(a =>
              `<div class="event-line"><strong>${{a.sim_t.toFixed(1)}}s</strong> [${{a.kind}}] ${{a.summary || ""}}</div>`
            ).join("")
          : '<div class="event-line muted">No anomalies recorded.</div>';
      }}
    }}

    function buildRiskTicks() {{
      const ticksEl = document.getElementById("risk-ticks");
      const marks = DATA.risk_marks || [];
      const frames = DATA.frames || [];
      if (!ticksEl || !frames.length) {{
        if (ticksEl) ticksEl.innerHTML = "";
        return;
      }}
      const max = frames.length - 1;
      ticksEl.innerHTML = marks.map(m => {{
        const pct = (m.frame / max) * 100;
        const tip = (m.id ? m.id + " — " : "") + m.label + " @ " + m.t + "s";
        return `<button type="button" class="decision-tick risk-tick" style="left:${{pct}}%" title="${{tip}}" data-frame="${{m.frame}}"></button>`;
      }}).join("");
      ticksEl.querySelectorAll(".risk-tick").forEach(btn => {{
        btn.addEventListener("click", () => updateFrameUI(Number(btn.dataset.frame)));
      }});
    }}

    function populateJumpDropdowns() {{
      const jump = document.getElementById("frame-decision-jump");
      if (jump) {{
        jump.innerHTML = '<option value="">Jump to decision…</option>' +
          (DATA.decision_marks || []).map(m =>
            `<option value="${{m.frame}}" data-decision-id="${{m.id || ""}}">${{m.id || "?"}} — ${{m.t.toFixed(1)}}s — ${{m.label}}</option>`
          ).join("");
      }}
      const riskJump = document.getElementById("frame-risk-jump");
      if (riskJump) {{
        riskJump.innerHTML = '<option value="">Jump to risk…</option>' +
          (DATA.risk_marks || []).map(m =>
            `<option value="${{m.frame}}">${{m.id || "?"}} — ${{m.t.toFixed(1)}}s — ${{m.label}}</option>`
          ).join("");
      }}
    }}

    function setupJumpDropdownListeners() {{
      if (jumpDropdownListenersReady) return;
      jumpDropdownListenersReady = true;
      document.addEventListener("change", (e) => {{
        if (e.target.id === "frame-decision-jump" && e.target.value !== "") {{
          updateFrameUI(Number(e.target.value));
        }}
        if (e.target.id === "frame-risk-jump" && e.target.value !== "") {{
          updateFrameUI(Number(e.target.value));
        }}
      }});
    }}

    function refreshFrameScrubber() {{
      const frames = DATA.frames || [];
      const slider = document.getElementById("frame-slider");
      if (!frames.length) {{
        drawFrame({{}});
        populateJumpDropdowns();
        return;
      }}
      slider.max = String(frames.length - 1);
      slider.value = "0";
      populateJumpDropdowns();
      buildDecisionTicks();
      buildRiskTicks();
      buildSpectateAnomalyTicks();
      buildSpectateAnomalyPanel();
      resetReplayZoom();
      updateFrameUI(0);
    }}

    function initFrameScrubber() {{
      const slider = document.getElementById("frame-slider");
      setupJumpDropdownListeners();
      const anomalyJump = document.getElementById("spectate-anomaly-jump");
      if (anomalyJump && !anomalyJump.dataset.bound) {{
        anomalyJump.dataset.bound = "1";
        anomalyJump.addEventListener("change", () => {{
          const v = anomalyJump.value;
          if (v !== "") updateFrameUI(Number(v));
        }});
      }}
      if (!scrubberInitialized) {{
        scrubberInitialized = true;
        document.getElementById("frame-play").addEventListener("click", togglePlayback);
        document.getElementById("playback-rate").addEventListener("change", (e) => {{
          playbackRate = Number(e.target.value) || 1;
          if (isPlaying) {{
            playAnchorWall = performance.now();
            playAnchorSim = playheadT;
            startPlaybackLoop();
          }}
        }});
        slider.addEventListener("input", () => updateFrameUI(Number(slider.value)));
        document.getElementById("frame-prev").addEventListener("click", () => updateFrameUI(currentFrameIndex - 1));
        document.getElementById("frame-next").addEventListener("click", () => updateFrameUI(currentFrameIndex + 1));
        document.addEventListener("keydown", (e) => {{
          if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return;
          if (e.key === " ") {{
            e.preventDefault();
            togglePlayback();
          }}
          if (e.key === "ArrowLeft") updateFrameUI(currentFrameIndex - 1);
          if (e.key === "ArrowRight") updateFrameUI(currentFrameIndex + 1);
          if (e.key === "+" || e.key === "=") {{
            const r = document.getElementById("replay-viewport").getBoundingClientRect();
            zoomReplayAt(1.2, r.left + r.width / 2, r.top + r.height / 2);
          }}
          if (e.key === "-") {{
            const r = document.getElementById("replay-viewport").getBoundingClientRect();
            zoomReplayAt(1 / 1.2, r.left + r.width / 2, r.top + r.height / 2);
          }}
          if (e.key === "0") resetReplayZoom();
          if (e.key === "[") setPlaybackRate(playbackRate / 2);
          if (e.key === "]") setPlaybackRate(playbackRate * 2);
          if (e.key === "d") jumpAlongMarks(DATA.decision_marks || [], 1);
          if (e.key === "D") jumpAlongMarks(DATA.decision_marks || [], -1);
          if (e.key === "r") jumpAlongMarks(DATA.risk_marks || [], 1);
          if (e.key === "R") jumpAlongMarks(DATA.risk_marks || [], -1);
        }});
        initReplayZoom();
        setPlaybackRate(DEFAULT_PLAYBACK_RATE);
      }}
      refreshFrameScrubber();
    }}

    function renderRoundPanels() {{
      const s = DATA.session;
      const a = DATA.archetypes;
      const sum = s.summary || {{}};

      const statRows = [];
      if ((DATA.rounds || []).length > 1) {{
        statRows.push([
          "Viewing",
          "Round " + (activeRoundIndex + 1) + " / " + DATA.rounds.length,
          "var(--accent)",
        ]);
      }}
      statRows.push(
        ["Outcome", s.outcome, outcomeColor(s.outcome)],
        ["Duration", s.duration_s + "s", "var(--text)"],
        ["Crossings", s.crossings, "var(--text)"],
        ["Risk events", s.risk_events, s.risk_events > 2 ? "var(--warn)" : "var(--text)"],
        ["Hesitation", sum.total_hesitation_s + "s (" + sum.hesitation_count + " pauses)", "var(--text)"],
        ["Backtracks", sum.total_backtracks, "var(--text)"],
      );
      document.getElementById("stats").innerHTML = statRows.map(([label, value, color]) =>
        `<div class="stat"><div class="value" style="color:${{color}}">${{value}}</div><div class="label">${{label}}</div></div>`
      ).join("");

      document.getElementById("primary-archetype").textContent =
        a.primary_label + " (" + a.primary_score + "% fit)";
      document.getElementById("secondary-archetype").textContent =
        a.secondary_label
          ? "Secondary: " + a.secondary_label + " (" + a.secondary_score + "%)"
          : "";

      const bars = document.getElementById("archetype-bars");
      bars.innerHTML = Object.entries(a.scores)
        .sort((x, y) => y[1] - x[1])
        .map(([key, score]) => `
          <div class="bar-row">
            <div class="bar-label"><span>${{a.labels[key]}}</span><span>${{score}}%</span></div>
            <div class="bar-track"><div class="bar-fill" style="width:${{score}}%"></div></div>
          </div>`).join("");

      document.getElementById("insights").innerHTML =
        (a.insights || []).map(i => `<li>${{i}}</li>`).join("");

      document.getElementById("decision-summary").innerHTML = `
        <p><strong>${{sum.decision_count || 0}}</strong> logged decisions ·
        <strong>${{sum.quick_commits || 0}}</strong> quick commits ·
        <strong>${{sum.slow_commits || 0}}</strong> deliberate commits</p>`;

      const seq = s.decision_sequence || [];
      const decisions = seq.filter(d => !isRiskAction(d.action, d.risk)).slice(-40);
      const risks = seq.filter(d => isRiskAction(d.action, d.risk)).slice(-40);
      document.getElementById("decision-log").innerHTML = decisions
        .map(d => `<div>${{formatDecisionLine(d)}}</div>`)
        .join("") || "<div class='subtitle'>No decisions logged.</div>";
      const dm = DATA.decision_marks || [];
      const rm = DATA.risk_marks || [];
      const replayDec = document.getElementById("replay-decision-log");
      if (replayDec) {{
        replayDec.innerHTML = decisions.map(d => replayEventRow(d, dm, formatDecisionLine)).join("")
          || "<div class='subtitle'>No decisions.</div>";
        bindReplayLog(replayDec);
      }}
      const replayRisk = document.getElementById("replay-risk-log");
      if (replayRisk) {{
        replayRisk.innerHTML = risks.map(d => replayEventRow(d, rm, formatRiskLine)).join("")
          || "<div class='subtitle'>No risks.</div>";
        bindReplayLog(replayRisk);
      }}

    }}

    function render() {{
      if (DATA.rounds && DATA.rounds.length) {{
        applyRoundToData(DATA.rounds.length - 1);
      }}
      buildRoundTabs();
      renderRoundPanels();
      initFrameScrubber();
    }}
    render();
  </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Build Pathwise recruiter dashboard from session JSON.")
    parser.add_argument("session_file", nargs="?", default="logs.json", help="Path to session log JSON")
    parser.add_argument("-o", "--output", help="Output HTML path")
    args = parser.parse_args()

    if not os.path.isfile(args.session_file):
        print(f"Session file not found: {args.session_file}")
        print("Play a round first (python main.py), then run this again.")
        return 1

    out = build_dashboard_html(args.session_file, args.output)
    print(f"Dashboard written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
