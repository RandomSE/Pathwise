"""Tests for Exposure modifier (cumulative on-road time budget)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_is_blocked,
    modifier_mask_from_ids,
)
from pathwise.modifiers import exposure, time_pressure
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestExposureRegistry(unittest.TestCase):
    def test_bit_is_one_twenty_eight(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"exposure"})), 128)
        self.assertEqual(modifier_ids_from_mask(128), frozenset({"exposure"}))
        self.assertTrue(is_valid_modifier_mask(128))
        self.assertTrue(is_valid_modifier_mask(16 | 128))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            111111, "normal", 1, modifiers=frozenset({"exposure"})
        )
        self.assertEqual(encoded[3:7], "0128")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"exposure"}))

    def test_conflicts_with_highway_not_time_pressure(self):
        self.assertTrue(modifier_is_blocked("exposure", frozenset({"highway"})))
        self.assertTrue(modifier_is_blocked("highway", frozenset({"exposure"})))
        self.assertFalse(modifier_is_blocked("exposure", frozenset({"time_pressure"})))
        self.assertFalse(is_valid_modifier_mask(32 | 128))
        self.assertTrue(is_valid_modifier_mask(16 | 128))


class TestExposurePolicy(unittest.TestCase):
    def tearDown(self):
        exposure.install_for_round(ModifierContext(frozenset()))
        time_pressure.install_for_round(ModifierContext(frozenset()))

    def test_inactive_never_exhausts(self):
        exposure.install_for_round(ModifierContext(frozenset()), round_time_limit=60)
        self.assertFalse(exposure.tick(on_road=True, elapsed=1.0))
        self.assertFalse(exposure.tick(on_road=True, elapsed=100.0))
        self.assertIsNone(exposure.hud_line())

    def test_budget_is_half_round_timer(self):
        exposure.install_for_round(
            ModifierContext(frozenset({"exposure"})),
            round_time_limit=80.0,
        )
        self.assertEqual(exposure.limit_seconds(), 40.0)
        self.assertEqual(exposure.remaining_seconds(), 40.0)
        self.assertIn("Exposure:", exposure.hud_line() or "")

    def test_on_road_time_burns_budget(self):
        exposure.install_for_round(
            ModifierContext(frozenset({"exposure"})),
            round_time_limit=10.0,
        )
        self.assertEqual(exposure.limit_seconds(), 5.0)
        self.assertFalse(exposure.tick(on_road=True, elapsed=0.0))
        self.assertFalse(exposure.tick(on_road=True, elapsed=2.0))
        self.assertAlmostEqual(exposure.spent_seconds(), 2.0, places=3)
        self.assertAlmostEqual(exposure.remaining_seconds(), 3.0, places=3)
        # Off-road time does not burn.
        self.assertFalse(exposure.tick(on_road=False, elapsed=4.0))
        self.assertAlmostEqual(exposure.spent_seconds(), 2.0, places=3)
        self.assertTrue(exposure.tick(on_road=True, elapsed=8.0))
        self.assertLessEqual(exposure.remaining_seconds(), 0.0)

    def test_time_pressure_bonus_grants_half_to_exposure(self):
        ctx = ModifierContext(frozenset({"exposure", "time_pressure"}))
        time_pressure.install_for_round(ctx, preset_id="normal")
        exposure.install_for_round(ctx, round_time_limit=10.0)
        self.assertEqual(exposure.limit_seconds(), 5.0)
        grant = exposure.grant_from_time_bonus(6.0)
        self.assertEqual(grant, 3.0)
        self.assertEqual(exposure.limit_seconds(), 8.0)

    def test_time_pressure_combo_mask_valid(self):
        mask = modifier_mask_from_ids(frozenset({"exposure", "time_pressure"}))
        self.assertEqual(mask, 16 | 128)
        self.assertTrue(is_valid_modifier_mask(mask))


if __name__ == "__main__":
    unittest.main()
