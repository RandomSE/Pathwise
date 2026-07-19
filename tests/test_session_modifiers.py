"""Tests for recruiter seed codec and modifier registry."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import ModifierContext, modifier_mask_from_ids, modifier_ids_from_mask
from pathwise.pre_game import (
    SessionConfig,
    build_candidate_session_config,
    build_recruiter_session_config,
    recruiter_settings_fingerprint,
    recruiter_seed_stale,
)
from pathwise.session_seed import (
    ENCODED_SEED_LEN,
    ENCODED_SEED_LEN_V9,
    ENCODED_SEED_LEN_V9_WIDE,
    MAP_SEED_MOD,
    MAP_SEED_MOD_V9,
    decode_recruiter_seed,
    encode_recruiter_seed,
)


class TestSeedCodecV9(unittest.TestCase):
    def test_v9_round_trip_with_rainy_roads(self):
        encoded = encode_recruiter_seed(
            123456,
            "hard",
            3,
            modifiers=frozenset({"rainy_roads"}),
        )
        self.assertEqual(len(encoded), ENCODED_SEED_LEN_V9_WIDE)
        self.assertEqual(encoded[0], "9")
        payload = decode_recruiter_seed(encoded)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.map_seed, 123456 % MAP_SEED_MOD_V9)
        self.assertEqual(payload.preset, "hard")
        self.assertEqual(payload.num_rounds, 3)
        self.assertEqual(payload.modifiers, frozenset({"rainy_roads"}))

    def test_v9_no_modifiers_mask_zero(self):
        encoded = encode_recruiter_seed(42, "normal", 1, modifiers=frozenset())
        self.assertEqual(encoded[3:7], "0000")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset())

    def test_v8_backward_compat_empty_modifiers(self):
        legacy = encode_recruiter_seed(7654321, "easy", 2, version=8)
        self.assertEqual(len(legacy), ENCODED_SEED_LEN)
        payload = decode_recruiter_seed(legacy)
        assert payload is not None
        self.assertEqual(payload.map_seed, 7654321 % MAP_SEED_MOD)
        self.assertEqual(payload.preset, "easy")
        self.assertEqual(payload.num_rounds, 2)
        self.assertEqual(payload.modifiers, frozenset())

    def test_invalid_v9_mask_rejected(self):
        bad = "9121000999999"
        self.assertIsNone(decode_recruiter_seed(bad))

    def test_modifier_mask_helpers(self):
        self.assertEqual(modifier_mask_from_ids(frozenset()), 0)
        self.assertEqual(modifier_mask_from_ids(frozenset({"rainy_roads"})), 1)
        self.assertEqual(modifier_mask_from_ids(frozenset({"ignored"})), 2)
        self.assertEqual(modifier_mask_from_ids(frozenset({"untrustworthy"})), 4)
        self.assertEqual(modifier_mask_from_ids(frozenset({"lawless"})), 8)
        self.assertEqual(modifier_ids_from_mask(1), frozenset({"rainy_roads"}))
        self.assertEqual(modifier_ids_from_mask(2), frozenset({"ignored"}))
        self.assertEqual(modifier_ids_from_mask(4), frozenset({"untrustworthy"}))
        self.assertEqual(modifier_ids_from_mask(8), frozenset({"lawless"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"time_pressure"})), 16)
        self.assertEqual(modifier_ids_from_mask(16), frozenset({"time_pressure"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"highway"})), 32)
        self.assertEqual(modifier_ids_from_mask(32), frozenset({"highway"}))
        self.assertEqual(
            modifier_mask_from_ids(frozenset({"variable_speed_zones"})), 64
        )
        self.assertEqual(
            modifier_ids_from_mask(64), frozenset({"variable_speed_zones"})
        )
        self.assertEqual(modifier_mask_from_ids(frozenset({"exposure"})), 128)
        self.assertEqual(modifier_ids_from_mask(128), frozenset({"exposure"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"high_speed"})), 256)
        self.assertEqual(modifier_ids_from_mask(256), frozenset({"high_speed"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"lag"})), 512)
        self.assertEqual(modifier_ids_from_mask(512), frozenset({"lag"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"old"})), 1024)
        self.assertEqual(modifier_ids_from_mask(1024), frozenset({"old"}))
        self.assertEqual(modifier_mask_from_ids(frozenset({"hidden"})), 2048)
        self.assertEqual(modifier_ids_from_mask(2048), frozenset({"hidden"}))
        self.assertEqual(
            modifier_ids_from_mask(7),
            frozenset({"rainy_roads", "ignored", "untrustworthy"}),
        )
        self.assertEqual(
            modifier_ids_from_mask(15),
            frozenset({"rainy_roads", "ignored", "untrustworthy", "lawless"}),
        )
        self.assertEqual(
            modifier_ids_from_mask(31),
            frozenset(
                {
                    "rainy_roads",
                    "ignored",
                    "untrustworthy",
                    "lawless",
                    "time_pressure",
                }
            ),
        )
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


class TestSessionConfigModifiers(unittest.TestCase):
    def test_build_candidate_config_carries_modifiers(self):
        encoded = encode_recruiter_seed(500, "normal", 1, modifiers=frozenset({"rainy_roads"}))
        cfg = build_candidate_session_config(encoded)
        self.assertEqual(cfg.seed, 500)
        self.assertEqual(cfg.modifiers, frozenset({"rainy_roads"}))
        self.assertEqual(cfg.audience, "candidate")

    def test_build_recruiter_config_carries_modifiers(self):
        encoded = encode_recruiter_seed(500, "normal", 2, modifiers=frozenset({"rainy_roads"}))
        cfg = build_recruiter_session_config(encoded, preset="normal", num_rounds=2)
        self.assertEqual(cfg.modifiers, frozenset({"rainy_roads"}))
        self.assertEqual(cfg.audience, "recruiter")

    def test_fingerprint_includes_modifiers(self):
        fp_a = recruiter_settings_fingerprint("normal", 1, frozenset())
        fp_b = recruiter_settings_fingerprint("normal", 1, frozenset({"rainy_roads"}))
        self.assertNotEqual(fp_a, fp_b)

    def test_stale_when_modifiers_change(self):
        encoded = encode_recruiter_seed(1, "normal", 1, modifiers=frozenset())
        generated_fp = recruiter_settings_fingerprint("normal", 1, frozenset())
        current_fp = recruiter_settings_fingerprint("normal", 1, frozenset({"rainy_roads"}))
        self.assertTrue(
            recruiter_seed_stale(
                encoded,
                current_fingerprint=current_fp,
                generated_fingerprint=generated_fp,
            )
        )


class TestModifierContext(unittest.TestCase):
    def test_deterministic_rng(self):
        ctx = ModifierContext(frozenset({"rainy_roads"}), session_base_seed=99, round_index=2)
        a = ctx.rng(7, 3, 5).random()
        b = ctx.rng(7, 3, 5).random()
        c = ctx.rng(7, 3, 6).random()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_has_modifier(self):
        ctx = ModifierContext(frozenset({"rainy_roads"}))
        self.assertTrue(ctx.has("rainy_roads"))
        self.assertFalse(ctx.has("other"))


if __name__ == "__main__":
    unittest.main()
