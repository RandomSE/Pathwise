"""Round lifecycle: start, end, session logging, and risk recording."""

from __future__ import annotations

import json
import os
import time

from analytics.archetype_scoring import score_session, score_session_log
from analytics.car_diagnostics import car_diagnostics
from analytics.map_snapshot import serialize_map_layout
from analytics.traffic_lights import cycle_durations
from analytics.decision_logger import DecisionLogger
from analytics.frame_recorder import FrameRecorder
from map_generation.difficulty import DifficultyProfile
from map_generation.traffic_schedule import generate_traffic_schedule
from pathwise import map_generator
from pathwise import sprites
from pathwise import traffic_spawn
from pathwise.car import (
    _frame_car_spatial,
    _frame_nearby_scratch,
    set_car_removed_callback,
    set_intersection_zones_shell,
    set_traffic_map_seed,
)
from pathwise.entity_group import EntityGroup
from pathwise.geom import Rect
from pathwise.game_tuning import install_for_round
from pathwise.modifiers.registry import ModifierContext
from pathwise.modifiers import exposure, hidden, high_speed, highway, ignored, lag, lawless, old, rainy_roads, time_pressure, untrustworthy, variable_speed_zones
from pathwise.modifiers.weather_visuals import bake_rainy_road_overlay, install_rain_visuals, reset_rain_visuals
from pathwise.pedestrian import Pedestrian
from pathwise.sim_constants import (
    INTERSECTION_SHELL_PAD,
    LIGHT_CYCLE_SECONDS,
    PEDESTRIAN_SIZE,
    RISK_COOLDOWN_SECONDS,
)
from pathwise.road_states import (
    _build_road_states_by_index,
    build_intersection_zones,
    build_road_states,
)
from pathwise.car_viewport import _cars_for_replay



def _game():
    import main
    return main

def _load_prior_session():
    path = "logs.json"
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("session") or payload
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _map_seed_for_round(session_seed: int, round_index: int) -> int:
    """One session seed; each round gets a stable derived map seed."""
    return (int(session_seed) + round_index * 9973) & 0x7FFFFFFF


def _effective_light_durations(scale: float):
    """Scale full cycle length; preserve 45/10/45 green/yellow/red ratio."""
    cycle = LIGHT_CYCLE_SECONDS * max(0.88, scale)
    return cycle_durations(cycle)


def _apply_difficulty_globals(profile: DifficultyProfile):
    m = _game()
    m.CAR_SPEED_MULT = profile.car_speed_mult
    m.SPAWN_RATE_MULT = profile.spawn_rate_mult
    m.LIGHT_CYCLE_SCALE = profile.light_cycle_scale
    m._LIGHT_GREEN, m._LIGHT_YELLOW, m._LIGHT_RED = _effective_light_durations(m.LIGHT_CYCLE_SCALE)



def start_round(round_index: int, difficulty_profile: DifficultyProfile, preset_id: str):
    m = _game()

    m.current_round_index = round_index
    m.current_difficulty_profile = difficulty_profile
    m.base_preset_id = preset_id
    install_for_round(preset_id, difficulty_profile)
    _apply_difficulty_globals(difficulty_profile)

    modifiers = getattr(m, "session_modifiers", None) or ModifierContext(frozenset())
    modifiers = ModifierContext(
        modifiers.active,
        session_base_seed=m.session_base_seed,
        round_index=round_index,
    )
    m.session_modifiers = modifiers
    rainy_roads.install_for_round(modifiers)
    ignored.install_for_round(modifiers)
    untrustworthy.install_for_round(modifiers)
    lawless.install_for_round(modifiers)
    time_pressure.install_for_round(modifiers, preset_id=preset_id)
    highway.install_for_round(modifiers, preset_id=preset_id)
    variable_speed_zones.install_for_round(modifiers)
    high_speed.install_for_round(modifiers)
    lag.install_for_round(modifiers)
    old.install_for_round(modifiers)
    hidden.install_for_round(
        modifiers,
        audience=getattr(m, "session_audience", "candidate"),
    )
    # exposure installs after ROUND_TIME_LIMIT is known (below)
    if modifiers.has("rainy_roads"):
        install_rain_visuals(session_base_seed=m.session_base_seed, round_index=round_index)
    else:
        reset_rain_visuals()
    m.rain_slip_tracker = rainy_roads.RainSlipTracker() if modifiers.has("rainy_roads") else None

    set_car_removed_callback(traffic_spawn._queue_car_respawn)

    map_seed = _map_seed_for_round(m.session_base_seed, round_index)
    prior_session = _load_prior_session() if m.session_use_adaptive_map else None
    map_difficulty = (
        difficulty_profile.with_adaptive_traffic(prior_session)
        if m.session_use_adaptive_map
        else difficulty_profile
    )

    if modifiers.has("highway"):
        m.current_map = highway.generate_highway_map(
            seed=map_seed,
            difficulty=map_difficulty,
            preset_id=preset_id,
        )
    else:
        m.current_map = map_generator.generate_map(
            seed=map_seed,
            prior_session=None,
            difficulty=map_difficulty,
        )
    m.ROUND_TIME_LIMIT = rainy_roads.scaled_time_limit(m.current_map.time_limit)
    m.ROUND_TIME_LIMIT = time_pressure.initial_time_limit(m.ROUND_TIME_LIMIT)
    m.ROUND_TIME_LIMIT = old.scaled_time_limit(m.ROUND_TIME_LIMIT)
    m.ROUND_TIME_LIMIT = time_pressure.clamp_timer_limit(
        m.ROUND_TIME_LIMIT,
        elapsed=0.0,
        extra_mult=old.time_bonus_mult(),
    )
    exposure.install_for_round(modifiers, round_time_limit=m.ROUND_TIME_LIMIT)

    m.cars = EntityGroup()
    m.player = Pedestrian(m.current_map.start_pos)
    m.player_prev_center = (m.player.rect.centerx, m.player.rect.centery)
    m.all_sprites = EntityGroup(m.player)
    m.start_time = time.time()
    m.sim_elapsed = 0.0
    m._sim_clock_last = m.start_time
    m.crossings = 0
    m.collisions = 0
    m.risk_events = 0
    m.reasonable_risk_events = 0
    m.risky_risk_events = 0
    m.last_risk_time = 0
    m.legal_crossing_commit_active = False
    m.failure_reason = "none"

    m.frame_recorder = FrameRecorder(PEDESTRIAN_SIZE)
    m.decision_logger = DecisionLogger(
        m.current_map.start_pos,
        m.current_map.goal_rect.center,
        m.current_map.map_id,
        len(m.current_map.roads),
        frame_recorder=m.frame_recorder,
        analytics_zones=getattr(m.current_map, "analytics_zones", None),
    )

    hint = getattr(m.current_map, "world_bounds_hint", None)
    m.world_bounds = build_world_bounds(
        m.current_map.roads,
        m.current_map.start_pos,
        m.current_map.goal_rect,
        hint=hint,
    )
    m.road_states = build_road_states(m.current_map.roads)
    m.road_states_h = [s for s in m.road_states if s["direction"] == "horizontal"]
    m.road_states_v = [s for s in m.road_states if s["direction"] == "vertical"]
    m.road_states_by_index = _build_road_states_by_index(m.road_states, len(m.current_map.roads))
    m._round_city_block_rects = traffic_spawn._city_block_rects_from(
        getattr(m.current_map, "city_blocks", None)
    )
    m.intersection_zones = build_intersection_zones(m.current_map.roads)
    m.intersection_zones_shell = [
        zone.inflate(INTERSECTION_SHELL_PAD, INTERSECTION_SHELL_PAD)
        for zone in m.intersection_zones
    ]
    set_intersection_zones_shell(m.intersection_zones_shell)
    m.wall_rects = [
        Rect(m.world_bounds.left - 4000, m.world_bounds.top - 4000, 4000, m.world_bounds.height + 8000),
        Rect(m.world_bounds.right, m.world_bounds.top - 4000, 4000, m.world_bounds.height + 8000),
        Rect(m.world_bounds.left, m.world_bounds.top - 4000, m.world_bounds.width, 4000),
        Rect(m.world_bounds.left, m.world_bounds.bottom, m.world_bounds.width, 4000),
    ]

    m.traffic_map_seed = m.current_map.seed
    set_traffic_map_seed(m.traffic_map_seed)
    weights = getattr(m.current_map, "traffic_weights", None)
    m.traffic_schedule = generate_traffic_schedule(
        m.traffic_map_seed,
        m.current_map.roads,
        weights,
        difficulty_profile,
        m.ROUND_TIME_LIMIT,
    )
    traffic_spawn.reset_spawn_state(m.traffic_schedule)
    traffic_spawn.bind_spawn_runtime(
        car_speed_mult=m.CAR_SPEED_MULT,
        city_block_rects=m._round_city_block_rects,
        frame_car_spatial=_frame_car_spatial,
        frame_nearby_scratch=_frame_nearby_scratch,
        crosswalk_rects=tuple(s["crosswalk"] for s in m.road_states),
    )
    traffic_spawn.set_round_frame_getter(lambda: m.round_frame)
    sync_spawn_state_from_runtime()
    m._ix_rects_cache = None
    m._ix_rects_cache_frame = -1
    m.round_frame = 0

    car_diagnostics.begin_round(
        m.current_round_index,
        session_seed=m.session_base_seed,
        map_seed=getattr(m.current_map, "seed", None),
        traffic_map_seed=m.traffic_map_seed,
    )

    m.round_active = True

    if m.ENABLE_PERF_PROFILE:
        m.perf_profiler.begin_round(
            round_index,
            map_id=str(getattr(m.current_map, "map_id", map_seed)),
            map_seed=map_seed,
            preset=preset_id,
            roads=len(m.current_map.roads),
            time_limit_s=m.ROUND_TIME_LIMIT,
        )

    skip_bake = os.environ.get("PATHWISE_SKIP_MAP_BAKE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not skip_bake:
        m.current_map.bake(
            city_blocks=getattr(m.current_map, "city_blocks", None),
            decorations=getattr(m.current_map, "decorations", None),
            world_bounds=m.world_bounds,
            map_id=str(getattr(m.current_map, "map_id", map_seed)),
            road_states=m.road_states,
        )
    if modifiers.has("rainy_roads") and m.current_map.baked_layer is not None:
        m.current_map.baked_layer = bake_rainy_road_overlay(
            m.current_map.baked_layer,
            road_states=m.road_states,
            session_base_seed=m.session_base_seed,
            round_index=round_index,
        )


def build_world_bounds(roads, start_pos, goal_rect, *, hint=None):
    if hint is not None:
        return Rect(hint.left, hint.top, hint.width, hint.height)
    min_left = min([r.rect.left for r in roads] + [start_pos[0] - 80, goal_rect.left]) - 120
    max_right = max([r.rect.right for r in roads] + [start_pos[0] + 80, goal_rect.right]) + 120
    min_top = min([r.rect.top for r in roads] + [start_pos[1] - 80, goal_rect.top]) - 120
    max_bottom = max([r.rect.bottom for r in roads] + [start_pos[1] + 80, goal_rect.bottom]) + 120
    return Rect(min_left, min_top, max_right - min_left, max_bottom - min_top)


def _perf_counter_snapshot(
    *,
    car_list: list,
    replay_cars: list,
    draw_sprites: list,
) -> dict[str, int | float]:
    m = _game()
    spatial = _frame_car_spatial
    bucket_entries = sum(len(b) for b in spatial._cells.values())
    replay_frames = len(m.frame_recorder.frames) if m.frame_recorder else 0
    decisions = len(m.decision_logger.decisions) if m.decision_logger else 0
    heat_samples = len(m.decision_logger.heat_samples) if m.decision_logger else 0
    return {
        "cars_alive": sum(1 for c in car_list if c.alive()),
        "cars_in_group": len(m.cars),
        "draw_sprites": len(draw_sprites),
        "record_cars": len(replay_cars),
        "cars_in_view": len(replay_cars),
        "replay_frames": replay_frames,
        "decisions": decisions,
        "heat_samples": heat_samples,
        "spawn_retry_queue": len(m.traffic_spawn_retry),
        "spawn_cursor": m.traffic_spawn_cursor,
        "spawn_schedule_len": len(m.traffic_schedule),
        "spatial_cells": len(spatial._cells),
        "spatial_bucket_entries": bucket_entries,
        "road_states": len(m.road_states),
    }


def end_round(collided, timed_out=False, *, reason: str | None = None) -> str:
    m = _game()
    if not m.round_active:
        return m.failure_reason if m.failure_reason != "none" else "collision"

    end_time = time.time()
    duration = round(end_time - m.start_time, 2)
    if collided:
        m.collisions += 1
        m.failure_reason = "collision"
        outcome = "collision"
    elif reason == "trip":
        m.failure_reason = "trip"
        outcome = "trip"
    elif timed_out:
        m.failure_reason = reason or "timeout"
        outcome = "timeout"
    else:
        m.failure_reason = "goal_reached"
        outcome = "success"

    m.round_active = False
    m.round_results.append(
        {
            "round": m.current_round_index,
            "outcome": outcome,
            "duration_s": duration,
            "crossings": m.crossings,
            "collisions": m.collisions,
            "risk_events": m.risk_events,
            "reasonable_risk_events": m.reasonable_risk_events,
            "risky_risk_events": m.risky_risk_events,
            "session": None,
            "archetypes": None,
            "_pending_finalize": True,
        }
    )
    car_diagnostics.end_round()
    print(f"Round {m.current_round_index} complete:", outcome, f"({duration}s)")
    return outcome


def finalize_round_result(*, round_index: int | None = None) -> None:
    """Heavy analytics/replay work deferred until after gameplay UI can transition."""
    m = _game()
    if not m.round_results:
        return
    if round_index is None:
        entry = m.round_results[-1]
    else:
        entry = next((r for r in m.round_results if r["round"] == round_index), None)
        if entry is None:
            return
    if not entry.get("_pending_finalize"):
        return

    outcome = entry["outcome"]
    duration = entry["duration_s"]

    end_cars = _cars_for_replay(
        [c for c in m.cars.sprites() if c.alive()],
        m.player.rect.center,
    )
    m.frame_recorder.capture_end(
        duration, m.player.rect, end_cars, m.road_states, game_time=duration
    )

    session = m.decision_logger.finalize(
        outcome=outcome,
        duration=duration,
        crossings=entry["crossings"],
        collisions=entry["collisions"],
        risk_events=entry["risk_events"],
        reasonable_risk_events=entry["reasonable_risk_events"],
        risky_risk_events=entry["risky_risk_events"],
        failure_reason=m.failure_reason,
    )
    session["replay_capture"] = m.frame_recorder.capture_metadata()
    session["map_layout"] = serialize_map_layout(m.current_map, m.road_states, m.world_bounds)
    session["map_seed"] = getattr(m.current_map, "seed", None)
    session["session_seed"] = m.session_base_seed
    session["time_limit"] = m.ROUND_TIME_LIMIT
    session["difficulty"] = getattr(m.current_map, "difficulty", None)
    session["round_index"] = m.current_round_index
    session["rounds_total"] = m.session_num_rounds
    session["base_preset"] = m.base_preset_id
    session["analytics_zones"] = getattr(m.current_map, "analytics_zones", [])
    session["path_estimate_s"] = getattr(m.current_map, "path_estimate_s", None)
    session["generation_meta"] = getattr(m.current_map, "generation_meta", None)
    session["car_archetypes"] = sprites.serialize_archetypes_for_log()
    modifiers = getattr(m, "session_modifiers", None)
    if modifiers is not None and getattr(modifiers, "active", None) is not None:
        session["modifiers"] = sorted(modifiers.active)
    else:
        session["modifiers"] = []
    if time_pressure.is_active():
        session["time_pressure"] = time_pressure.bonus_summary()
    if exposure.is_active():
        session["exposure"] = exposure.summary()
    archetypes = score_session(session)

    entry["session"] = session
    entry["archetypes"] = archetypes
    entry.pop("_pending_finalize", None)

    if m.ENABLE_PERF_PROFILE:
        report_path = m.perf_profiler.end_round(outcome, duration)
        print(f"Perf log: {m.perf_profiler.jsonl_path}")
        if report_path:
            print(f"Perf report: {report_path}")
        print("Share perf_profile.jsonl + perf_report.html for lag diagnosis.")


def save_session_log():
    m = _game()
    if not m.round_results:
        return None
    finalize_round_result()
    last = m.round_results[-1]
    aggregate = score_session_log(
        {
            "rounds": m.round_results,
            "session": last.get("session") or {},
        }
    )
    log = {
        "time": last["duration_s"],
        "crossings": last["crossings"],
        "collisions": last["collisions"],
        "risks_taken": last["risk_events"],
        "failure_reason": last["session"].get("failure_reason"),
        "outcome": last["outcome"],
        "min_crossings": len(last["session"].get("map_layout", {}).get("roads", [])) or 0,
        "avg_time_per_crossing": last["duration_s"] / max(1, last["crossings"]),
        "session": last["session"],
        "archetypes": aggregate,
        "validity": aggregate["validity"],
        "hiring_output": aggregate["hiring_output"],
        "traits": aggregate["traits"],
        "num_rounds": m.session_num_rounds,
        "session_seed": m.session_base_seed,
        "seed_source": m.session_seed_source,
        "pathwise_seed_env": os.environ.get("PATHWISE_SEED"),
        "adaptive_map": m.session_use_adaptive_map,
        "base_difficulty_preset": m.base_preset_id,
        "candidate_label": getattr(m, "session_candidate_label", None),
        "recruiter_seed_code": getattr(m, "session_recruiter_seed_code", None),
        "session_started_at_utc": getattr(m, "session_started_at_utc", None),
        "rounds": m.round_results,
    }
    with open("logs.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    return _game().build_dashboard_html("logs.json")


def record_risk(reason, tier="risky", cooldown=None, **context):
    m = _game()
    local_cooldown = RISK_COOLDOWN_SECONDS if cooldown is None else cooldown
    if (time.time() - m.last_risk_time) > local_cooldown:
        if tier == "reasonable":
            m.reasonable_risk_events += 1
        else:
            m.risky_risk_events += 1
            m.risk_events += 1
        m.last_risk_time = time.time()
        m.decision_logger.note_risk(reason, tier=tier, **context)


def sync_spawn_state_from_runtime() -> None:
    """Mirror traffic_spawn module state onto main."""
    m = _game()
    m.traffic_schedule = traffic_spawn.traffic_schedule
    m.traffic_spawn_cursor = traffic_spawn.traffic_spawn_cursor
    m.traffic_spawn_retry = traffic_spawn.traffic_spawn_retry
    m.traffic_respawn_pending = traffic_spawn.traffic_respawn_pending
    m.traffic_respawn_event_id = traffic_spawn.traffic_respawn_event_id
