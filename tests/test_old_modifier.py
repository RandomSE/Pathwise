"""Tests for Old modifier (half move, doubled time, fatal rain trip)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import old, rainy_roads, time_pressure
from pathwise.session_seed import (
    ENCODED_SEED_LEN_V9_WIDE,
    decode_recruiter_seed,
    encode_recruiter_seed,
)


class TestOldRegistry(unittest.TestCase):
    def test_bit_is_one_zero_two_four(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"old"})), 1024)
        self.assertEqual(modifier_ids_from_mask(1024), frozenset({"old"}))
        self.assertTrue(is_valid_modifier_mask(1024))
        self.assertTrue(is_valid_modifier_mask(1 | 1024))

    def test_seed_round_trip_wide_mask(self):
        encoded = encode_recruiter_seed(
            555555, "easy", 1, modifiers=frozenset({"old"})
        )
        self.assertEqual(len(encoded), ENCODED_SEED_LEN_V9_WIDE)
        self.assertEqual(encoded[3:7], "1024")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"old"}))


class TestOldPolicy(unittest.TestCase):
    def tearDown(self):
        old.install_for_round(ModifierContext(frozenset()))
        rainy_roads.install_for_round(ModifierContext(frozenset()))
        time_pressure.install_for_round(ModifierContext(frozenset()))

    def test_inactive_defaults(self):
        old.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(old.player_speed_mult(), 1.0)
        self.assertEqual(old.scaled_time_limit(60.0), 60.0)
        self.assertEqual(old.time_bonus_mult(), 1.0)
        self.assertFalse(old.trip_is_fatal())

    def test_half_speed_and_double_time(self):
        old.install_for_round(ModifierContext(frozenset({"old"})))
        self.assertEqual(old.player_speed_mult(), 0.5)
        self.assertEqual(old.scaled_time_limit(60.0), 120.0)
        self.assertEqual(old.time_bonus_mult(), 2.0)
        self.assertFalse(old.trip_is_fatal())

    def test_rain_combo_is_three_x_route_and_fatal_trip(self):
        ctx = ModifierContext(frozenset({"old", "rainy_roads"}))
        rainy_roads.install_for_round(ctx)
        old.install_for_round(ctx)
        after_rain = rainy_roads.scaled_time_limit(60.0)
        self.assertEqual(after_rain, 90.0)
        self.assertEqual(old.scaled_time_limit(after_rain), 180.0)
        self.assertTrue(old.trip_is_fatal())

    def test_time_pressure_bonus_doubled(self):
        ctx = ModifierContext(frozenset({"old", "time_pressure"}))
        time_pressure.install_for_round(ctx, preset_id="normal")
        old.install_for_round(ctx)
        base = time_pressure.apply_crossing_bonus(time_pressure.TIER_SAFE_CROSSWALK)
        self.assertGreater(base, 0)
        self.assertEqual(base * old.time_bonus_mult(), base * 2.0)

    def test_fatal_trip_slip_then_fail_no_blackout(self):
        ctx = ModifierContext(frozenset({"old", "rainy_roads"}))
        old.install_for_round(ctx)
        self.assertFalse(old.is_fatal_trip_active())
        old.begin_fatal_trip(10.0)
        self.assertTrue(old.is_fatal_trip_active())
        self.assertFalse(old.should_blackout())
        self.assertEqual(old.update_fatal_trip(10.5), "continue")
        self.assertFalse(old.should_blackout())
        self.assertEqual(old.update_fatal_trip(12.0), "fail")
        self.assertFalse(old.should_blackout())
        self.assertEqual(old.fatal_slip_duration(), 2.0)


if __name__ == "__main__":
    unittest.main()
