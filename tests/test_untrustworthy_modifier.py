"""Tests for untrustworthy modifier (some cars run reds and ignore the player)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import ModifierContext, modifier_mask_from_ids, modifier_ids_from_mask
from pathwise.modifiers import untrustworthy
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestUntrustworthyRegistry(unittest.TestCase):
    def test_bit_is_four(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"untrustworthy"})), 4)
        self.assertEqual(modifier_ids_from_mask(4), frozenset({"untrustworthy"}))

    def test_combined_mask_with_rainy_and_ignored(self):
        mask = modifier_mask_from_ids(
            frozenset({"rainy_roads", "ignored", "untrustworthy"})
        )
        self.assertEqual(mask, 7)
        self.assertEqual(
            modifier_ids_from_mask(7),
            frozenset({"rainy_roads", "ignored", "untrustworthy"}),
        )

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            222222, "hard", 2, modifiers=frozenset({"untrustworthy"})
        )
        self.assertEqual(encoded[3:7], "0004")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"untrustworthy"}))


class TestUntrustworthyRolls(unittest.TestCase):
    def tearDown(self):
        untrustworthy.install_for_round(ModifierContext(frozenset()))

    def test_inactive_never_unlawful(self):
        untrustworthy.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(untrustworthy.is_unlawful(spawn_id=1))
        self.assertFalse(untrustworthy.should_skip_red_stop(spawn_id=1))
        self.assertFalse(untrustworthy.should_disable_player_yield(spawn_id=1))

    def test_unlawful_roll_is_deterministic(self):
        ctx = ModifierContext(
            frozenset({"untrustworthy"}), session_base_seed=99, round_index=1
        )
        untrustworthy.install_for_round(ctx)
        a = untrustworthy.is_unlawful(spawn_id=3)
        b = untrustworthy.is_unlawful(spawn_id=3)
        self.assertEqual(a, b)

    def test_unlawful_cars_skip_red_and_player_yield(self):
        ctx = ModifierContext(
            frozenset({"untrustworthy"}), session_base_seed=7, round_index=1
        )
        untrustworthy.install_for_round(ctx)
        found_lawful = False
        found_unlawful = False
        for spawn_id in range(80):
            if untrustworthy.is_unlawful(spawn_id=spawn_id):
                found_unlawful = True
                self.assertTrue(untrustworthy.should_skip_red_stop(spawn_id=spawn_id))
                self.assertTrue(
                    untrustworthy.should_disable_player_yield(spawn_id=spawn_id)
                )
                self.assertTrue(
                    untrustworthy.should_skip_player_body_block(spawn_id=spawn_id)
                )
            else:
                found_lawful = True
                self.assertFalse(untrustworthy.should_skip_red_stop(spawn_id=spawn_id))
                self.assertFalse(
                    untrustworthy.should_disable_player_yield(spawn_id=spawn_id)
                )
        self.assertTrue(found_lawful)
        self.assertTrue(found_unlawful)

    def test_mark_unlawful_infects_lawful_car(self):
        ctx = ModifierContext(
            frozenset({"untrustworthy"}), session_base_seed=7, round_index=1
        )
        untrustworthy.install_for_round(ctx)
        lawful_id = None
        for spawn_id in range(80):
            if not untrustworthy.is_unlawful(spawn_id=spawn_id):
                lawful_id = spawn_id
                break
        self.assertIsNotNone(lawful_id)
        untrustworthy.mark_unlawful(lawful_id)
        self.assertTrue(untrustworthy.is_unlawful(spawn_id=lawful_id))
        self.assertTrue(untrustworthy.should_skip_red_stop(spawn_id=lawful_id))

    def test_install_clears_infection(self):
        ctx = ModifierContext(
            frozenset({"untrustworthy"}), session_base_seed=7, round_index=1
        )
        untrustworthy.install_for_round(ctx)
        untrustworthy.mark_unlawful(9999)
        self.assertTrue(untrustworthy.is_unlawful(spawn_id=9999))
        untrustworthy.install_for_round(ctx)
        self.assertFalse(untrustworthy.is_unlawful(spawn_id=9999))


if __name__ == "__main__":
    unittest.main()
