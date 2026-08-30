"""Targeted coverage for modules below the 95% gate."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pathwise.geom import Rect, as_rect, clip_rect, collide, contains_rect
from pathwise.map import Road


class TestGeomExtended(unittest.TestCase):
    def test_rect_copy_constructors(self):
        base = Rect(10, 20, 30, 40)
        copy = Rect(base)
        self.assertEqual(copy, base)
        tup = Rect((5, 6, 7, 8))
        self.assertEqual(tup.topleft, (5, 6))

    def test_collidepoint_and_clamp(self):
        r = Rect(0, 0, 100, 100)
        self.assertTrue(r.collidepoint(50, 50))
        self.assertTrue(r.collidepoint((50, 50)))
        inner = Rect(200, 200, 10, 10)
        inner.clamp_ip(r)
        self.assertLessEqual(inner.right, r.right)
        wide = Rect(150, 10, 80, 20)
        wide.clamp_ip(r)
        self.assertLessEqual(wide.right, r.right)

    def test_as_rect_duck_type(self):
        duck = MagicMock(left=1, top=2, width=3, height=4)
        self.assertEqual(as_rect(duck).width, 3)

    def test_collide_mixed_types(self):
        duck = MagicMock(left=0, top=0, width=50, height=50)
        self.assertTrue(collide(Rect(10, 10, 50, 50), duck))

    def test_contains_and_clip(self):
        outer = Rect(0, 0, 100, 100)
        inner = Rect(10, 10, 20, 20)
        self.assertTrue(contains_rect(outer, inner))
        clipped = clip_rect(Rect(50, 50, 80, 80), outer)
        self.assertLessEqual(clipped.right, outer.right)


class TestEntityGroupExtended(unittest.TestCase):
    def test_remove_and_dead_membership(self):
        from pathwise.entity_group import Entity, EntityGroup

        class E(Entity):
            pass

        a, b = E(), E()
        group = EntityGroup(a)
        group.add(b)
        group.remove(a)
        b.kill()
        self.assertEqual(len(group), 0)
        self.assertNotIn(b, group)


class TestReplayInterpolationExtended(unittest.TestCase):
    def test_empty_and_boundary_frames(self):
        from analytics.replay_interpolation import (
            frame_at_time,
            frame_pair_at_time,
            interpolate_car,
            lerp_replay_frame,
        )

        self.assertEqual(frame_pair_at_time([], 1.0), (0, 0, 0.0))
        frames = [{"t": 0.0, "player": {"x": 0, "y": 0}, "cars": [], "lights": []}]
        self.assertEqual(frame_pair_at_time(frames, -1.0), (0, 0, 0.0))
        self.assertEqual(frame_pair_at_time(frames, 99.0)[0], 0)
        at = frame_at_time(frames, 0.0)
        self.assertEqual(at["t"], 0.0)
        left = {"t": 0, "player": {"x": 0, "y": 0}, "cars": [{"id": 1, "x": 0, "ang": 350, "sp": 1}], "lights": []}
        right = {"t": 1, "player": {"x": 0, "y": 0}, "cars": [{"id": 1, "x": 10, "ang": 10, "sp": 2}], "lights": []}
        car = interpolate_car(left["cars"][0], right["cars"][0], 0.5)
        self.assertIn("ang", car)
        early = lerp_replay_frame(left, right, 0.0)
        late = lerp_replay_frame(left, right, 1.0)
        self.assertEqual(early["t"], left["t"])
        self.assertEqual(late["t"], right["t"])
        left["decision"] = {"action": "cross"}
        left["is_decision"] = True
        mid = lerp_replay_frame(left, right, 0.25, t=0.25)
        self.assertIn("decision", mid)


class TestTrafficLightsExtended(unittest.TestCase):
    def test_zero_cycle_and_normalization(self):
        from analytics.traffic_lights import (
            cycle_durations,
            light_state_at,
            seconds_to_change,
        )

        self.assertEqual(light_state_at(1.0, 0, 0, 0), "green")
        g, y, r = cycle_durations(10.0, green_frac=1, yellow_frac=1, red_frac=1)
        self.assertAlmostEqual(g + y + r, 10.0)
        state, secs, nxt = seconds_to_change(5.0, 0.0, g, y, r)
        self.assertIn(state, ("green", "yellow", "red"))


class TestConstraints(unittest.TestCase):
    def test_roads_fully_connected_and_density(self):
        from map_generation.constraints import (
            road_positions_valid,
            roads_fully_connected,
            traffic_density_balanced,
        )

        v = Road(Rect(100, 0, 40, 400), "vertical")
        h = Road(Rect(0, 200, 400, 40), "horizontal")
        self.assertTrue(roads_fully_connected([v, h]))
        orphan = Road(Rect(0, 0, 40, 40), "vertical")
        self.assertFalse(roads_fully_connected([orphan, h]))
        self.assertTrue(traffic_density_balanced([]))
        self.assertFalse(traffic_density_balanced([0, 1]))
        self.assertTrue(traffic_density_balanced([1, 2]))
        self.assertFalse(road_positions_valid([0, 5], [0, 100], min_gap=10))


class TestTrafficScheduleExtended(unittest.TestCase):
    def test_spawn_poses_and_lane_caps(self):
        from map_generation.difficulty import DifficultyProfile
        from map_generation.traffic_schedule import (
            PHASE_OPENING,
            car_pose_edge_entry,
            car_pose_for_spawn,
            count_lane_cars,
            edge_spawn_lane_allowed,
            entry_along_frac,
            generate_traffic_schedule,
            lane_spawn_allowed,
            spawn_poses_for_event,
            TrafficSpawn,
        )

        v = Road(Rect(80, 0, 60, 500), "vertical")
        h = Road(Rect(0, 220, 500, 60), "horizontal")
        roads = [v, h]
        self.assertLess(entry_along_frac(1), entry_along_frac(-1))
        x, y, d, vert = car_pose_for_spawn(v, 0.5, 1)
        self.assertFalse(vert)
        x2, y2, d2, vert2 = car_pose_edge_entry(h, -1, queue_index=1.0)
        self.assertTrue(vert2)
        import main as game

        car = game.Car(x, y, 3.0, vertical=vert, spawn_id=99, road_index=0)
        self.assertEqual(count_lane_cars([car], v, d), 1)
        self.assertTrue(lane_spawn_allowed([], v, 1, PHASE_OPENING))
        world = Rect(0, 0, 800, 600)
        self.assertTrue(edge_spawn_lane_allowed([], v, 1, world))
        event = TrafficSpawn(0, 0, 0.2, 1, 0, 1, phase=PHASE_OPENING)
        poses = spawn_poses_for_event(v, event, [], world)
        self.assertTrue(len(poses) >= 1)
        schedule = generate_traffic_schedule(42, roads, None, DifficultyProfile.default(), 30)
        self.assertGreater(len(schedule), 0)


class TestArchetypeAndDecisionLogger(unittest.TestCase):
    def test_archetype_scoring_edges(self):
        from analytics.archetype_scoring import score_session

        sess = {
            "outcome": "success",
            "duration_s": 10,
            "time_limit": 30,
            "crossings": 3,
            "risk_events": 0,
            "collisions": 0,
            "decision_marks": [],
        }
        scores = score_session(sess)
        self.assertTrue(scores)
        self.assertIn("hiring_output", scores)
        self.assertEqual(scores["hiring_output"]["kind"], "role_target_similarity")

    def test_decision_logger_risk_split(self):
        from analytics.decision_logger import DecisionLogger

        logger = DecisionLogger((0, 0), (200, 200), "map_test", 4)
        logger.note_risk("near_miss", road_index=1)
        logger.note_road_approach(0)
        logger.note_curb_arrival(0, pos=(40, 0))
        logger.note_road_crossed(0, "green")
        payload = logger.finalize("success", 5.0, 1, 0, 1, "none")
        self.assertIn("decision_sequence", payload)
        self.assertTrue(payload["decision_sequence"])
        attempt = payload["crossing_attempts"][-1]
        self.assertIn("commit_latency_s", attempt)
        self.assertIn("approach_travel_s", attempt)
        self.assertIn("approach_path_px", attempt)
        actions = [item["action"] for item in payload["decision_sequence"]]
        self.assertIn("arrive_curb", actions)
        logger.note_curb_arrival(3, pos=(1, 1))
        logger.note_curb_arrival(0, pos=(2, 2))


class TestPerfProfilerAndFrameRecorder(unittest.TestCase):
    def test_perf_profiler_session(self):
        from analytics.perf_profiler import PerfProfiler

        with tempfile.TemporaryDirectory() as tmp:
            p = PerfProfiler(jsonl_path=str(Path(tmp) / "perf.jsonl"))
            p.begin_session(session_seed=1, seed_source="t", num_rounds=1, preset="normal")
            with p.section("sim"):
                pass
            p.begin_round(1)
            p.finish_draw(0.01)
            p.end_round("success", 1.0)

    def test_frame_recorder_trim_and_densify(self):
        from analytics.frame_recorder import FrameRecorder

        rec = FrameRecorder(28)
        player = Rect(0, 0, 20, 20)
        states = [
            {
                "crosswalk": Rect(0, 0, 40, 12),
                "direction": "horizontal",
                "light_state": "green",
                "turn_light_state": "red",
                "seconds_to_change": 1.0,
                "turn_seconds_to_change": 1.0,
                "next_light": "yellow",
                "next_turn_light": "red",
            }
        ]
        for i in range(400):
            rec.capture(float(i) * 0.1, player, [], states, force=(i == 0))
        rec.densify_frames(max_gap_s=0.5)
        self.assertGreater(len(rec.frames), 0)


class TestPathwiseRender(unittest.TestCase):
    @patch("arcade.draw_lbwh_rectangle_filled")
    def test_sim_draw_helpers(self, _fill):
        from pathwise.pathwise_render import (
            draw_sim_circle_filled,
            draw_sim_rect_filled,
            sim_point_to_arcade,
            sim_rect_to_arcade_lbwh,
        )

        ax, ay = sim_point_to_arcade(100, 200, 600)
        self.assertEqual(ax, 100)
        self.assertEqual(ay, 400)
        lbwh = sim_rect_to_arcade_lbwh(0, 0, 50, 50, 600)
        self.assertEqual(len(lbwh), 4)
        draw_sim_rect_filled(Rect(0, 0, 10, 10), (0, 0), 600, (0, 0, 0))
        with patch("arcade.draw_circle_filled"):
            draw_sim_circle_filled(10, 10, 600, 5, (255, 0, 0))


class TestMainSpawnExtended(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game

    def test_spawn_helpers(self):
        roads = [Road(Rect(0, 0, 90, 400), "vertical")]
        rect, shell = self.game._spawn_probe_geometry(10, 120, False)
        self.assertFalse(self.game._blocks_player_spawn_shell(shell, None))
        player = Rect(100, 100, 20, 20)
        car = self.game.Car(10, 120, 3.0, vertical=False, spawn_id=1, road_index=0)
        car._sync_collision_shell(force=True)
        valid = self.game._car_spawn_pose_valid(car, roads)
        self.assertIsInstance(valid, bool)
        blocks = [{"x": 0, "y": 0, "w": 50, "h": 50}]
        self.assertEqual(len(self.game._city_block_rects_from(blocks)), 1)
        self.assertTrue(
            self.game._spawn_forward_lane_clear(car.rect, car.vertical, car.direction, [])
        )

    def test_player_crosswalk_wrapper(self):
        states = [{"crosswalk": Rect(0, 0, 200, 200), "light_state": "red"}]
        player = Rect(50, 50, 20, 20)
        self.assertTrue(self.game.player_on_car_red_crosswalk(player, states))

    def test_serialize_lights(self):
        import main as game

        profile = __import__(
            "map_generation.difficulty", fromlist=["DifficultyProfile"]
        ).DifficultyProfile.default()
        game.start_round(1, profile, "normal")
        game.update_light_timers(game.road_states, 0.5)
        out = game.serialize_lights_for_frame(game.road_states[:2])
        self.assertEqual(out[0]["s"], "green")

    def test_end_round_perf_profile(self):
        import main as game

        game.session_num_rounds = 1
        game.current_round_index = 1
        profile = __import__(
            "map_generation.difficulty", fromlist=["DifficultyProfile"]
        ).DifficultyProfile.default()
        game.start_round(1, profile, "normal")
        prev = game.ENABLE_PERF_PROFILE
        game.ENABLE_PERF_PROFILE = True
        try:
            game.perf_profiler.begin_session(session_seed=1, seed_source="t", num_rounds=1, preset="normal")
            game.perf_profiler.begin_round(1)
            with patch.object(game, "save_session_log", return_value=None):
                outcome = game.end_round(False, timed_out=True)
                game.finalize_round_result()
            self.assertEqual(outcome, "timeout")
        finally:
            game.ENABLE_PERF_PROFILE = prev


class TestSpectateAutopilot(unittest.TestCase):
    def test_autopilot_keys_branches(self):
        import main as game
        from analytics.spectate_round import autopilot_keys, _session_log_dict
        from map_generation.difficulty import DifficultyProfile

        game.session_base_seed = 1
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        game.player.rect.centerx = 10
        game.player.rect.centery = 10
        keys = autopilot_keys(game)
        self.assertIsNotNone(keys)
        game.player.rect.centerx = game.current_map.goal_rect.centerx
        game.player.rect.centery = game.current_map.goal_rect.centery - 100
        autopilot_keys(game)
        game.round_results = []
        self.assertIsNone(_session_log_dict(game))


if __name__ == "__main__":
    unittest.main()
