"""Regression stub: vertical cars must creep to stop line on red, not lock at entry lead band."""
from __future__ import annotations

import unittest

from pathwise.geom import Rect, collide


class TestVerticalEntryLeadBandFreeze(unittest.TestCase):
    def _northbound_setup(self):
        import main as game

        zone = Rect(200, 300, 100, 100)
        crosswalk = Rect(zone.left, zone.bottom + 6, zone.w, 22)
        car = game.Car(zone.centerx, 440, 3.0, vertical=True, spawn_id=101)
        car.direction = -1
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 5.0,
            "direction": "vertical",
            "approach": "south",
            "approach_rect": zone.inflate(180, 180),
        }
        return game, car, zone, state

    def test_northbound_in_entry_lead_band_not_frozen_on_red(self):
        """Creep toward stop line when entry_dist<=48 but not entering the box."""
        game, car, zone, state = self._northbound_setup()
        entry = car._distance_to_intersection_entry(zone)
        stop_axis = car._signal_stop_axis(state["crosswalk"])
        stop_dist = car._distance_to_signal_stop(stop_axis)
        self.assertIsNotNone(entry)
        self.assertLessEqual(entry, 48)
        self.assertGreater(stop_dist, game.STOP_LINE_GAP)
        next_rect = car.rect.copy()
        next_rect.y -= 2
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            ),
            "must allow creep to stop line without entering intersection on red",
        )

    def test_northbound_turn_signal_can_approach_intersection_on_red(self):
        game, car, zone, state = self._northbound_setup()
        car.turn_signal = -1
        car._turn_exit = (0, -1, False)
        next_rect = car.rect.copy()
        next_rect.y -= 2
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )


class TestHorizontalRedApproachDistance(unittest.TestCase):
    def test_westbound_can_creep_within_creep_dist_of_stop_line(self):
        import main as game

        zone = Rect(300, 200, 100, 100)
        crosswalk = Rect(zone.left - 22, zone.top, 22, zone.h)
        car = game.Car(zone.left - 55, zone.centery, 3.0, vertical=False, spawn_id=102)
        car.direction = 1
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 5.0,
            "direction": "horizontal",
            "approach": "west",
            "approach_rect": zone.inflate(180, 180),
        }
        next_rect = car.rect.copy()
        next_rect.x += 2
        self.assertFalse(
            car._intersection_entry_blocked(
                next_rect, [state], [zone], [], []
            )
        )
        blocking: list = []
        speed = car._apply_approach_signal_braking(
            state,
            stop_distance=18.0,
            desired_speed=car.base_speed,
            blocking_controls=blocking,
            brake_dist=game.RED_SIGNAL_BRAKE_DIST,
            creep_dist=game.RED_SIGNAL_CREEP_DIST,
        )
        self.assertGreater(speed, 0.0)


class TestVerticalTurnHeadlessRegression(unittest.TestCase):
    """FU-3: vertical cars creep to stop line on red; no entry-lead band lock."""

    def test_vertical_approach_not_entry_locked_on_seed_332556754(self):
        from unittest.mock import patch

        from analytics.spectate_round import SIM_DT_S, SyntheticClock, autopilot_keys
        from map_generation.difficulty import DifficultyProfile
        from pathwise.session_seed import SEED_SOURCE_MENU

        import main as game

        seed = 332556754
        game.session_base_seed = seed
        game.session_seed_source = SEED_SOURCE_MENU
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []
        clock = SyntheticClock(t=1_000_000.0, dt=SIM_DT_S)
        creep_blocks = 0
        reached_stop_line = 0

        with patch.object(game.time, "time", clock.now):
            game.start_round(1, DifficultyProfile.for_menu_preset("normal"), "normal")
            zones = game.intersection_zones
            for _ in range(240):
                game.update_round_frame(autopilot_keys(game))
                clock.advance()
                for car in game.cars.sprites():
                    if not car.alive() or not car.vertical:
                        continue
                    states = game._road_states_for_car(
                        car, game._oriented_road_states_for_car(car)
                    )
                    appr = car._approach_state_for_signal(states) if states else None
                    if appr is None:
                        continue
                    light = car._effective_approach_light(appr)
                    stop_axis = car._signal_stop_axis(appr["crosswalk"])
                    stop_dist = car._distance_to_signal_stop(stop_axis)
                    ed = min(
                        (
                            d
                            for z in zones
                            if (d := car._distance_to_intersection_entry(z))
                            is not None
                        ),
                        default=None,
                    )
                    if (
                        light == "red"
                        and ed is not None
                        and ed <= 48
                        and 0 < stop_dist <= game.STOP_LINE_GAP + 10
                    ):
                        reached_stop_line += 1
                    if light != "red" or ed is None or ed > 48:
                        continue
                    next_rect = car.rect.copy()
                    step = max(1, int(abs(car.direction) * 2))
                    if car.vertical:
                        next_rect.y += step if car.direction > 0 else -step
                    else:
                        next_rect.x += step if car.direction > 0 else -step
                    if car._intersection_entry_blocked(
                        next_rect, states, zones, [], []
                    ):
                        creep_blocks += 1

        self.assertEqual(
            creep_blocks,
            0,
            "vertical cars must creep toward stop line in entry lead band on red",
        )
        self.assertGreater(
            reached_stop_line,
            0,
            "expected vertical cars to reach the stop line on red",
        )


class TestApproachCrosswalkRelevance(unittest.TestCase):
    def test_southbound_past_intersection_ignores_behind_crosswalk(self):
        import main as game

        zone = Rect(200, 400, 100, 100)
        crosswalk = Rect(zone.left, zone.top - 22, zone.w, 22)
        car = game.Car(zone.centerx, 550, 3.0, vertical=True, spawn_id=201)
        car.direction = 1
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 5.0,
            "direction": "vertical",
            "approach": "north",
            "approach_rect": zone.inflate(180, 180),
        }
        self.assertFalse(car._approach_crosswalk_relevant(crosswalk))

    def test_committed_on_crosswalk_blocked_on_red(self):
        import main as game

        zone = Rect(200, 300, 100, 100)
        crosswalk = Rect(zone.left, zone.bottom + 6, zone.w, 22)
        car = game.Car(zone.centerx, 420, 3.0, vertical=True, spawn_id=202)
        car.direction = -1
        car.rect.top = crosswalk.bottom - 4
        car._sync_collision_shell(force=True)
        stop_axis = car._signal_stop_axis(crosswalk)
        self.assertLess(car._distance_to_signal_stop(stop_axis), 0)
        self.assertTrue(collide(car.rect, crosswalk))
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 5.0,
            "direction": "vertical",
            "approach": "south",
            "approach_rect": zone.inflate(180, 180),
        }
        next_rect = car.rect.copy()
        next_rect.y -= 3
        self.assertTrue(
            car._crosswalk_advance_blocked(next_rect, [state], [zone])
        )


class TestGreenCrosswalkCommitmentHeadless(unittest.TestCase):
    """Seed 332556754: vertical cars idled on crosswalk at green (stop_dist ~ -28)."""

    def test_no_green_crosswalk_freeze_over_90_frames(self):
        from unittest.mock import patch

        from analytics.spectate_round import SIM_DT_S, SyntheticClock, autopilot_keys
        from map_generation.difficulty import DifficultyProfile
        from pathwise.geom import collide
        from pathwise.session_seed import SEED_SOURCE_MENU

        import main as game

        game.session_base_seed = 332556754
        game.session_seed_source = SEED_SOURCE_MENU
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.app_running = True
        game.round_results = []
        clock = SyntheticClock(t=1_000_000.0, dt=SIM_DT_S)
        streak: dict[int, int] = {}
        stuck: list[int] = []

        with patch.object(game.time, "time", clock.now):
            game.start_round(
                1, DifficultyProfile.for_menu_preset("normal"), "normal"
            )
            for _ in range(240):
                game.update_round_frame(autopilot_keys(game))
                clock.advance()
                for car in game.cars.sprites():
                    if not car.alive() or car.current_speed >= 0.15:
                        streak[car.spawn_id] = 0
                        continue
                    oriented = game._oriented_road_states_for_car(car)
                    states = game._road_states_for_car(car, oriented)
                    approach = (
                        car._approach_state_for_signal(states) if states else None
                    )
                    light = (
                        car._effective_approach_light(approach)
                        if approach
                        else None
                    )
                    on_cw = bool(
                        approach and collide(car.rect, approach["crosswalk"])
                    )
                    if light == "green" and on_cw:
                        streak[car.spawn_id] = streak.get(car.spawn_id, 0) + 1
                        if streak[car.spawn_id] >= 90:
                            stuck.append(car.spawn_id)
                    else:
                        streak[car.spawn_id] = 0

        self.assertEqual(
            stuck,
            [],
            f"cars frozen on crosswalk at green: {stuck[:8]}",
        )


if __name__ == "__main__":
    unittest.main()
