"""Tests for High speed modifier (2x sim scale)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import high_speed, highway, variable_speed_zones
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestHighSpeedRegistry(unittest.TestCase):
    def test_bit_is_two_fifty_six(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"high_speed"})), 256)
        self.assertEqual(modifier_ids_from_mask(256), frozenset({"high_speed"}))
        self.assertTrue(is_valid_modifier_mask(256))
        self.assertTrue(is_valid_modifier_mask(32 | 64 | 256))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            333333, "hard", 1, modifiers=frozenset({"high_speed"})
        )
        self.assertEqual(encoded[3:7], "0256")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"high_speed"}))


class TestHighSpeedPolicy(unittest.TestCase):
    def tearDown(self):
        high_speed.install_for_round(ModifierContext(frozenset()))
        variable_speed_zones.install_for_round(ModifierContext(frozenset()))
        highway.install_for_round(ModifierContext(frozenset()))

    def test_inactive_scale_is_one(self):
        high_speed.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(high_speed.time_scale(), 1.0)
        self.assertEqual(high_speed.frame_steps(), 1)

    def test_active_scale_is_two(self):
        high_speed.install_for_round(ModifierContext(frozenset({"high_speed"})))
        self.assertEqual(high_speed.time_scale(), 2.0)
        self.assertEqual(high_speed.car_speed_scale(), 2.0)
        self.assertEqual(high_speed.frame_steps(), 2)

    def test_multiplies_with_highway_rain_and_zones(self):
        ctx = ModifierContext(
            frozenset({"high_speed", "highway", "rainy_roads", "variable_speed_zones"}),
            session_base_seed=7,
            round_index=1,
        )
        high_speed.install_for_round(ctx)
        highway.install_for_round(ctx, preset_id="normal")
        variable_speed_zones.install_for_round(ctx)
        # Car composition: base * highway.rain * zone * high_speed.car (1.5 on highway)
        composed = (
            1.0
            * highway.car_speed_mult()
            * 1.35
            * high_speed.car_speed_scale()
        )
        self.assertAlmostEqual(composed, (2.0 / 3.0) * 1.35 * 1.5, places=5)
        self.assertEqual(high_speed.time_scale(), 2.0)


if __name__ == "__main__":
    unittest.main()
