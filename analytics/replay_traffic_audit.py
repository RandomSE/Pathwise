"""
Headless traffic audit: spectate metrics + custom replay checks per seed.

Example:
  python -m analytics.replay_traffic_audit --seed 215728416 --seconds 60
  python -m analytics.replay_traffic_audit --battery --output baseline_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from analytics.spectate_analyzer import SpectateTracker
from analytics.spectate_round import SIM_DT_S, SyntheticClock, autopilot_keys
from analytics.traffic_lights import FORBIDDEN_PERPENDICULAR_PAIRS, perpendicular_pair_legal
from map_generation.difficulty import DifficultyProfile
from pathwise.geom import Rect, collide
from pathwise.input_keys import KeyState
from pathwise.session_seed import SEED_SOURCE_MENU

REQUIRED_ZERO_KINDS = (
    "shell_overlap",
    "intersection_gridlock",
    "spawn_in_lane_ahead",
)

DIAG_ZERO_KINDS = (
    "proximity_streak",
    "wide_turn_sweep",
    "shell_collision",
    "cross_stall",
    "multi_rotation",
)

CUSTOM_ZERO_KINDS = (
    "red_advance_in_intersection",
    "forbidden_perpendicular_light_pair_visible",
)


@dataclass
class CustomTrafficObserver:
    red_advance_events: list[dict[str, Any]] = field(default_factory=list)
    forbidden_pair_events: list[dict[str, Any]] = field(default_factory=list)
    _last_center: dict[int, tuple[int, int]] = field(default_factory=dict)

    def observe(
        self,
        *,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
        road_states: list,
        road_states_for_car=None,
    ) -> None:
        for car in cars:
            if not car.alive():
                continue
            states = (
                road_states_for_car(car)
                if road_states_for_car is not None
                else road_states
            )
            self._observe_red_advance(
                frame, sim_t, [car], intersection_zones, states
            )
        self._observe_forbidden_pairs(frame, sim_t, road_states)

    def _observe_red_advance(
        self,
        frame: int,
        sim_t: float,
        cars: list,
        intersection_zones: list[Rect],
        road_states: list,
    ) -> None:
        if not intersection_zones:
            return
        for car in cars:
            if not car.alive():
                continue
            if not any(collide(z, car.rect) for z in intersection_zones):
                continue
            if float(getattr(car, "current_speed", 0.0)) < 0.5:
                continue
            center = (int(car.rect.centerx), int(car.rect.centery))
            prev = self._last_center.get(int(getattr(car, "spawn_id", 0)))
            self._last_center[int(getattr(car, "spawn_id", 0))] = center
            if prev is not None:
                moved = ((center[0] - prev[0]) ** 2 + (center[1] - prev[1]) ** 2) ** 0.5
                if moved < 0.5:
                    continue
            light = car._straight_light_at_approach(road_states)
            if light not in ("red", "yellow"):
                continue
            if light == "yellow":
                approach = car._approach_state_for_signal(road_states)
                zone = next((z for z in intersection_zones if collide(z, car.rect)), None)
                if (
                    approach is not None
                    and zone is not None
                    and car._can_clear_signal_in_time(approach, zone)
                ):
                    continue
            self.red_advance_events.append(
                {
                    "frame": frame,
                    "sim_t": round(sim_t, 3),
                    "spawn_id": int(getattr(car, "spawn_id", 0)),
                    "light": light,
                    "speed": round(float(car.current_speed), 2),
                    "phase": "none",
                }
            )

    def _observe_forbidden_pairs(
        self, frame: int, sim_t: float, road_states: list
    ) -> None:
        by_offset: dict[float, dict[str, str]] = {}
        for state in road_states:
            key = round(float(state.get("phase_offset", 0.0)), 4)
            bucket = by_offset.setdefault(key, {})
            bucket[state["direction"]] = state.get("light_state", "green")
        for offset, arms in by_offset.items():
            if "vertical" not in arms or "horizontal" not in arms:
                continue
            pair = (arms["vertical"], arms["horizontal"])
            if not perpendicular_pair_legal(*pair):
                self.forbidden_pair_events.append(
                    {
                        "frame": frame,
                        "sim_t": round(sim_t, 3),
                        "phase_offset": offset,
                        "vertical": pair[0],
                        "horizontal": pair[1],
                    }
                )

    def summary(self) -> dict[str, Any]:
        return {
            "red_advance_in_intersection": len(self.red_advance_events),
            "forbidden_perpendicular_light_pair_visible": len(
                self.forbidden_pair_events
            ),
            "red_advance_samples": self.red_advance_events[:5],
            "forbidden_pair_samples": self.forbidden_pair_events[:5],
        }


def _load_diag_counts(path: str) -> dict[str, int]:
    if not os.path.isfile(path):
        return {}
    by_kind: dict[str, int] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "anomaly":
                continue
            kind = str(row.get("kind", "unknown"))
            by_kind[kind] = by_kind.get(kind, 0) + 1
    return by_kind


def run_traffic_audit(
    *,
    seed: int,
    seconds: float = 60.0,
    preset: str = "normal",
    output_dir: str | None = None,
) -> dict[str, Any]:
    import main as game
    from analytics.car_diagnostics import car_diagnostics

    max_frames = max(1, int(seconds / SIM_DT_S))
    out = output_dir or os.path.join("tmp", f"audit_{seed}")
    os.makedirs(out, exist_ok=True)
    os.environ["PATHWISE_CAR_DIAGNOSTICS"] = "1"
    car_diagnostics.path = os.path.join(out, "traffic_events.jsonl")
    car_diagnostics.begin_session(session_seed=seed)

    game.session_base_seed = seed
    game.session_seed_source = SEED_SOURCE_MENU
    game.session_use_adaptive_map = False
    game.session_num_rounds = 1
    game.app_running = True
    game.round_results = []

    clock = SyntheticClock(t=1_000_000.0, dt=SIM_DT_S)
    tracker = SpectateTracker()
    custom = CustomTrafficObserver()
    profile = DifficultyProfile.for_menu_preset(preset)

    sim_frames = 0

    def _observe_pre_separation(car_list) -> None:
        elapsed = clock.t - 1_000_000.0
        tracker.observe_pre_separation(
            frame=sim_frames,
            sim_t=elapsed,
            cars=car_list,
            intersection_zones=game.intersection_zones,
        )

    def _road_states_for_car(car):
        oriented = game._oriented_road_states_for_car(car)
        return game._road_states_for_car(car, oriented)

    with patch.object(game.time, "time", clock.now), patch.object(
        game, "player_hits_any_car", lambda *a, **k: False
    ):
        game.start_round(1, profile, preset)
        if game.current_map is not None:
            game.current_map.goal_rect.x = -5000
        while game.round_active and sim_frames < max_frames:
            keys = autopilot_keys(game)
            game.update_round_frame(keys, before_shell_separation=_observe_pre_separation)
            clock.advance()
            sim_frames += 1
            elapsed = clock.t - 1_000_000.0
            cars = game.cars.sprites()
            tracker.observe(
                frame=sim_frames,
                sim_t=elapsed,
                cars=cars,
                intersection_zones=game.intersection_zones,
                road_states_for_car=_road_states_for_car,
            )
            custom.observe(
                frame=sim_frames,
                sim_t=elapsed,
                cars=cars,
                intersection_zones=game.intersection_zones,
                road_states=game.road_states,
                road_states_for_car=_road_states_for_car,
            )
        if game.round_active:
            game.end_round(False, timed_out=True)

    spectate_metrics = tracker.summary_dict()
    custom_summary = custom.summary()
    diag_by_kind = _load_diag_counts(car_diagnostics.path)

    return {
        "seed": seed,
        "sim_frames": sim_frames,
        "seconds": round(sim_frames * SIM_DT_S, 2),
        "anomaly_count": spectate_metrics.get("anomaly_count", 0),
        "by_kind": spectate_metrics.get("by_kind", {}),
        "custom": custom_summary,
        "diagnostics_by_kind": diag_by_kind,
        "forbidden_pairs_reference": sorted(FORBIDDEN_PERPENDICULAR_PAIRS),
    }


def run_battery(
    seeds: tuple[int, ...],
    *,
    seconds: float = 60.0,
    output_path: str,
) -> dict[str, Any]:
    results = []
    for seed in seeds:
        results.append(run_traffic_audit(seed=seed, seconds=seconds))
    report = {
        "seconds_per_seed": seconds,
        "seed_count": len(seeds),
        "seeds": list(seeds),
        "results": results,
        "totals": {
            "anomaly_count": sum(r["anomaly_count"] for r in results),
            "custom": {
                kind: sum(r["custom"].get(kind, 0) for r in results)
                for kind in CUSTOM_ZERO_KINDS
            },
        },
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return report


def main(argv: list[str] | None = None) -> int:
    from tests.fixtures.traffic_seed_battery import BASELINE_SEEDS

    parser = argparse.ArgumentParser(description="Traffic audit for one seed or battery.")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--battery", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    if args.battery:
        out = args.output or "baseline_report.json"
        report = run_battery(BASELINE_SEEDS, seconds=args.seconds, output_path=out)
        print(json.dumps(report["totals"], indent=2))
        return 0

    if args.seed is None:
        parser.error("--seed is required unless --battery is set")
    result = run_traffic_audit(seed=args.seed, seconds=args.seconds)
    out = args.output or os.path.join("tmp", f"audit_{args.seed}.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
