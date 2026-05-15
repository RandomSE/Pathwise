"""Generate a recruiter-facing HTML dashboard from a Pathwise session log."""

import argparse
import json
import os

from analytics.archetype_scoring import score_session


def build_dashboard_html(session_path, output_path=None):
    with open(session_path, encoding="utf-8") as f:
        payload = json.load(f)

    session = payload.get("session", payload)
    archetypes = payload.get("archetypes") or score_session(session)
    duration = session.get("duration_s", 1)
    frames = session.get("replay_frames", [])
    decision_marks = session.get("decision_marks", [])
    map_layout = session.get("map_layout")
    car_archetypes = session.get("car_archetypes", [])

    if output_path is None:
        base = os.path.splitext(os.path.basename(session_path))[0]
        output_path = os.path.join(os.path.dirname(session_path) or ".", f"{base}_dashboard.html")

    data_json = json.dumps(
        {
            "session": session,
            "archetypes": archetypes,
            "duration": duration,
            "map_layout": map_layout,
            "frames": frames,
            "decision_marks": decision_marks,
            "car_archetypes": car_archetypes,
        }
    )

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
    .frame-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 1rem;
      margin-top: 0.75rem;
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
      <p class="subtitle">Press Play for real-time replay, scrub the slider, or use arrows. Scroll or +/- to zoom, drag to pan. Orange ticks = decision points.</p>
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
        </div>
        <button type="button" id="frame-next" title="Next frame">&#9654;</button>
      </div>
      <div class="frame-meta">
        <span id="frame-time">0.0s</span>
        <span id="frame-index">Frame 0 / 0</span>
        <select id="frame-decision-jump"><option value="">Jump to decision…</option></select>
        <span id="frame-decision-label"></span>
        <label class="subtitle" for="playback-rate">Speed</label>
        <select id="playback-rate" title="Playback speed">
          <option value="0.5">0.5×</option>
          <option value="1" selected>1×</option>
          <option value="1.5">1.5×</option>
          <option value="2">2×</option>
        </select>
      </div>
    </section>
  </main>
  <script>
    const DATA = {data_json};
    let currentFrameIndex = 0;
    let isPlaying = false;
    let playTimeoutId = null;
    let playbackRate = 1;
    let replayZoom = 1;
    let replayPanX = 0;
    let replayPanY = 0;
    let replayBaseBounds = null;
    let replayDrag = null;

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

    function carSvg(car) {{
      const x = car.x, y = car.y, w = car.w, h = car.h;
      const vertical = car.v === 1;
      const pal = paletteForCar(car);
      const L = layoutForStyle(pal.style, vertical);
      const wheel = "#212121";
      const rx = Math.min(6, (vertical ? w : h) / 3);
      let svg = `<g transform="translate(${{x}},${{y}})">`;
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
      }}
      svg += `</g>`;
      return svg;
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
      svg += `<rect x="${{b.x}}" y="${{b.y}}" width="${{b.w}}" height="${{b.h}}" fill="#dde8d8"/>`;
      for (const road of L.roads) {{
        svg += `<rect x="${{road.x}}" y="${{road.y}}" width="${{road.w}}" height="${{road.h}}" fill="#646464"/>`;
      }}
      const signals = L.crosswalks || [];
      const lights = frame.lights || [];
      signals.forEach((cw, i) => {{
        svg += `<rect x="${{cw.x}}" y="${{cw.y}}" width="${{cw.w}}" height="${{cw.h}}" fill="url(#crosswalkStripe)" stroke="#bdbdbd"/>`;
        const housing = cw.housing;
        if (!housing) return;
        const state = lights[i] || "green";
        const colors = bulbColors(state);
        svg += `<rect x="${{housing[0]}}" y="${{housing[1]}}" width="${{housing[2]}}" height="${{housing[3]}}" fill="#191919" stroke="#464646" stroke-width="2" rx="5"/>`;
        if (cw.direction === "vertical") {{
          const cx = housing[0] + housing[2] / 2;
          const tops = [housing[1] + 10, housing[1] + 28, housing[1] + 46];
          tops.forEach((y, idx) => {{ svg += `<circle cx="${{cx}}" cy="${{y}}" r="6" fill="${{colors[idx]}}"/>`; }});
        }} else {{
          const cy = housing[1] + housing[3] / 2;
          const lefts = [housing[0] + 10, housing[0] + 28, housing[0] + 46];
          lefts.forEach((x, idx) => {{ svg += `<circle cx="${{x}}" cy="${{cy}}" r="6" fill="${{colors[idx]}}"/>`; }});
        }}
      }});
      const goal = L.goal;
      svg += `<rect x="${{goal.x}}" y="${{goal.y}}" width="${{goal.w}}" height="${{goal.h}}" fill="#2244cc" stroke="#fff" stroke-width="3"/>`;
      for (const car of frame.cars || []) {{
        svg += carSvg(car);
        if (car.honk) {{
          svg += honkSvg(car.x + car.w / 2, car.y - 4);
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

    function stopPlayback() {{
      isPlaying = false;
      if (playTimeoutId !== null) {{
        clearTimeout(playTimeoutId);
        playTimeoutId = null;
      }}
      const playBtn = document.getElementById("frame-play");
      if (playBtn) {{
        playBtn.textContent = "\\u25B6";
        playBtn.title = "Play replay";
        playBtn.setAttribute("aria-label", "Play replay");
        playBtn.classList.remove("is-playing");
      }}
    }}

    function scheduleNextFrame() {{
      if (!isPlaying) return;
      const frames = DATA.frames || [];
      if (currentFrameIndex >= frames.length - 1) {{
        stopPlayback();
        return;
      }}
      const current = frames[currentFrameIndex];
      const next = frames[currentFrameIndex + 1];
      const deltaMs = Math.max(40, ((next.t - current.t) * 1000) / playbackRate);
      playTimeoutId = setTimeout(() => {{
        playTimeoutId = null;
        updateFrameUI(currentFrameIndex + 1, true);
        scheduleNextFrame();
      }}, deltaMs);
    }}

    function togglePlayback() {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      if (isPlaying) {{
        stopPlayback();
        return;
      }}
      if (currentFrameIndex >= frames.length - 1) {{
        updateFrameUI(0, true);
      }}
      isPlaying = true;
      const playBtn = document.getElementById("frame-play");
      playBtn.textContent = "\\u23F8";
      playBtn.title = "Pause replay";
      playBtn.setAttribute("aria-label", "Pause replay");
      playBtn.classList.add("is-playing");
      scheduleNextFrame();
    }}

    function updateFrameUI(index, fromPlayback = false) {{
      const frames = DATA.frames || [];
      if (!frames.length) return;
      if (!fromPlayback) stopPlayback();
      currentFrameIndex = Math.max(0, Math.min(index, frames.length - 1));
      const frame = frames[currentFrameIndex];
      const slider = document.getElementById("frame-slider");
      slider.value = String(currentFrameIndex);
      document.getElementById("frame-time").textContent = frame.t.toFixed(1) + "s";
      document.getElementById("frame-index").textContent = `Frame ${{currentFrameIndex + 1}} / ${{frames.length}}`;
      const label = frame.decision ? frame.decision.label : "";
      document.getElementById("frame-decision-label").textContent = label;
      drawFrame(frame);
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
        return `<button type="button" class="decision-tick" style="left:${{pct}}%" title="${{m.label}} @ ${{m.t}}s" data-frame="${{m.frame}}"></button>`;
      }}).join("");
      ticksEl.querySelectorAll(".decision-tick").forEach(btn => {{
        btn.addEventListener("click", () => updateFrameUI(Number(btn.dataset.frame)));
      }});
    }}

    function initFrameScrubber() {{
      const frames = DATA.frames || [];
      const slider = document.getElementById("frame-slider");
      const jump = document.getElementById("frame-decision-jump");
      if (!frames.length) {{
        drawFrame({{}});
        return;
      }}
      slider.max = String(frames.length - 1);
      jump.innerHTML = '<option value="">Jump to decision…</option>' +
        (DATA.decision_marks || []).map(m =>
          `<option value="${{m.frame}}">${{m.t.toFixed(1)}}s — ${{m.label}}</option>`
        ).join("");
      buildDecisionTicks();
      document.getElementById("frame-play").addEventListener("click", togglePlayback);
      document.getElementById("playback-rate").addEventListener("change", (e) => {{
        playbackRate = Number(e.target.value) || 1;
        if (isPlaying) {{
          if (playTimeoutId !== null) clearTimeout(playTimeoutId);
          scheduleNextFrame();
        }}
      }});
      slider.addEventListener("input", () => updateFrameUI(Number(slider.value)));
      document.getElementById("frame-prev").addEventListener("click", () => updateFrameUI(currentFrameIndex - 1));
      document.getElementById("frame-next").addEventListener("click", () => updateFrameUI(currentFrameIndex + 1));
      jump.addEventListener("change", () => {{
        if (jump.value !== "") updateFrameUI(Number(jump.value));
      }});
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
      }});
      initReplayZoom();
      updateFrameUI(0);
    }}

    function render() {{
      const s = DATA.session;
      const a = DATA.archetypes;
      const sum = s.summary || {{}};

      document.getElementById("stats").innerHTML = [
        ["Outcome", s.outcome, outcomeColor(s.outcome)],
        ["Duration", s.duration_s + "s", "var(--text)"],
        ["Crossings", s.crossings, "var(--text)"],
        ["Risk events", s.risk_events, s.risk_events > 2 ? "var(--warn)" : "var(--text)"],
        ["Hesitation", sum.total_hesitation_s + "s (" + sum.hesitation_count + " pauses)", "var(--text)"],
        ["Backtracks", sum.total_backtracks, "var(--text)"],
      ].map(([label, value, color]) =>
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

      const log = (s.decision_sequence || []).slice(-40);
      document.getElementById("decision-log").innerHTML = log
        .map(d => `<div><strong>${{d.t}}s</strong> ${{d.action}}${{d.commit_time_s != null ? " (" + d.commit_time_s + "s)" : ""}}</div>`)
        .join("");

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
