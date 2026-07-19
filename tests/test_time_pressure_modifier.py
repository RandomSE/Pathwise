"""Tests for time_pressure modifier (short timer + crossing bonuses)."""

from __future__ import annotations

import unittest

from pathwise.modifiers.registry import (
    ModifierContext,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import time_pressure
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestTimePressureRegistry(unittest.TestCase):
    def test_bit_is_sixteen(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"time_pressure"})), 16)
        self.assertEqual(modifier_ids_from_mask(16), frozenset({"time_pressure"}))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            333333, "hard", 2, modifiers=frozenset({"time_pressure"})
        )
        self.assertEqual(encoded[3:7], "0016")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"time_pressure"}))
        self.assertEqual(payload.preset, "hard")

    def test_combo_mask_with_all(self):
        mask = modifier_mask_from_ids(
            frozenset(
                {
                    "rainy_roads",
                    "ignored",
                    "untrustworthy",
                    "lawless",
                    "time_pressure",
                }
            )
        )
        self.assertEqual(mask, 31)
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


class TestTimePressureTimerAndBonus(unittest.TestCase):
    def tearDown(self):
        time_pressure.install_for_round(ModifierContext(frozenset()))

    def test_inactive_keeps_base_limit(self):
        time_pressure.install_for_round(ModifierContext(frozenset()))
        self.assertEqual(time_pressure.initial_time_limit(40.0), 40.0)
        self.assertEqual(
            time_pressure.apply_crossing_bonus(time_pressure.TIER_SAFE_CROSSWALK),
            0.0,
        )

    def test_active_starts_at_ten_seconds(self):
        time_pressure.install_for_round(
            ModifierContext(frozenset({"time_pressure"}), session_base_seed=1, round_index=1),
            preset_id="normal",
        )
        self.assertTrue(time_pressure.is_active())
        self.assertEqual(time_pressure.initial_time_limit(90.0), 10.0)
        self.assertEqual(time_pressure.START_SECONDS, 10.0)

    def test_classify_three_tiers(self):
        self.assertEqual(
            time_pressure.classify_crossing(on_crosswalk=False, legal_crossing=False),
            time_pressure.TIER_UNSAFE_ROAD,
        )
        self.assertEqual(
            time_pressure.classify_crossing(on_crosswalk=True, legal_crossing=False),
            time_pressure.TIER_UNSAFE_CROSSWALK,
        )
        self.assertEqual(
            time_pressure.classify_crossing(on_crosswalk=True, legal_crossing=True),
            time_pressure.TIER_SAFE_CROSSWALK,
        )

    def test_safe_bonus_greater_than_unsafe_tiers(self):
        for preset in ("easy", "normal", "hard"):
            road = time_pressure.bonus_seconds_for(
                time_pressure.TIER_UNSAFE_ROAD, preset_id=preset
            )
            unsafe_cw = time_pressure.bonus_seconds_for(
                time_pressure.TIER_UNSAFE_CROSSWALK, preset_id=preset
            )
            safe = time_pressure.bonus_seconds_for(
                time_pressure.TIER_SAFE_CROSSWALK, preset_id=preset
            )
            self.assertLess(road, unsafe_cw, preset)
            self.assertLess(unsafe_cw, safe, preset)

    def test_hard_gives_more_bonus_than_easier_presets(self):
        for tier in (
            time_pressure.TIER_UNSAFE_ROAD,
            time_pressure.TIER_UNSAFE_CROSSWALK,
            time_pressure.TIER_SAFE_CROSSWALK,
        ):
            easy = time_pressure.bonus_seconds_for(tier, preset_id="easy")
            normal = time_pressure.bonus_seconds_for(tier, preset_id="normal")
            hard = time_pressure.bonus_seconds_for(tier, preset_id="hard")
            self.assertLess(easy, normal, tier)
            self.assertLess(normal, hard, tier)

    def test_apply_crossing_bonus_uses_preset(self):
        time_pressure.install_for_round(
            ModifierContext(frozenset({"time_pressure"}), session_base_seed=1, round_index=1),
            preset_id="hard",
        )
        bonus = time_pressure.apply_crossing_bonus(
            time_pressure.TIER_SAFE_CROSSWALK, elapsed=1.0
        )
        self.assertEqual(bonus, 10.0)
        self.assertEqual(time_pressure.last_bonus_seconds(), 10.0)
        self.assertEqual(
            time_pressure.last_bonus_tier(), time_pressure.TIER_SAFE_CROSSWALK
        )
        self.assertEqual(time_pressure.active_bonus_popup_text(1.0), "+10s")
        self.assertIsNone(time_pressure.active_bonus_popup_text(3.0))

    def test_legal_crossing_for_bonus_lawless_any_crosswalk(self):
        self.assertTrue(
            time_pressure.legal_crossing_for_bonus(
                on_crosswalk=True,
                cars_have_red=False,
                legal_commit_active=False,
                unsignalized=True,
            )
        )
        self.assertFalse(
            time_pressure.legal_crossing_for_bonus(
                on_crosswalk=True,
                cars_have_red=False,
                legal_commit_active=False,
                unsignalized=False,
            )
        )
        self.assertTrue(
            time_pressure.legal_crossing_for_bonus(
                on_crosswalk=True,
                cars_have_red=True,
                legal_commit_active=False,
                unsignalized=False,
            )
        )

    def test_safe_budget_near_target_play_time(self):
        for preset, lo, hi in (
            ("easy", 0.65, 0.85),
            ("normal", 0.65, 0.85),
            ("hard", 0.85, 1.15),
        ):
            target = time_pressure._TARGET_PLAY_S[preset]
            budget = time_pressure.expected_safe_budget_seconds(preset)
            ratio = budget / target
            self.assertGreaterEqual(ratio, lo, preset)
            self.assertLessEqual(ratio, hi, preset)

    def test_hard_budget_exceeds_easier_presets_at_mid_crossings(self):
        easy = time_pressure.expected_safe_budget_seconds("easy")
        normal = time_pressure.expected_safe_budget_seconds("normal")
        hard = time_pressure.expected_safe_budget_seconds("hard")
        self.assertLess(easy, normal)
        self.assertLess(normal, hard)

    def test_bonus_summary_tracks_events(self):
        time_pressure.install_for_round(
            ModifierContext(frozenset({"time_pressure"}), session_base_seed=1, round_index=1),
            preset_id="normal",
        )
        time_pressure.apply_crossing_bonus(time_pressure.TIER_UNSAFE_ROAD, elapsed=0.5)
        time_pressure.apply_crossing_bonus(time_pressure.TIER_SAFE_CROSSWALK, elapsed=1.0)
        summary = time_pressure.bonus_summary()
        self.assertEqual(summary["preset"], "normal")
        self.assertEqual(summary["start_seconds"], 10.0)
        self.assertFalse(summary["rain_combo"])
        self.assertEqual(summary["total_bonus_s"], 3.0 + 7.5)
        self.assertEqual(len(summary["events"]), 2)
        self.assertEqual(summary["events"][0]["tier"], time_pressure.TIER_UNSAFE_ROAD)

    def test_timer_bank_caps_at_two_max_crossings(self):
        time_pressure.install_for_round(
            ModifierContext(frozenset({"time_pressure"}), session_base_seed=1, round_index=1),
            preset_id="normal",
        )
        max_one = time_pressure.max_single_crossing_bonus_s()
        self.assertAlmostEqual(max_one, 6.0 * 1.25)
        cap = time_pressure.max_time_bank_seconds()
        self.assertAlmostEqual(cap, 2.0 * max_one)
        # Starting at 10s is under the normal cap (~15s).
        self.assertEqual(
            time_pressure.clamp_timer_limit(10.0, elapsed=0.0),
            10.0,
        )
        # Stacking past the bank clamps remaining time.
        clamped = time_pressure.clamp_timer_limit(40.0, elapsed=5.0)
        self.assertAlmostEqual(clamped, 5.0 + cap)

    def test_rain_combo_starts_at_twenty_and_boosts_bonus(self):
        time_pressure.install_for_round(
            ModifierContext(
                frozenset({"time_pressure", "rainy_roads"}),
                session_base_seed=1,
                round_index=1,
            ),
            preset_id="hard",
        )
        self.assertTrue(time_pressure.rain_combo_active())
        self.assertEqual(time_pressure.initial_time_limit(90.0), 20.0)
        self.assertEqual(time_pressure.start_seconds(), 20.0)
        bonus = time_pressure.bonus_seconds_for(time_pressure.TIER_SAFE_CROSSWALK)
        self.assertAlmostEqual(bonus, 8.0 * 1.25 * 1.75)
        applied = time_pressure.apply_crossing_bonus(
            time_pressure.TIER_SAFE_CROSSWALK, elapsed=0.2
        )
        self.assertAlmostEqual(applied, 8.0 * 1.25 * 1.75)
        summary = time_pressure.bonus_summary()
        self.assertTrue(summary["rain_combo"])
        self.assertEqual(summary["start_seconds"], 20.0)


class TestTimePressureDecisionLog(unittest.TestCase):
    def test_note_road_crossed_records_tier_and_bonus(self):
        from analytics.decision_logger import DecisionLogger

        logger = DecisionLogger((0, 0), (100, 100), "map", 2)
        logger.note_road_approach(0)
        logger.note_road_crossed(
            0,
            "red",
            crossing_tier=time_pressure.TIER_SAFE_CROSSWALK,
            time_bonus_s=7.5,
        )
        attempt = logger.crossing_attempts[-1]
        self.assertEqual(attempt["crossing_tier"], time_pressure.TIER_SAFE_CROSSWALK)
        self.assertEqual(attempt["time_bonus_s"], 7.5)
        actions = [d["action"] for d in logger.decisions]
        self.assertIn("crossing_time_bonus", actions)


class TestModifierComboCopy(unittest.TestCase):
    def test_detail_lines_include_combo_banner_when_both_active(self):
        from pathwise.pre_game import modifier_detail_lines, modifier_explain_body

        lines = modifier_detail_lines(frozenset({"rainy_roads", "time_pressure"}))
        self.assertEqual(lines[0][0], "Rain + Time pressure")
        self.assertIn("20 seconds", lines[0][1])
        self.assertIn("75%", lines[0][1])
        body = modifier_explain_body(
            "time_pressure", frozenset({"rainy_roads", "time_pressure"})
        )
        assert body is not None
        self.assertIn("Active together now", body)
        self.assertIn("20 seconds", body)


if __name__ == "__main__":
    unittest.main()
