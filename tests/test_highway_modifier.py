"""Tests for highway modifier (wide unprotected road, conflicts with time pressure)."""

from __future__ import annotations

import unittest

from map_generation.difficulty import DifficultyProfile
from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_is_blocked,
    modifier_mask_from_ids,
)
from pathwise.modifiers import highway
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestHighwayRegistry(unittest.TestCase):
    def test_bit_is_thirty_two(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"highway"})), 32)
        self.assertEqual(modifier_ids_from_mask(32), frozenset({"highway"}))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            444444, "hard", 1, modifiers=frozenset({"highway"})
        )
        self.assertEqual(encoded[3:7], "0032")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"highway"}))

    def test_conflicts_with_time_pressure(self):
        selected = frozenset({"time_pressure"})
        self.assertTrue(modifier_is_blocked("highway", selected))
        self.assertTrue(modifier_is_blocked("time_pressure", frozenset({"highway"})))
        self.assertTrue(modifier_is_blocked("highway", frozenset({"exposure"})))
        self.assertTrue(modifier_is_blocked("exposure", frozenset({"highway"})))
        self.assertFalse(modifier_is_blocked("highway", frozenset({"rainy_roads"})))
        self.assertFalse(is_valid_modifier_mask(16 | 32))
        self.assertFalse(is_valid_modifier_mask(32 | 128))
        self.assertFalse(is_valid_modifier_mask(63))

    def test_combo_mask_without_time_pressure(self):
        mask = modifier_mask_from_ids(
            frozenset(
                {
                    "rainy_roads",
                    "ignored",
                    "untrustworthy",
                    "lawless",
                    "highway",
                }
            )
        )
        self.assertEqual(mask, 47)
        self.assertTrue(is_valid_modifier_mask(47))
        self.assertEqual(
            modifier_ids_from_mask(47),
            frozenset(
                {
                    "rainy_roads",
                    "ignored",
                    "untrustworthy",
                    "lawless",
                    "highway",
                }
            ),
        )


class TestHighwayMapAndPolicy(unittest.TestCase):
    def tearDown(self):
        highway.install_for_round(ModifierContext(frozenset()))

    def test_inactive_keeps_signals_and_crosswalks(self):
        highway.install_for_round(ModifierContext(frozenset()))
        self.assertTrue(highway.signals_enabled())
        self.assertTrue(highway.crosswalks_enabled())
        self.assertIsNone(highway.highway_max_lane_active())
        self.assertFalse(
            highway.should_emit_highway_crossing_risk(on_road=True, moved=True)
        )

    def test_active_disables_signals_and_crosswalk_risks(self):
        highway.install_for_round(
            ModifierContext(frozenset({"highway"}), session_base_seed=1, round_index=1),
            preset_id="normal",
        )
        self.assertTrue(highway.is_active())
        self.assertFalse(highway.signals_enabled())
        self.assertFalse(highway.crosswalks_enabled())
        self.assertFalse(highway.should_emit_crosswalk_risks())
        self.assertEqual(highway.highway_max_lane_active(), 56)
        self.assertEqual(highway.car_speed_mult(), 1.0)
        self.assertEqual(highway.edge_spawn_queue_cap(), 8)
        self.assertTrue(
            highway.should_emit_highway_crossing_risk(on_road=True, moved=True)
        )
        self.assertFalse(
            highway.should_emit_highway_crossing_risk(on_road=True, moved=False)
        )

    def test_map_scales_lanes_and_time_by_difficulty(self):
        difficulty = DifficultyProfile.for_menu_preset("normal")
        easy = highway.generate_highway_map(
            seed=1, difficulty=difficulty, preset_id="easy"
        )
        hard = highway.generate_highway_map(
            seed=1, difficulty=difficulty, preset_id="hard"
        )
        self.assertEqual(len(easy.roads), 1)
        self.assertEqual(easy.n_v, 1)
        self.assertEqual(easy.n_h, 0)
        self.assertEqual(easy.generation_meta["mode"], "highway")
        self.assertEqual(easy.generation_meta["lanes"], 8)
        self.assertEqual(easy.generation_meta["parallel_lanes"], 4)
        self.assertEqual(hard.generation_meta["lanes"], 16)
        self.assertEqual(hard.generation_meta["parallel_lanes"], 8)
        self.assertEqual(easy.roads[0].parallel_lanes, 4)
        self.assertEqual(easy.roads[0].traffic_density_mult, 8.0)
        self.assertEqual(easy.roads[0].opening_fleet, 28)
        self.assertEqual(hard.generation_meta["opening_fleet"], 44)
        self.assertEqual(hard.generation_meta["car_speed_mult"], 1.0)
        self.assertAlmostEqual(hard.generation_meta["rain_speed_mult"], 2.0 / 3.0)
        self.assertLess(easy.roads[0].rect.height, hard.roads[0].rect.height)
        self.assertLess(easy.time_limit, hard.time_limit)
        self.assertEqual(easy.time_limit, 60)
        self.assertEqual(hard.time_limit, 110)
        self.assertGreater(hard.traffic_weights[0], easy.traffic_weights[0])
        self.assertGreater(easy.start_pos[1], easy.roads[0].rect.bottom)
        self.assertLess(easy.goal_rect.centery, easy.roads[0].rect.top)
        # Full map width is asphalt; no walk-around corridors on the left/right.
        road = easy.roads[0]
        bounds = easy.world_bounds_hint
        self.assertEqual(road.rect.left, bounds.left)
        self.assertEqual(road.rect.right, bounds.right)
        self.assertTrue(easy.generation_meta["full_width"])
        self.assertGreater(bounds.height, road.rect.height)

    def test_max_lane_active_scales_with_preset(self):
        for preset, expected in (("easy", 48), ("normal", 56), ("hard", 64)):
            highway.install_for_round(
                ModifierContext(frozenset({"highway"})),
                preset_id=preset,
            )
            self.assertEqual(highway.highway_max_lane_active(), expected)

    def test_inactive_speed_mult_is_one(self):
        highway.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(highway.car_speed_mult(), 1.0)
        self.assertIsNone(highway.edge_spawn_queue_cap())
        self.assertFalse(highway.should_disable_player_yield())
        self.assertEqual(highway.spawn_ramp_frames(), 90)

    def test_highway_rain_combo_slows_cars_by_one_third(self):
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="normal",
        )
        self.assertEqual(highway.car_speed_mult(), 1.0)
        self.assertFalse(highway.rain_combo_active())
        highway.install_for_round(
            ModifierContext(frozenset({"highway", "rainy_roads"})),
            preset_id="normal",
        )
        self.assertTrue(highway.rain_combo_active())
        self.assertAlmostEqual(highway.car_speed_mult(), 2.0 / 3.0)

    def test_highway_does_not_yield_but_still_honks(self):
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="normal",
        )
        self.assertTrue(highway.should_disable_player_yield())
        self.assertTrue(highway.should_skip_player_body_block())
        self.assertEqual(highway.spawn_ramp_frames(), 16)
        from pathwise.modifiers import ignored

        ignored.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(ignored.should_suppress_honk())

    def test_near_player_spawn_gap_and_sides(self):
        from pathwise.geom import Rect
        from pathwise.commonUtils import CAR_WIDTH

        difficulty = DifficultyProfile.for_menu_preset("easy")
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="easy",
        )
        m = highway.generate_highway_map(
            seed=3, difficulty=difficulty, preset_id="easy"
        )
        road = m.roads[0]
        self.assertEqual(highway.near_player_spawn_gap_px(), CAR_WIDTH * 4)
        self.assertEqual(highway.min_vertical_weave_gap_px(), 60)
        mid = Rect(road.rect.centerx - 10, road.rect.centery - 10, 20, 20)
        self.assertFalse(highway.player_at_highway_side(mid, road))
        curb = Rect(road.rect.centerx - 10, road.rect.bottom + 10, 20, 20)
        self.assertTrue(highway.player_at_highway_side(curb, road))

    def test_opening_fleet_respects_vertical_weave_gap(self):
        from map_generation.traffic_schedule import (
            car_pose_for_spawn,
            generate_traffic_schedule,
            _candidate_rect_from_pose,
        )

        difficulty = DifficultyProfile.for_menu_preset("normal")
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="normal",
        )
        m = highway.generate_highway_map(
            seed=7, difficulty=difficulty, preset_id="normal"
        )
        road = m.roads[0]
        sched = generate_traffic_schedule(
            7, m.roads, m.traffic_weights, difficulty, m.time_limit
        )
        opening = [e for e in sched if e.phase == "opening" and e.on_road]
        self.assertGreaterEqual(len(opening), 20)
        min_gap = highway.min_vertical_weave_gap_px()
        rects = []
        for e in opening:
            x, y, _, vertical = car_pose_for_spawn(
                road, e.along_frac, e.direction, lane_index=e.lane_index
            )
            rects.append(_candidate_rect_from_pose(x, y, vertical))
        for i, a in enumerate(rects):
            ax, ay, aw, ah = a
            for b in rects[i + 1 :]:
                bx, by, bw, bh = b
                if ax < bx + bw and ax + aw > bx:
                    vgap = max(by - (ay + ah), ay - (by + bh))
                    self.assertGreaterEqual(
                        vgap,
                        min_gap,
                        msg=f"cars at {a} and {b} leave only {vgap}px vertical gap",
                    )

    def test_highway_vertical_gap_blocked_helper(self):
        from pathwise.geom import Rect
        from pathwise.traffic_spawn import _highway_vertical_gap_blocked

        class _Peer:
            def __init__(self, rect: Rect, vertical: bool = False):
                self.rect = rect
                self.vertical = vertical

        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="normal",
        )
        probe = Rect(100, 100, 60, 30)
        too_close = _Peer(Rect(120, 100 + 30 + 20, 60, 30))  # 20px < 60px
        clear = _Peer(Rect(120, 100 + 30 + 80, 60, 30))  # 80px >= 60px
        offset_x = _Peer(Rect(200, 100, 60, 30))  # no x overlap
        self.assertTrue(_highway_vertical_gap_blocked(probe, False, [too_close]))
        self.assertFalse(_highway_vertical_gap_blocked(probe, False, [clear]))
        self.assertFalse(_highway_vertical_gap_blocked(probe, False, [offset_x]))
        highway.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(_highway_vertical_gap_blocked(probe, False, [too_close]))

    def test_highway_blocks_near_player_ongoing_spawn(self):
        from map_generation.traffic_schedule import TrafficSpawn, PHASE_ONGOING
        from pathwise.geom import Rect
        from pathwise.traffic_spawn import _highway_blocks_near_player_spawn

        difficulty = DifficultyProfile.for_menu_preset("easy")
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="easy",
        )
        m = highway.generate_highway_map(
            seed=3, difficulty=difficulty, preset_id="easy"
        )
        road = m.roads[0]
        player = Rect(road.rect.centerx - 10, road.rect.centery - 10, 20, 20)
        event = TrafficSpawn(
            frame=10,
            road_index=0,
            along_frac=0.5,
            direction=1,
            archetype_index=0,
            event_id=1,
            phase=PHASE_ONGOING,
            lane_index=0,
            on_road=False,
        )
        near_x = player.centerx - 80
        self.assertTrue(
            _highway_blocks_near_player_spawn(
                near_x, road.rect.centery - 15, False, player, road, event
            )
        )
        far_x = player.centerx - 500
        self.assertFalse(
            _highway_blocks_near_player_spawn(
                far_x, road.rect.centery - 15, False, player, road, event
            )
        )
        on_road_event = TrafficSpawn(
            frame=0,
            road_index=0,
            along_frac=0.5,
            direction=1,
            archetype_index=0,
            event_id=2,
            phase="opening",
            lane_index=0,
            on_road=True,
        )
        self.assertFalse(
            _highway_blocks_near_player_spawn(
                near_x, road.rect.centery - 15, False, player, road, on_road_event
            )
        )

    def test_opening_schedule_packs_on_road_fleet(self):
        from map_generation.traffic_schedule import generate_traffic_schedule

        difficulty = DifficultyProfile.for_menu_preset("normal")
        highway.install_for_round(
            ModifierContext(frozenset({"highway"})),
            preset_id="normal",
        )
        m = highway.generate_highway_map(
            seed=7, difficulty=difficulty, preset_id="normal"
        )
        sched = generate_traffic_schedule(
            7, m.roads, m.traffic_weights, difficulty, m.time_limit
        )
        opening = [e for e in sched if e.phase == "opening" and e.on_road]
        self.assertGreaterEqual(len(opening), 30)
        lanes_used = {e.lane_index for e in opening}
        self.assertGreaterEqual(len(lanes_used), 3)

    def test_parallel_lane_centers_are_distinct(self):
        from map_generation.lane_geometry import lane_center_xy

        difficulty = DifficultyProfile.for_menu_preset("easy")
        m = highway.generate_highway_map(
            seed=2, difficulty=difficulty, preset_id="easy"
        )
        road = m.roads[0]
        ys = [
            lane_center_xy(road, 1, lane_index=i)[1]
            for i in range(road.parallel_lanes)
        ]
        self.assertEqual(len(ys), len(set(ys)))
        self.assertGreater(max(ys) - min(ys), 40)


if __name__ == "__main__":
    unittest.main()
