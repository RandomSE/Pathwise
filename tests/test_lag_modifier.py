"""Tests for Lag modifier and High speed highway car scale."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import high_speed, highway, lag
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestLagRegistry(unittest.TestCase):
    def test_bit_is_five_twelve(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"lag"})), 512)
        self.assertEqual(modifier_ids_from_mask(512), frozenset({"lag"}))
        self.assertTrue(is_valid_modifier_mask(512))
        self.assertTrue(is_valid_modifier_mask(256 | 512))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            444444, "normal", 1, modifiers=frozenset({"lag"})
        )
        self.assertEqual(encoded[3:7], "0512")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"lag"}))


class TestLagPhysicsScale(unittest.TestCase):
    def tearDown(self):
        lag.install_for_round(ModifierContext(frozenset()))

    def test_inactive_physics_scale_is_one(self):
        lag.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(lag.begin_frame(0.1), 1.0)
        self.assertEqual(lag.physics_scale(), 1.0)
        self.assertEqual(lag.target_fps(), 60.0)

    def test_active_rescales_to_sixty_hz_budget(self):
        lag.install_for_round(ModifierContext(frozenset({"lag"})))
        self.assertEqual(lag.target_fps(), 10.0)
        # One 10 FPS frame (~0.1s) should apply six 60Hz frame budgets.
        self.assertAlmostEqual(lag.begin_frame(0.1), 6.0, places=5)
        self.assertAlmostEqual(lag.physics_scale(), 6.0, places=5)
        # Wall-timer path stays wall_dt based: 60s * scale on elapsed is unchanged.
        # (sim uses wall_dt * high_speed only; lag does not shrink the clock.)


class TestHighSpeedHighwayCarScale(unittest.TestCase):
    def tearDown(self):
        high_speed.install_for_round(ModifierContext(frozenset()))
        highway.install_for_round(ModifierContext(frozenset()))

    def test_highway_cars_use_one_point_five(self):
        ctx = ModifierContext(frozenset({"high_speed", "highway"}))
        high_speed.install_for_round(ctx)
        highway.install_for_round(ctx, preset_id="hard")
        self.assertEqual(high_speed.time_scale(), 2.0)
        self.assertEqual(high_speed.car_speed_scale(), 1.5)

    def test_non_highway_cars_use_two(self):
        high_speed.install_for_round(ModifierContext(frozenset({"high_speed"})))
        highway.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(high_speed.car_speed_scale(), 2.0)


if __name__ == "__main__":
    unittest.main()
