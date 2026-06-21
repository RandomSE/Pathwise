"""
Run a full Pathwise round headless with synthetic sim-time and anomaly tracking.

Produces:
  - spectate_log.json      — session log (replay frames + metadata)
  - spectate_report.json   — anomaly timeline + metrics
  - spectate_dashboard.html — accelerated replay viewer (default 8×)

Example:
  python -m analytics.spectate_round --seed 1890416619
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time as wall_time
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from analytics.dashboard import build_dashboard_html
from analytics.spectate_analyzer import SpectateTracker
from map_generation.difficulty import DifficultyProfile
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
from pathwise.session_seed import SEED_SOURCE_MENU


SIM_DT_S = 1.0 / 60.0
DEFAULT_SEED = 1890416619
DEFAULT_PLAYBACK_RATE = 8.0
MAX_SIM_FRAMES = 60 * 120


@dataclass
class SyntheticClock:
    """Advance sim time per frame instead of using wall clock."""

    t: float
    dt: float = SIM_DT_S

    def advance(self) -> float:
        self.t += self.dt
        return self.t

    def now(self) -> float:
        return self.t


def autopilot_keys(game) -> KeyState:
    """Move pedestrian toward goal so the round plays out like a real session."""
    keys = KeyState()
    px, py = game.player.rect.centerx, game.player.rect.centery
    goal = game.current_map.goal_rect
    gx, gy = goal.centerx, goal.centery
    dx, dy = gx - px, gy - py
    if abs(dx) >= abs(dy):
        if dx > 4:
            keys.press(KEY_RIGHT)
        elif dx < -4:
            keys.press(KEY_LEFT)
    else:
        if dy > 4:
            keys.press(KEY_DOWN)
        elif dy < -4:
            keys.press(KEY_UP)
    return keys


def _configure_session(game, seed: int, preset: str) -> None:
    game.session_base_seed = seed
    game.session_seed_source = SEED_SOURCE_MENU
    game.session_use_adaptive_map = False
    game.session_num_rounds = 1
    game.app_running = True
    game.round_results = []


def _session_log_dict(game) -> dict[str, Any] | None:
    if not game.round_results:
        return None
    last = game.round_results[-1]
    return {
        "time": last["duration_s"],
        "crossings": last["crossings"],
        "collisions": last["collisions"],
        "risks_taken": last["risk_events"],
        "failure_reason": last["session"].get("failure_reason"),
        "outcome": last["outcome"],
        "min_crossings": len(last["session"].get("map_layout", {}).get("roads", [])) or 0,
        "avg_time_per_crossing": last["duration_s"] / max(1, last["crossings"]),
        "session": last["session"],
        "archetypes": last["archetypes"],
        "num_rounds": game.session_num_rounds,
        "session_seed": game.session_base_seed,
        "seed_source": game.session_seed_source,
        "pathwise_seed_env": os.environ.get("PATHWISE_SEED"),
        "adaptive_map": game.session_use_adaptive_map,
        "base_difficulty_preset": game.base_preset_id,
        "rounds": game.round_results,
        "spectate": True,
    }


@dataclass
class SpectateResult:
    outcome: str
    duration_s: float
    sim_frames: int
    wall_seconds: float
    session_seed: int
    map_seed: int | None
    report: dict[str, Any]
    log_path: str
    report_path: str
    dashboard_path: str


def run_spectate_round(
    *,
    seed: int = DEFAULT_SEED,
    preset: str = "normal",
    autopilot: bool = True,
    output_dir: str = ".",
    playback_rate: float = DEFAULT_PLAYBACK_RATE,
    max_frames: int = MAX_SIM_FRAMES,
    sample_stride: int = 1,
) -> SpectateResult:
    import main as game
    from analytics.car_diagnostics import car_diagnostics

    os.makedirs(output_dir, exist_ok=True)
    os.environ["PATHWISE_CAR_DIAGNOSTICS"] = "1"
    car_diagnostics.path = os.path.join(output_dir, "traffic_events.jsonl")
    car_diagnostics.begin_session(session_seed=seed)
    _configure_session(game, seed, preset)

    clock = SyntheticClock(t=1_000_000.0, dt=SIM_DT_S)
    tracker = SpectateTracker()
    profile = DifficultyProfile.for_menu_preset(preset)

    wall_t0 = wall_time.perf_counter()
    sim_frames = 0

    def _observe_pre_separation(car_list) -> None:
        elapsed = clock.t - 1_000_000.0
        tracker.observe_pre_separation(
            frame=sim_frames,
            sim_t=elapsed,
            cars=car_list,
            intersection_zones=game.intersection_zones,
        )

    with patch.object(game.time, "time", clock.now):
        game.start_round(1, profile, preset)
        while game.round_active and sim_frames < max_frames:
            keys = autopilot_keys(game) if autopilot else KeyState()
            game.update_round_frame(
                keys, before_shell_separation=_observe_pre_separation
            )
            clock.advance()
            sim_frames += 1

            if sim_frames % sample_stride == 0:
                elapsed = clock.t - 1_000_000.0
                tracker.observe(
                    frame=sim_frames,
                    sim_t=elapsed,
                    cars=game.cars.sprites(),
                    intersection_zones=game.intersection_zones,
                    road_states_for_car=lambda car: game._road_states_for_car(
                        car, game._oriented_road_states_for_car(car)
                    ),
                )

        if game.round_active:
            game.end_round(False, timed_out=True)

    wall_seconds = wall_time.perf_counter() - wall_t0
    log = _session_log_dict(game)
    if log is None:
        raise RuntimeError("Spectate round produced no session log")

    last = game.round_results[-1]
    anomalies = [a.to_dict() for a in tracker.anomalies]
    report = {
        "session_seed": seed,
        "map_seed": log["session"].get("map_seed"),
        "preset": preset,
        "outcome": last["outcome"],
        "duration_s": last["duration_s"],
        "sim_frames": sim_frames,
        "wall_seconds": round(wall_seconds, 3),
        "sim_dt_s": SIM_DT_S,
        "autopilot": autopilot,
        "metrics": tracker.summary_dict(),
        "anomalies": anomalies,
    }

    log_path = os.path.join(output_dir, "spectate_log.json")
    report_path = os.path.join(output_dir, "spectate_report.json")
    dashboard_path = os.path.join(output_dir, "spectate_dashboard.html")

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    build_dashboard_html(
        log_path,
        dashboard_path,
        default_playback_rate=playback_rate,
        spectate_anomalies=anomalies,
        spectate_metrics=tracker.summary_dict(),
    )

    return SpectateResult(
        outcome=last["outcome"],
        duration_s=last["duration_s"],
        sim_frames=sim_frames,
        wall_seconds=wall_seconds,
        session_seed=seed,
        map_seed=log["session"].get("map_seed"),
        report=report,
        log_path=log_path,
        report_path=report_path,
        dashboard_path=dashboard_path,
    )


def format_summary(result: SpectateResult) -> str:
    r = result.report
    lines = [
        f"Spectate seed {result.session_seed} -> {result.outcome} "
        f"({result.duration_s:.2f}s sim, {result.sim_frames} frames, "
        f"{result.wall_seconds:.2f}s wall)",
        (
            f"Anomalies: {r['metrics']['anomaly_count']} "
            f"(overlap_frames={r['metrics']['overlap_frames']}, "
            f"max_pairs={r['metrics']['max_overlap_pairs']}, "
            f"turn_arc_pre={r['metrics'].get('turn_arc_pre_separation_frames', 0)})"
        ),
    ]
    for a in r["anomalies"][:25]:
        lines.append(f"  t={a['sim_t']:6.2f}s  [{a['kind']}]  {a['summary']}")
    if len(r["anomalies"]) > 25:
        lines.append(f"  ... +{len(r['anomalies']) - 25} more (see {result.report_path})")
    lines.append(
        f"Replay: {result.dashboard_path}  (default {DEFAULT_PLAYBACK_RATE:.0f}x speed)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Spectate a synthetic Pathwise round (headless, accelerated replay)."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Session seed (default: {DEFAULT_SEED})",
    )
    parser.add_argument("--preset", default="normal", help="Difficulty preset")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Directory for outputs (default: tmp_spectate/<seed>)",
    )
    parser.add_argument(
        "--playback-rate",
        type=float,
        default=DEFAULT_PLAYBACK_RATE,
        help=f"Default dashboard replay speed (default: {DEFAULT_PLAYBACK_RATE})",
    )
    parser.add_argument(
        "--no-autopilot",
        action="store_true",
        help="Keep player idle (cars-only stress; round usually times out)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=MAX_SIM_FRAMES,
        help="Safety cap on simulated frames",
    )
    args = parser.parse_args(argv)

    os.environ.pop("PATHWISE_PERF_PROFILE", None)
    os.environ.pop("PATHWISE_CAR_DIAGNOSTICS", None)

    output_dir = args.output_dir if args.output_dir is not None else os.path.join("tmp_spectate", str(args.seed))
    result = run_spectate_round(
        seed=args.seed,
        preset=args.preset,
        autopilot=not args.no_autopilot,
        output_dir=output_dir,
        playback_rate=args.playback_rate,
        max_frames=args.max_frames,
    )
    print(format_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
