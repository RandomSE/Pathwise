"""Tests for variable speed zones modifier."""

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
from pathwise.modifiers import highway, variable_speed_zones
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestVariableSpeedZonesRegistry(unittest.TestCase):
    def test_bit_is_sixty_four(self):
        self.assertEqual(
            modifier_mask_from_ids(frozenset({"variable_speed_zones"})), 64
        )
        self.assertEqual(
            modifier_ids_from_mask(64), frozenset({"variable_speed_zones"})
        )
        self.assertTrue(is_valid_modifier_mask(64))
        self.assertTrue(is_valid_modifier_mask(32 | 64))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            222222, "normal", 1, modifiers=frozenset({"variable_speed_zones"})
        )
        self.assertEqual(encoded[3:7], "0064")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"variable_speed_zones"}))

    def test_compatible_with_highway_and_time_pressure(self):
        self.assertFalse(
            modifier_is_blocked("variable_speed_zones", frozenset({"highway"}))
        )
        self.assertFalse(
            modifier_is_blocked("variable_speed_zones", frozenset({"time_pressure"}))
        )
        self.assertTrue(is_valid_modifier_mask(32 | 64))
        self.assertTrue(is_valid_modifier_mask(16 | 64))


class TestVariableSpeedZonesPolicy(unittest.TestCase):
    def tearDown(self):
        variable_speed_zones.install_for_round(ModifierContext(frozenset()))
        highway.install_for_round(ModifierContext(frozenset()))

    def test_inactive_mult_is_one(self):
        variable_speed_zones.install_for_round(ModifierContext(frozenset()))
        difficulty = DifficultyProfile.for_menu_preset("easy")
        m = highway.generate_highway_map(
            seed=1, difficulty=difficulty, preset_id="easy"
        )
        road = m.roads[0]
        self.assertEqual(
            variable_speed_zones.speed_mult_for_pose(
                road, road_index=0, x=road.rect.centerx, y=road.rect.centery
            ),
            1.0,
        )

    def test_highway_bands_produce_multiple_speeds(self):
        ctx = ModifierContext(
            frozenset({"variable_speed_zones", "highway"}),
            session_base_seed=99,
            round_index=1,
        )
        variable_speed_zones.install_for_round(ctx)
        highway.install_for_round(ctx, preset_id="normal")
        difficulty = DifficultyProfile.for_menu_preset("normal")
        m = highway.generate_highway_map(
            seed=99, difficulty=difficulty, preset_id="normal"
        )
        road = m.roads[0]
        mults = {
            variable_speed_zones.speed_mult_for_pose(
                road,
                road_index=0,
                x=road.rect.left + int(road.rect.width * frac),
                y=road.rect.centery,
            )
            for frac in (0.1, 0.5, 0.9)
        }
        self.assertGreaterEqual(len(mults), 2)
        table = variable_speed_zones.zone_mults_for_road(0)
        self.assertEqual(len(table), 3)
        self.assertEqual(set(table), set(variable_speed_zones.ZONE_MULT_POOL))

    def test_zone_table_is_seed_stable(self):
        ctx = ModifierContext(
            frozenset({"variable_speed_zones"}),
            session_base_seed=42,
            round_index=2,
        )
        variable_speed_zones.install_for_round(ctx)
        a = variable_speed_zones.zone_mults_for_road(0)
        variable_speed_zones.install_for_round(ctx)
        b = variable_speed_zones.zone_mults_for_road(0)
        self.assertEqual(a, b)

    def test_band_rects_cover_highway_width(self):
        difficulty = DifficultyProfile.for_menu_preset("easy")
        m = highway.generate_highway_map(
            seed=3, difficulty=difficulty, preset_id="easy"
        )
        road = m.roads[0]
        bands = [
            variable_speed_zones.band_rect_for_road(road, i) for i in range(3)
        ]
        self.assertEqual(bands[0].left, road.rect.left)
        self.assertEqual(bands[-1].right, road.rect.right)
        self.assertEqual(sum(b.width for b in bands), road.rect.width)


if __name__ == "__main__":
    unittest.main()
