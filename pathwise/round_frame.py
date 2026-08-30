"""Per-frame simulation step for an active round."""

from __future__ import annotations

import time

from pathwise import sprites
from pathwise import traffic_spawn
from pathwise import viewport as game_viewport
from pathwise.car import (
    _build_lane_buckets,
    _frame_car_list_scratch,
    _frame_car_spatial,
    _frame_draw_sprites_scratch,
    _frame_lane_scratch,
    _frame_nearby_scratch,
    _frame_player_car_scratch,
    _fleet_has_shell_overlap,
    _lane_peers_for,
    _resolve_all_shell_overlaps,
)
from pathwise.crosswalk_rules import (
    car_is_traffic_threat,
    car_shares_crossing_plane,
    cars_on_crossing_plane,
    cars_should_respect_player,
    crosswalk_crossing_is_legal,
    is_car_approaching_player,
    player_conflicting_car_vertical,
    player_crossing_cars_have_red,
    player_feet_fully_on_road,
    player_jaywalking_off_crosswalk,
    player_hits_any_car,
    player_mostly_on_legal_crosswalk,
    road_midline_crossed,
    should_honk_at_player_precomputed,
    update_legal_crossing_commit,
)
from pathwise.car_viewport import (
    _cap_cars_near_player,
    _cars_for_replay,
    _cars_near_player,
    _replay_view_rect_for_camera,
    _view_rect_for_camera,
)
from pathwise.geom import collide, contains_rect
from pathwise.input_keys import KeyState, key_labels_from_state
from pathwise.road_states import (
    _oriented_road_states_for_car,
    _road_states_for_car,
    get_player_light_state,
    update_light_timers,
)
from pathwise.round_session import end_round, record_risk, sync_spawn_state_from_runtime, _perf_counter_snapshot
from pathwise.modifiers import exposure, hidden, high_speed, highway, ignored, lag, lawless, old, rainy_roads, time_pressure
from pathwise.sprint import sprint_risk_reason
from analytics.car_diagnostics import car_diagnostics
import pathwise.sim_constants as sim_tuning
from pathwise.sim_constants import *  # noqa: F403



def _game():
    import main
    return main


_MAX_WALL_DT_S = 0.25

_CAR_UPDATE_BRANCH_KEYS = (
    "branch_cruise",
    "branch_far_skip",
    "branch_far_cruise_tick",
    "branch_near_skip",
    "branch_near_cruise_tick",
    "branch_full_update",
)


def _empty_car_update_branches() -> dict[str, int]:
    return {key: 0 for key in _CAR_UPDATE_BRANCH_KEYS}


def _cheap_offscreen_motion(car, m) -> None:
    """Keep far/mid-ring cars moving on skip frames without full AI."""
    car._spawn_age += 1
    signed = car.current_speed * car.direction
    if signed == 0:
        return
    next_rect = car.rect.copy()
    if car.vertical:
        next_rect.y += int(signed)
    else:
        next_rect.x += int(signed)
    move_blocked = False
    zones = m.intersection_zones
    if zones:
        margin = (
            IX_QUERY_PAD
            + max(car.rect.width, car.rect.height)
            + abs(int(signed))
            + 8
        )
        if car._near_intersection_bbox(zones, margin=margin):
            oriented = _oriented_road_states_for_car(car)
            states = _road_states_for_car(car, oriented)
            if car._intersection_entry_blocked(
                next_rect,
                states,
                zones,
                [],
                [],
            ):
                move_blocked = True
            elif car._intersection_advance_blocked_on_red(next_rect, states, zones):
                move_blocked = True
            elif car._crosswalk_advance_blocked(next_rect, states, zones):
                move_blocked = True
    if move_blocked:
        car.current_speed = 0.0
        car.speed = 0.0
    else:
        car.rect = next_rect
    car._sync_collision_shell()
    _frame_car_spatial.relocate_car(car)


def _cruise_car(car, m, lane_buckets, lane_scratch, player_body) -> None:
    _lane_peers_for(car, lane_buckets, lane_scratch)
    car.straight_cruise_update(
        _road_states_for_car(car, _oriented_road_states_for_car(car)),
        m.world_bounds,
        lane_scratch,
        m.round_frame,
        m.current_map.roads,
        m.intersection_zones,
        player_body,
    )
    _frame_car_spatial.relocate_car(car)


def _car_can_straight_cruise(car, in_intersection: bool, in_active_turn: bool, zones) -> bool:
    return (
        not in_intersection
        and not in_active_turn
        and car._turn_phase == "none"
        and car.turn_signal == 0
        and car.current_speed >= 0.4
        and not car._approaching_or_in_intersection(zones)
    )


def _strided_offscreen_tick(
    car, m, stride: int, lane_buckets, lane_scratch, player_body
) -> bool:
    """True when this frame ran cruise; False when it used cheap skip motion."""
    if (m.round_frame + car.spawn_id) % max(1, int(stride)) != 0:
        _cheap_offscreen_motion(car, m)
        return False
    _cruise_car(car, m, lane_buckets, lane_scratch, player_body)
    return True


def update_round_frame(keys: KeyState, *, before_shell_separation=None):
    """Advance simulation one frame; returns draw kwargs when the round is still active."""
    m = _game()
    frame_t0 = time.perf_counter()
    if not m.round_active:
        return None
    vp_w, vp_h = game_viewport.sim_viewport_size()
    wall_now = time.time()
    last = getattr(m, "_sim_clock_last", None)
    if last is None:
        m.sim_elapsed = 0.0
        m._sim_clock_last = wall_now
        last = wall_now
    wall_dt = min(max(0.0, wall_now - float(last)), _MAX_WALL_DT_S)
    m._sim_clock_last = wall_now
    phys = lag.begin_frame(wall_dt)
    m.sim_elapsed = float(getattr(m, "sim_elapsed", 0.0)) + wall_dt * high_speed.time_scale()
    elapsed = m.sim_elapsed
    time_left = max(0, m.ROUND_TIME_LIMIT - elapsed)

    fatal_tick = old.update_fatal_trip(elapsed)
    if fatal_tick == "fail":
        end_round(False, timed_out=False, reason="trip")
        return None

    previous_pos = m.player.rect.topleft

    with m.perf_profiler.section("lights_and_crossings"):
        for state in m.road_states:
            state["player_waiting"] = False
            road_rect = state["road_rect"]
            crosswalk = state["crosswalk"]
            wait_zone = crosswalk.inflate(80, 80)
            if collide(wait_zone, m.player.rect) and not collide(road_rect, m.player.rect):
                state["player_waiting"] = True
        update_light_timers(m.road_states, elapsed)

        for road_index, road in enumerate(m.current_map.roads):
            approach_zone = road.rect.inflate(120, 120)
            if not road.crossed and collide(approach_zone, m.player.rect):
                m.decision_logger.note_road_approach(road_index)

    with m.perf_profiler.section("traffic_spawns"):
        spawn_steps = max(1, int(round(high_speed.frame_steps() * phys)))
        for _ in range(spawn_steps):
            traffic_spawn._process_traffic_spawns_through_frame(
                m.round_frame,
                m.current_map.roads,
                m.cars,
                m.all_sprites,
                m.intersection_zones,
                m.player.rect,
                getattr(m.current_map, "city_blocks", None),
                m.world_bounds,
            )
            m.round_frame += 1
        sync_spawn_state_from_runtime()
    traffic_spawn.set_round_frame_getter(lambda: m.round_frame)

    with m.perf_profiler.section("player_update"):
        move_prev_center = m.player_prev_center
        m.player.update(keys, elapsed=elapsed)
        if not contains_rect(m.world_bounds, m.player.rect):
            m.player.rect.topleft = previous_pos

        curr_center = (m.player.rect.centerx, m.player.rect.centery)
        player_moved_this_frame = move_prev_center != curr_center
        if m.rain_slip_tracker is not None:
            if m.player.sprint_enabled and player_moved_this_frame:
                m.rain_slip_tracker.note_sprint_activity(elapsed)
            slipped = m.rain_slip_tracker.update(elapsed, m.player)
            if slipped and old.trip_is_fatal():
                old.begin_fatal_trip(elapsed)
        for road_index, road in enumerate(m.current_map.roads):
            if road.crossed:
                continue
            if not road_midline_crossed(move_prev_center, curr_center, road):
                continue
            if not collide(road.rect, m.player.rect):
                continue
            m.crossings += 1
            road.crossed = True
            light_at = get_player_light_state(m.player.rect, m.road_states)
            crossing_tier = None
            time_bonus_s = None
            if time_pressure.is_active():
                body = sprites.player_body_hitbox(m.player.rect)
                on_crosswalk = any(
                    collide(state["crosswalk"], body) for state in m.road_states
                )
                cars_have_red = player_crossing_cars_have_red(body, m.road_states)
                legal = time_pressure.legal_crossing_for_bonus(
                    on_crosswalk=on_crosswalk,
                    cars_have_red=cars_have_red,
                    legal_commit_active=m.legal_crossing_commit_active,
                    unsignalized=lawless.is_active(),
                )
                crossing_tier = time_pressure.classify_crossing(
                    on_crosswalk=on_crosswalk, legal_crossing=legal
                )
                time_bonus_s = time_pressure.apply_crossing_bonus(
                    crossing_tier, elapsed=elapsed
                )
                time_bonus_s *= old.time_bonus_mult()
                if time_bonus_s > 0:
                    m.ROUND_TIME_LIMIT = time_pressure.clamp_timer_limit(
                        m.ROUND_TIME_LIMIT + time_bonus_s,
                        elapsed=elapsed,
                        extra_mult=old.time_bonus_mult(),
                    )
                    exposure.grant_from_time_bonus(time_bonus_s)
            m.decision_logger.note_road_crossed(
                road_index,
                light_at,
                crossing_tier=crossing_tier,
                time_bonus_s=time_bonus_s,
            )
        m.player_prev_center = curr_center

    with m.perf_profiler.section("player_context"):
        player_body = sprites.player_body_hitbox(m.player.rect)
        player_on_crosswalk = any(
            collide(state["crosswalk"], player_body) for state in m.road_states
        )
        player_on_road = any(
            collide(road.rect, player_body) for road in m.current_map.roads
        )
        player_feet_road = player_feet_fully_on_road(m.player.rect, m.current_map.roads)
        player_mostly_legal = player_mostly_on_legal_crosswalk(player_body, m.road_states)
        player_on_car_red = player_crossing_cars_have_red(player_body, m.road_states)
        unsignalized = lawless.is_active()
        m.legal_crossing_commit_active = update_legal_crossing_commit(
            m.legal_crossing_commit_active,
            player_on_crosswalk,
            player_on_car_red,
            on_road=player_on_road,
            unsignalized=unsignalized,
        )
        legal_crosswalk_crossing = crosswalk_crossing_is_legal(
            player_on_car_red, m.legal_crossing_commit_active
        )
        if unsignalized and player_on_crosswalk and m.legal_crossing_commit_active:
            player_mostly_legal = True
        conflict_car_vertical = player_conflicting_car_vertical(
            player_body, m.road_states, m.current_map.roads
        )
        if unsignalized:
            ped_legal_crossing = player_on_crosswalk and legal_crosswalk_crossing
            respect_basis = legal_crosswalk_crossing
        else:
            ped_legal_crossing = player_on_crosswalk and player_on_car_red
            respect_basis = player_on_car_red
        respect_player = cars_should_respect_player(
            player_on_road, player_on_crosswalk, respect_basis
        )
        if rainy_roads.should_disable_player_yield(
            slip_stunned=m.player.is_slip_stunned(elapsed)
        ) or ignored.should_disable_player_yield() or highway.should_disable_player_yield():
            respect_player = False
        honk_allowed = should_honk_at_player_precomputed(
            player_feet_road,
            player_mostly_legal,
            player_on_crosswalk,
            player_on_car_red,
        )
        if ignored.should_suppress_honk():
            honk_allowed = False
        player_body_block = player_body.inflate(4, 4)

        if m.player.sprint_enabled and player_moved_this_frame:
            sprint_reason = sprint_risk_reason(
                sprinting=True,
                moved=True,
                feet_on_road=player_feet_road,
                on_crosswalk=player_on_crosswalk,
            )
            if sprint_reason:
                record_risk(sprint_reason, tier="risky", cooldown=0.75)

    camera_offset = game_viewport.camera_offset_for(
        m.player.rect.centerx, m.player.rect.centery, vp_w, vp_h
    )
    view_rect = _view_rect_for_camera(camera_offset, vp_w, vp_h)
    replay_view = _replay_view_rect_for_camera(camera_offset, vp_w, vp_h)
    sim_view = view_rect.inflate(SIM_UPDATE_VIEW_PAD, SIM_UPDATE_VIEW_PAD)

    car_list = m.cars.sprites_into(_frame_car_list_scratch)
    with m.perf_profiler.section("cars_spatial"):
        _frame_car_spatial.rebuild(car_list)
        lane_buckets = _build_lane_buckets(car_list)
    move_scratch = _frame_nearby_scratch
    lane_scratch = _frame_lane_scratch
    with m.perf_profiler.section("cars_update"):
        branches = _empty_car_update_branches()
        m.car_update_branches = branches
        far_stride = max(1, int(sim_tuning.OFFSCREEN_FAR_STRIDE))
        near_stride = max(
            1,
            int(
                getattr(
                    sim_tuning,
                    "OFFSCREEN_NEAR_STRIDE",
                    sim_tuning.OFFSCREEN_UPDATE_STRIDE,
                )
            ),
        )
        for car in car_list:
            if not car.alive():
                continue
            in_intersection = bool(m.intersection_zones) and car._rect_in_intersection(
                car.rect, m.intersection_zones
            )
            in_active_turn = (
                car._turn_phase in ("to_hub", "turning", "settling")
                or car.turn_signal != 0
            )
            in_sim_view = collide(sim_view, car._collision_shell)
            in_camera_view = collide(view_rect, car._collision_shell)
            # Far offscreen: stride cruise only, never full Car.update.
            # Turns still use full AI so offscreen turn state does not stall.
            if not in_active_turn and not in_sim_view:
                cruised = _strided_offscreen_tick(
                    car, m, far_stride, lane_buckets, lane_scratch, player_body
                )
                if cruised:
                    branches["branch_far_cruise_tick"] += 1
                else:
                    branches["branch_far_skip"] += 1
                continue
            can_cruise = _car_can_straight_cruise(
                car, in_intersection, in_active_turn, m.intersection_zones
            )
            # Mid-ring (outside camera, inside sim pad): cheap cruise path.
            # Fairness: near-but-offscreen cars update less often than in-view.
            # Approaching / turning / in-ix cars still take full AI below.
            if not in_camera_view and in_sim_view and can_cruise:
                cruised = _strided_offscreen_tick(
                    car, m, near_stride, lane_buckets, lane_scratch, player_body
                )
                if cruised:
                    branches["branch_near_cruise_tick"] += 1
                else:
                    branches["branch_near_skip"] += 1
                continue
            if can_cruise:
                _cruise_car(car, m, lane_buckets, lane_scratch, player_body)
                branches["branch_cruise"] += 1
                continue
            _lane_peers_for(car, lane_buckets, lane_scratch)
            peer_pad = 72 if car._turn_phase == "none" and car.turn_signal == 0 else IX_QUERY_PAD
            peer_query = car._collision_shell
            move_peers = _frame_car_spatial.nearby(
                peer_query, peer_pad, move_scratch
            )
            car._frame_move_peers = move_peers
            car.update(
                _road_states_for_car(
                    car, _oriented_road_states_for_car(car)
                ),
                m.world_bounds,
                m.intersection_zones,
                player_body,
                m.current_map.roads,
                lane_scratch,
                move_peers,
                m.round_frame,
                player_on_road,
                player_on_crosswalk,
                player_feet_road,
                ped_legal_crossing,
                respect_player,
                honk_allowed
                and car_shares_crossing_plane(car, conflict_car_vertical),
                player_body_block,
                elapsed,
            )
            _frame_car_spatial.relocate_car(car)
            branches["branch_full_update"] += 1

    with m.perf_profiler.section("car_shell_separation"):
        if before_shell_separation is not None:
            before_shell_separation(car_list)
        sep_stride = max(1, sim_tuning.SHELL_SEP_EVERY_N_FRAMES)
        small_fleet = len(car_list) <= sim_tuning.SHELL_SEP_FLEET_THRESHOLD
        if m.round_frame % sep_stride == 0 or small_fleet:
            _resolve_all_shell_overlaps(
                car_list, _frame_car_spatial, _frame_nearby_scratch
            )
            # Second overlap scan is O(fleet); keep it for small fleets only.
            if small_fleet and _fleet_has_shell_overlap(
                car_list, _frame_car_spatial, _frame_nearby_scratch
            ):
                _resolve_all_shell_overlaps(
                    car_list, _frame_car_spatial, _frame_nearby_scratch
                )

    with m.perf_profiler.section("car_diagnostics"):
        if ENABLE_CAR_DIAGNOSTICS:
            player_center = player_body.center
            for car in car_list:
                if not car.alive():
                    continue
                car_diagnostics.observe(
                    car,
                    game_time=elapsed,
                    round_frame=m.round_frame,
                    intersection_zones=m.intersection_zones,
                    move_peers=car._frame_move_peers or (),
                    player_center=player_center,
                )

    with m.perf_profiler.section("risk_checks"):
        near_player_cars = _cars_near_player(
            player_body, _frame_car_spatial, _frame_player_car_scratch
        )
        draw_cars = _cap_cars_near_player(
            car_list,
            view_rect,
            player_body.center,
            MAX_DRAW_RECORD_CARS,
        )
        draw_sprites = _frame_draw_sprites_scratch
        draw_sprites.clear()
        draw_sprites.extend(draw_cars)
        draw_sprites.append(m.player)

        for car in car_list:
            if not car.honk_risk_pending:
                continue
            if not car_shares_crossing_plane(car, conflict_car_vertical):
                car.honk_risk_pending = False
                continue
            honk_reason = car.honk_reason or "honk"
            honk_tier = "risky"
            if (time.time() - m.last_risk_time) > 0.85:
                m.risky_risk_events += 1
                m.risk_events += 1
                m.last_risk_time = time.time()
            m.decision_logger._record(
                "car_honk",
                reason=honk_reason,
                risk=f"car_honk_{honk_reason}",
                risk_tier=honk_tier,
            )
            car.honk_risk_pending = False
        same_plane_near = cars_on_crossing_plane(near_player_cars, conflict_car_vertical)
        nearby_fast_cars = [
            car
            for car in same_plane_near
            if collide(car._collision_shell.inflate(170, 170), player_body)
            and car.current_speed > car.base_speed * 0.65
        ]
        approaching_cars = [
            car
            for car in same_plane_near
            if is_car_approaching_player(car, m.player.rect)
        ]

        if (
            not legal_crosswalk_crossing
            and player_feet_road
            and not player_on_crosswalk
            and nearby_fast_cars
        ):
            record_risk("fast_traffic_on_road", tier="risky")
        if highway.should_emit_highway_crossing_risk(
            on_road=player_feet_road,
            moved=player_moved_this_frame,
        ):
            record_risk("highway_crossing", tier="reasonable", cooldown=0.75)
        elif (
            player_moved_this_frame
            and player_feet_road
            and not legal_crosswalk_crossing
            and (
                (
                    unsignalized
                    and not player_on_crosswalk
                )
                or (
                    not unsignalized
                    and player_jaywalking_off_crosswalk(
                        player_body, m.road_states, on_crosswalk=player_on_crosswalk
                    )
                )
            )
        ):
            record_risk("road_jaywalk", tier="reasonable", cooldown=0.75)
        crosswalk_light = get_player_light_state(m.player.rect, m.road_states)
        if (
            highway.should_emit_crosswalk_risks()
            and lawless.should_emit_against_light_risk()
            and player_on_crosswalk
            and not legal_crosswalk_crossing
            and crosswalk_light in ("green", "yellow")
        ):
            record_risk(
                "crosswalk_against_light",
                tier="reasonable",
                cooldown=0.75,
                on_crosswalk=True,
                light=crosswalk_light,
            )
        if (
            highway.should_emit_crosswalk_risks()
            and lawless.should_emit_uncontrolled_crosswalk_risk(
                on_crosswalk=player_on_crosswalk,
                approaching_traffic=bool(approaching_cars),
            )
        ):
            record_risk(
                "uncontrolled_crosswalk_with_traffic",
                tier="reasonable",
                cooldown=0.75,
                on_crosswalk=True,
            )
        unprotected_on_road = highway.is_active() and player_on_road
        if (
            unprotected_on_road
            or player_on_crosswalk
            or (legal_crosswalk_crossing and player_on_road)
        ):
            threatening_cars = [
                car
                for car in approaching_cars
                if car_is_traffic_threat(car)
            ]

            if (unprotected_on_road or not legal_crosswalk_crossing) and threatening_cars:
                if any(
                    collide(
                        car._collision_shell.inflate(
                            TOO_CLOSE_DISTANCE, TOO_CLOSE_DISTANCE
                        ),
                        player_body,
                    )
                    for car in same_plane_near
                ):
                    record_risk("vehicle_too_close", tier="risky", cooldown=0.7)
                if any(
                    collide(
                        car._collision_shell.inflate(
                            NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE
                        ),
                        player_body,
                    )
                    and car_is_traffic_threat(car, min_speed_frac=0.75)
                    for car in same_plane_near
                ):
                    record_risk("near_miss", tier="risky")

    with m.perf_profiler.section("decision_logger"):
        m.decision_logger.update(
            player_body.center,
            key_labels_from_state(keys),
            player_on_crosswalk,
            player_on_road,
            get_player_light_state(m.player.rect, m.road_states),
            False,
        )

    with m.perf_profiler.section("frame_recorder"):
        m.frame_recorder.note_sim_frame_seconds(time.perf_counter() - frame_t0)
        needs_replay_cars = (
            not m.frame_recorder.frames or m.frame_recorder.wants_capture(elapsed)
        )
        replay_cars = (
            _cars_for_replay(car_list, player_body.center) if needs_replay_cars else ()
        )
        if not m.frame_recorder.frames:
            m.frame_recorder.capture_start(
                elapsed, m.player.rect, replay_cars, m.road_states, game_time=elapsed
            )
        elif needs_replay_cars:
            m.frame_recorder.capture(
                elapsed, m.player.rect, replay_cars, m.road_states, game_time=elapsed
            )

    with m.perf_profiler.section("round_end_checks"):
        if old.is_fatal_trip_active():
            # Preserve the trip fail sequence; do not swap to collision/timeout.
            pass
        elif player_hits_any_car(
            m.player, m.cars, spatial=_frame_car_spatial, scratch=_frame_player_car_scratch
        ):
            end_round(True, timed_out=False)
        elif collide(m.player.rect, m.current_map.goal_rect):
            end_round(False, timed_out=False)
        elif exposure.tick(on_road=player_on_road, elapsed=elapsed):
            end_round(False, timed_out=True, reason="exposure")
        elif time_left <= 0 and m.round_active:
            end_round(False, timed_out=True)

    if not m.round_active:
        return None

    esc = (
        getattr(m.current_difficulty_profile, "round_escalation", 0.0)
        if m.current_difficulty_profile
        else 0.0
    )
    route_crossings = getattr(m.current_map, "route_crossings", None)
    crossing_total = (
        route_crossings if route_crossings is not None else len(m.current_map.roads)
    )
    # Assessment chrome (route / risks / crossings / traffic / intensity) is
    # recruiter-facing; candidates only need timer, sprint, and live signals.
    show_assessment_hud = getattr(m, "session_audience", "candidate") == "recruiter"
    hud_lines = [
        f"Time left: {time_left:05.1f}s",
    ]
    if show_assessment_hud:
        hud_lines.insert(
            0,
            f"Round {m.current_round_index}/{m.session_num_rounds} · "
            f"intensity {esc * 100:.0f}%",
        )
        hud_lines.append(
            f"Crossings: {m.crossings}/{crossing_total} · "
            f"traffic {sum(1 for c in car_list if c.alive())} "
            f"({len(draw_cars)} on screen)",
        )
        gen_meta = getattr(m.current_map, "generation_meta", None) or {}
        spawn_edge = gen_meta.get("spawn_edge")
        goal_edge = gen_meta.get("goal_edge")
        if spawn_edge and goal_edge:
            # Keep Route under Round/intensity and above Time left.
            hud_lines.insert(
                1,
                f"Route: spawn {spawn_edge} → goal {goal_edge}",
            )
    hud_lines.append(
        f"Sprint: {'ON' if m.player.sprint_enabled else 'OFF'} (Shift)"
    )
    if player_on_crosswalk:
        if lawless.is_active():
            commit = "committed" if m.legal_crossing_commit_active else "entering"
            hud_lines.append(f"Crosswalk · lawless ({commit})")
        else:
            car_light = "red" if player_on_car_red else "green"
            if m.legal_crossing_commit_active and not player_on_car_red:
                car_light = "green (legal commit)"
            hud_lines.append(f"Crosswalk · cars: {car_light}")
    if show_assessment_hud and m.reasonable_risk_events + m.risky_risk_events > 0:
        hud_lines.append(
            f"Risks: {m.reasonable_risk_events} reasonable · {m.risky_risk_events} risky"
        )
    if getattr(m.session_modifiers, "has", lambda _id: False)("rainy_roads"):
        hud_lines.append("Weather: Rainy roads")
    if getattr(m.session_modifiers, "has", lambda _id: False)("lawless"):
        hud_lines.append("Signals: Unsignalized (lawless)")
    if getattr(m.session_modifiers, "has", lambda _id: False)("time_pressure"):
        last = time_pressure.last_bonus_seconds()
        if time_pressure.rain_combo_active():
            label = "Time pressure + rain"
        else:
            label = "Time pressure"
        if last > 0:
            hud_lines.append(
                f"{label}: +{last:.1f}s ({time_pressure.last_bonus_tier()})"
            )
        else:
            start = int(time_pressure.start_seconds())
            hud_lines.append(f"{label}: earn time by crossing (start {start}s)")
    exposure_hud = exposure.hud_line()
    if exposure_hud is not None:
        hud_lines.append(exposure_hud)
    if high_speed.is_active():
        if highway.is_active():
            hud_lines.append(
                f"High speed: {high_speed.TIME_SCALE:.0f}x "
                f"(cars {high_speed.HIGHWAY_CAR_SCALE:g}x on highway)"
            )
        else:
            hud_lines.append(f"High speed: {high_speed.TIME_SCALE:.0f}x")
    lag_hud = lag.hud_line()
    if lag_hud is not None:
        hud_lines.append(lag_hud)
    old_hud = old.hud_line()
    if old_hud is not None:
        hud_lines.append(old_hud)
    if m.ENABLE_PERF_PROFILE:
        hud_lines.append(f"Perf log: {m.perf_profiler.jsonl_path}")
    if hidden.suppress_hud():
        hud_lines = []
    counters = _perf_counter_snapshot(
        car_list=car_list,
        replay_cars=draw_cars,
        draw_sprites=draw_sprites,
    )
    counters.update(getattr(m, "car_update_branches", _empty_car_update_branches()))
    m.perf_profiler.finish_update(
        round_frame=m.round_frame,
        elapsed_s=elapsed,
        counters=counters,
    )
    return {
        "camera_offset": camera_offset,
        "view_rect": view_rect,
        "record_cars": draw_cars,
        "draw_sprites": draw_sprites,
        "elapsed": elapsed,
        "hud_lines": hud_lines,
        "draw_weather": getattr(m.session_modifiers, "has", lambda _id: False)("rainy_roads"),
    }


def draw_round_frame(
    window_width: int,
    window_height: int,
    draw_state: dict,
    *,
    display_layout=None,
) -> None:
    m = _game()
    from pathwise.game_draw import draw_round_scene

    draw_round_scene(
        window_width,
        window_height,
        current_map=m.current_map,
        player=m.player,
        world_bounds=m.world_bounds,
        road_states=m.road_states,
        wall_rects=m.wall_rects,
        draw_sprites=draw_state["draw_sprites"],
        record_cars=draw_state["record_cars"],
        camera_offset=draw_state["camera_offset"],
        view_rect=draw_state["view_rect"],
        elapsed=draw_state["elapsed"],
        hud_lines=draw_state["hud_lines"],
        light_green_duration=m._LIGHT_GREEN,
        draw_traffic_timer_bar=TRAFFIC_DRAW_TIMER_BAR,
        display_layout=display_layout,
        draw_weather=draw_state.get("draw_weather", False),
    )
