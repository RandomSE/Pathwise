"""Tests for ignored modifier (cars never yield to the player)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import ModifierContext, modifier_mask_from_ids, modifier_ids_from_mask
from pathwise.modifiers import ignored
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestIgnoredRegistry(unittest.TestCase):
    def test_bit_is_two(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"ignored"})), 2)
        self.assertEqual(modifier_ids_from_mask(2), frozenset({"ignored"}))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            111111, "normal", 1, modifiers=frozenset({"ignored"})
        )
        self.assertEqual(encoded[3:7], "0002")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"ignored"}))


class TestIgnoredYieldHooks(unittest.TestCase):
    def tearDown(self):
        ignored.install_for_round(ModifierContext(frozenset()))

    def test_inactive_does_not_disable_yield(self):
        ignored.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(ignored.should_disable_player_yield())
        self.assertFalse(ignored.should_skip_player_body_block())

    def test_active_disables_yield_and_body_block(self):
        ignored.install_for_round(
            ModifierContext(frozenset({"ignored"}), session_base_seed=1, round_index=1)
        )
        self.assertTrue(ignored.is_active())
        self.assertTrue(ignored.should_disable_player_yield())
        self.assertTrue(ignored.should_skip_player_body_block())
        self.assertTrue(ignored.should_suppress_honk())

    def test_inactive_does_not_suppress_honk(self):
        ignored.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(ignored.should_suppress_honk())


if __name__ == "__main__":
    unittest.main()
