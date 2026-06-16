"""Remove extracted blocks from main.py and add module imports."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
lines = MAIN.read_text(encoding="utf-8").splitlines()

# Keep lines 1-61 (imports through geom), then inject new imports
head = lines[:61]

NEW_IMPORTS = [
    "from pathwise.sim_constants import *  # noqa: F403",
    "from pathwise.car import (",
    "    Car,",
    "    CarSpatialIndex,",
    "    CarSpawnOrigin,",
    "    RespawnRequest,",
    "    _build_lane_buckets,",
    "    _frame_car_spatial,",
    "    _lane_peers_for,",
    "    _resolve_all_shell_overlaps,",
    ")",
    "from pathwise.pedestrian import Pedestrian",
    "from pathwise import traffic_spawn",
    "from analytics.perf_profiler import PerfProfiler, perf_profile_enabled",
    "",
    "ENABLE_PERF_PROFILE = perf_profile_enabled()",
    "perf_profiler = PerfProfiler(enabled=ENABLE_PERF_PROFILE)",
    "",
]

# After head: skip old config (62-180), keep helper funcs 181-368 (serialize_lights ends ~367)
# Old indices 0-based: 61:180 config, 180:368 helpers before CarSpawnOrigin
helpers = lines[180:368]

# Skip car block 370-3133 (index 369:3133), pedestrian 3135-3154, spawn 3176-3670
# Keep from _load_prior_session area - line 3156 def _load_prior_session
mid_start = 3155  # 0-based index for line 3156
mid_end = 3175  # before _rect_overlap_area
mid = lines[mid_start:mid_end]

# Per-round state starts at old line 3671 -> index 3670
tail = lines[3670:]

out = head + NEW_IMPORTS + helpers + mid + tail
MAIN.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"main.py: {len(lines)} -> {len(out)} lines")
