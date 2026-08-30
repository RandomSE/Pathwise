"""Live-loop proof that curb arrival writes commit_latency_s.

These tests drive start_round + update_round_frame (the same path as
pathwise/round_frame.py), not unit-constructed DecisionLogger calls and
not session_simulator policies.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from analytics.spectate_round import SyntheticClock
from analytics.trait_scoring import FLAG_OK, score_session
from map_generation.difficulty import DifficultyProfile
from pathwise.geom import collide
from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
from pathwise.round_session import finalize_round_result


LIVE_SEED = 17
BATTERY_SEEDS = (17, 42, 99, 777)
CURB_WAIT_FRAMES = 18
CROSS_BUDGET_FRAMES = 420
APPROACH_WALK_FRAMES = 80


def _place_player(game, xy: tuple[float, float]) -> None:
    game.player.rect.center = (int(xy[0]), int(xy[1]))
    game.player_prev_center = (game.player.rect.centerx, game.player.rect.centery)


def _clear_cars(game) -> None:
    for car in list(game.cars):
        car.kill()


def _nearest_uncrossed_road(game):
    px, py = game.player.rect.centerx, game.player.rect.centery
    best = None
    best_d = None
    for index, road in enumerate(game.current_map.roads):
        if road.crossed:
            continue
        cx, cy = road.rect.centerx, road.rect.centery
        dist = abs(cx - px) + abs(cy - py)
        if best_d is None or dist < best_d:
            best = (index, road)
            best_d = dist
    return best


def _curb_stand_point(road, player_center: tuple[int, int]) -> tuple[int, int]:
    """Stand just off the road on the player's current side of the midline."""
    pad = 20
    if road.direction == "vertical":
        x = road.rect.centerx
        if player_center[1] <= road.rect.centery:
            return (x, road.rect.top - pad)
        return (x, road.rect.bottom + pad)
    y = road.rect.centery
    if player_center[0] <= road.rect.centerx:
        return (road.rect.left - pad, y)
    return (road.rect.right + pad, y)


def _approach_stand_point(road, curb_xy: tuple[int, int]) -> tuple[int, int]:
    """Farther off-road than the curb, still inside the 120px approach inflate."""
    extra = 70
    if road.direction == "vertical":
        if curb_xy[1] < road.rect.centery:
            return (curb_xy[0], curb_xy[1] - extra)
        return (curb_xy[0], curb_xy[1] + extra)
    if curb_xy[0] < road.rect.centerx:
        return (curb_xy[0] - extra, curb_xy[1])
    return (curb_xy[0] + extra, curb_xy[1])


def _keys_toward(px: int, py: int, tx: int, ty: int) -> KeyState:
    keys = KeyState()
    dx, dy = tx - px, ty - py
    if abs(dx) >= abs(dy):
        if dx > 1:
            keys.press(KEY_RIGHT)
        elif dx < -1:
            keys.press(KEY_LEFT)
    else:
        if dy > 1:
            keys.press(KEY_DOWN)
        elif dy < -1:
            keys.press(KEY_UP)
    return keys


def _keys_across(road, player_center: tuple[int, int]) -> KeyState:
    keys = KeyState()
    if road.direction == "vertical":
        if player_center[1] <= road.rect.centery:
            keys.press(KEY_DOWN)
        else:
            keys.press(KEY_UP)
    else:
        if player_center[0] <= road.rect.centerx:
            keys.press(KEY_RIGHT)
        else:
            keys.press(KEY_LEFT)
    return keys


def _configure(game, seed: int) -> None:
    game.session_base_seed = seed
    game.session_seed_source = "test"
    game.session_use_adaptive_map = False
    game.session_num_rounds = 1
    game.app_running = True
    game.round_results = []
    game.round_active = False


def _start_live_round(game, seed: int, clock: SyntheticClock):
    _configure(game, seed)
    profile = DifficultyProfile.for_menu_preset("normal")
    game.start_round(1, profile, "normal")
    _clear_cars(game)
    return game


def _run_wait_then_cross(game, clock: SyntheticClock, *, from_approach: bool) -> dict:
    """Approach (optional), wait at curb, then walk across one road."""
    found = _nearest_uncrossed_road(game)
    if found is None:
        raise AssertionError("live map has no uncrossed road")
    road_index, road = found
    spawn = (game.player.rect.centerx, game.player.rect.centery)
    curb_xy = _curb_stand_point(road, spawn)
    if from_approach:
        _place_player(game, _approach_stand_point(road, curb_xy))
        for _ in range(APPROACH_WALK_FRAMES):
            if not game.round_active:
                break
            px, py = game.player.rect.centerx, game.player.rect.centery
            game.update_round_frame(_keys_toward(px, py, curb_xy[0], curb_xy[1]))
            clock.advance()
            if collide(road.rect.inflate(56, 56), game.player.rect) and not collide(
                road.rect, game.player.rect
            ):
                break
    else:
        _place_player(game, curb_xy)

    for _ in range(CURB_WAIT_FRAMES):
        if not game.round_active:
            break
        game.update_round_frame(KeyState())
        clock.advance()

    before = game.crossings
    for _ in range(CROSS_BUDGET_FRAMES):
        if not game.round_active:
            break
        if game.crossings > before:
            break
        center = (game.player.rect.centerx, game.player.rect.centery)
        game.update_round_frame(_keys_across(road, center))
        clock.advance()

    if game.round_active:
        game.end_round(False, timed_out=True)
    finalize_round_result()
    session = game.round_results[-1]["session"]
    session["_harness_road_index"] = road_index
    return session


def _arrive_curb_roads(session: dict) -> set:
    return {
        item.get("road_index")
        for item in session.get("decision_sequence") or []
        if item.get("action") == "arrive_curb"
    }


def _residual_used_after_curb(session: dict) -> list[dict]:
    """Attempts that had arrive_curb for that road but no commit_latency_s."""
    logged = _arrive_curb_roads(session)
    bad = []
    for attempt in session.get("crossing_attempts") or []:
        road = attempt.get("road_index")
        if road in logged and attempt.get("commit_latency_s") is None:
            bad.append(attempt)
    return bad


class TestLiveCurbArrivalLoop(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game

    def test_wait_at_curb_then_cross_writes_commit_latency(self):
        clock = SyntheticClock(t=8_000_000.0, dt=1 / 60)
        with patch.object(self.game.time, "time", clock.now):
            _start_live_round(self.game, LIVE_SEED, clock)
            session = _run_wait_then_cross(self.game, clock, from_approach=True)

        self.assertGreater(session["crossings"], 0)
        self.assertIn("arrive_curb", [d.get("action") for d in session["decision_sequence"]])
        after_curb = [
            a
            for a in session["crossing_attempts"]
            if a.get("road_index") in _arrive_curb_roads(session)
        ]
        self.assertTrue(after_curb, "expected a crossing after recorded curb arrival")
        for attempt in after_curb:
            self.assertIsNotNone(
                attempt.get("commit_latency_s"),
                f"live commit missing latency: {attempt}",
            )
        self.assertFalse(_residual_used_after_curb(session))

        scored = score_session(session)
        self.assertEqual(scored["trait_flags"]["decision_tempo"], FLAG_OK)
        self.assertEqual(scored["signal_sources"]["decision_tempo"], "commit_latency_s")
        counts = scored["signal_sources"]["decision_tempo_live_counts"]
        self.assertGreaterEqual(counts["n_commit_latency"], 1)
        self.assertEqual(counts["n_residual"], 0)

    def test_battery_residual_is_rare_when_curb_was_logged(self):
        n_commit = 0
        n_residual = 0
        n_insufficient = 0
        n_after_curb = 0
        for seed in BATTERY_SEEDS:
            clock = SyntheticClock(t=9_000_000.0 + seed, dt=1 / 60)
            with patch.object(self.game.time, "time", clock.now):
                _start_live_round(self.game, seed, clock)
                session = _run_wait_then_cross(self.game, clock, from_approach=False)
            scored = score_session(session)
            counts = scored["signal_sources"]["decision_tempo_live_counts"]
            n_commit += counts["n_commit_latency"]
            n_residual += counts["n_residual"]
            n_insufficient += counts["n_insufficient"]
            after_curb = [
                a
                for a in session.get("crossing_attempts") or []
                if a.get("road_index") in _arrive_curb_roads(session)
            ]
            n_after_curb += len(after_curb)
            self.assertFalse(
                _residual_used_after_curb(session),
                f"seed {seed} used residual after logged curb arrival",
            )
            for attempt in after_curb:
                self.assertIsNotNone(attempt.get("commit_latency_s"))

        self.assertGreaterEqual(n_after_curb, len(BATTERY_SEEDS))
        self.assertGreaterEqual(n_commit, len(BATTERY_SEEDS))
        self.assertEqual(
            n_residual,
            0,
            f"residual used after curb wait battery "
            f"commit={n_commit} residual={n_residual} insufficient={n_insufficient}",
        )


if __name__ == "__main__":
    unittest.main()
