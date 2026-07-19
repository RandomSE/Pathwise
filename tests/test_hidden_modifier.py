"""Tests for Hidden modifier (candidate HUD + pre-round concealment)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import hidden
from pathwise.pre_game import (
    build_candidate_session_config,
    build_recruiter_session_config,
    modifier_detail_lines,
)
from pathwise.session_seed import (
    ENCODED_SEED_LEN_V9_WIDE,
    decode_recruiter_seed,
    encode_recruiter_seed,
)


class TestHiddenRegistry(unittest.TestCase):
    def test_bit_is_two_zero_four_eight(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"hidden"})), 2048)
        self.assertEqual(modifier_ids_from_mask(2048), frozenset({"hidden"}))
        self.assertTrue(is_valid_modifier_mask(2048))
        self.assertTrue(is_valid_modifier_mask(1 | 2048))

    def test_seed_round_trip_wide_mask(self):
        encoded = encode_recruiter_seed(
            777777, "hard", 1, modifiers=frozenset({"hidden", "rainy_roads"})
        )
        self.assertEqual(len(encoded), ENCODED_SEED_LEN_V9_WIDE)
        self.assertEqual(encoded[3:7], "2049")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"hidden", "rainy_roads"}))


class TestHiddenVisibility(unittest.TestCase):
    def tearDown(self):
        hidden.install_for_round(ModifierContext(frozenset()))

    def test_candidate_pre_round_lists_only_hidden(self):
        mods = frozenset({"hidden", "rainy_roads", "old"})
        visible = hidden.visible_modifiers(mods, audience="candidate")
        self.assertEqual(visible, frozenset({"hidden"}))
        titles = [title for title, _ in modifier_detail_lines(mods, audience="candidate")]
        self.assertEqual(titles, ["Hidden"])

    def test_recruiter_pre_round_lists_all(self):
        mods = frozenset({"hidden", "rainy_roads"})
        visible = hidden.visible_modifiers(mods, audience="recruiter")
        self.assertEqual(visible, mods)
        titles = {
            title for title, _ in modifier_detail_lines(mods, audience="recruiter")
        }
        self.assertIn("Hidden", titles)
        self.assertIn("Rainy roads", titles)

    def test_without_hidden_lists_are_unchanged(self):
        mods = frozenset({"rainy_roads", "old"})
        self.assertEqual(
            hidden.visible_modifiers(mods, audience="candidate"), mods
        )

    def test_candidate_hud_suppressed(self):
        hidden.install_for_round(
            ModifierContext(frozenset({"hidden"})), audience="candidate"
        )
        self.assertTrue(hidden.suppress_hud())

    def test_recruiter_hud_visible(self):
        hidden.install_for_round(
            ModifierContext(frozenset({"hidden"})), audience="recruiter"
        )
        self.assertFalse(hidden.suppress_hud())
        self.assertTrue(hidden.is_active())

    def test_inactive_no_suppression(self):
        hidden.install_for_round(ModifierContext(frozenset()), audience="candidate")
        self.assertFalse(hidden.suppress_hud())


class TestHiddenSessionAudience(unittest.TestCase):
    def test_candidate_config_audience(self):
        encoded = encode_recruiter_seed(
            12, "normal", 1, modifiers=frozenset({"hidden"})
        )
        cfg = build_candidate_session_config(encoded)
        self.assertEqual(cfg.audience, "candidate")
        self.assertEqual(cfg.modifiers, frozenset({"hidden"}))

    def test_recruiter_config_audience(self):
        encoded = encode_recruiter_seed(
            12, "normal", 1, modifiers=frozenset({"hidden"})
        )
        cfg = build_recruiter_session_config(encoded, preset="normal", num_rounds=1)
        self.assertEqual(cfg.audience, "recruiter")


if __name__ == "__main__":
    unittest.main()
