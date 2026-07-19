"""Tests for lawless modifier (unsignalized crossings, no traffic lights)."""

from __future__ import annotations

import unittest

from pathwise.crosswalk_rules import (
    cars_should_respect_player,
    crosswalk_crossing_is_legal,
    update_legal_crossing_commit,
)
from pathwise.modifiers.registry import (
    ModifierContext,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)
from pathwise.modifiers import lawless
from pathwise.session_seed import decode_recruiter_seed, encode_recruiter_seed


class TestLawlessRegistry(unittest.TestCase):
    def test_bit_is_eight(self):
        self.assertEqual(modifier_mask_from_ids(frozenset({"lawless"})), 8)
        self.assertEqual(modifier_ids_from_mask(8), frozenset({"lawless"}))

    def test_seed_round_trip(self):
        encoded = encode_recruiter_seed(
            222222, "normal", 1, modifiers=frozenset({"lawless"})
        )
        self.assertEqual(encoded[3:7], "0008")
        payload = decode_recruiter_seed(encoded)
        assert payload is not None
        self.assertEqual(payload.modifiers, frozenset({"lawless"}))

    def test_combo_mask_with_others(self):
        mask = modifier_mask_from_ids(
            frozenset({"rainy_roads", "ignored", "untrustworthy", "lawless"})
        )
        self.assertEqual(mask, 15)
        self.assertEqual(
            modifier_ids_from_mask(15),
            frozenset({"rainy_roads", "ignored", "untrustworthy", "lawless"}),
        )


class TestLawlessInstallHooks(unittest.TestCase):
    def tearDown(self):
        lawless.install_for_round(ModifierContext(frozenset()))

    def test_inactive_keeps_signals_enabled(self):
        lawless.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(lawless.is_active())
        self.assertTrue(lawless.signals_enabled())
        self.assertTrue(lawless.should_emit_against_light_risk())

    def test_active_disables_signals(self):
        lawless.install_for_round(
            ModifierContext(frozenset({"lawless"}), session_base_seed=1, round_index=1)
        )
        self.assertTrue(lawless.is_active())
        self.assertFalse(lawless.signals_enabled())
        self.assertFalse(lawless.should_emit_against_light_risk())


class TestLawlessCommitAndRespect(unittest.TestCase):
    def test_unsignalized_commit_latches_without_car_red(self):
        active = update_legal_crossing_commit(
            False, True, False, on_road=False, unsignalized=True
        )
        self.assertTrue(active)
        active = update_legal_crossing_commit(
            active, True, False, on_road=True, unsignalized=True
        )
        self.assertTrue(active)
        active = update_legal_crossing_commit(
            active, False, False, on_road=True, unsignalized=True
        )
        self.assertTrue(active)
        active = update_legal_crossing_commit(
            active, False, False, on_road=False, unsignalized=True
        )
        self.assertFalse(active)

    def test_signalized_commit_still_requires_red(self):
        self.assertFalse(
            update_legal_crossing_commit(False, True, False, unsignalized=False)
        )
        self.assertTrue(
            update_legal_crossing_commit(False, True, True, unsignalized=False)
        )

    def test_legal_crossing_and_respect_while_committed(self):
        self.assertTrue(crosswalk_crossing_is_legal(False, True))
        self.assertTrue(
            cars_should_respect_player(False, True, True)
        )
        self.assertFalse(
            cars_should_respect_player(False, True, False)
        )
        self.assertTrue(
            cars_should_respect_player(True, False, False)
        )


class TestLawlessRiskHelpers(unittest.TestCase):
    def tearDown(self):
        lawless.install_for_round(ModifierContext(frozenset()))

    def test_uncontrolled_risk_when_traffic_approaches(self):
        lawless.install_for_round(
            ModifierContext(frozenset({"lawless"}), session_base_seed=1, round_index=1)
        )
        self.assertTrue(
            lawless.should_emit_uncontrolled_crosswalk_risk(
                on_crosswalk=True, approaching_traffic=True
            )
        )
        self.assertFalse(
            lawless.should_emit_uncontrolled_crosswalk_risk(
                on_crosswalk=True, approaching_traffic=False
            )
        )
        self.assertFalse(
            lawless.should_emit_uncontrolled_crosswalk_risk(
                on_crosswalk=False, approaching_traffic=True
            )
        )

    def test_uncontrolled_risk_inactive_when_modifier_off(self):
        lawless.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(
            lawless.should_emit_uncontrolled_crosswalk_risk(
                on_crosswalk=True, approaching_traffic=True
            )
        )


class TestLawlessCarSignals(unittest.TestCase):
    def tearDown(self):
        lawless.install_for_round(ModifierContext(frozenset()))

    def test_lawless_does_not_block_crosswalk_on_red(self):
        import main as game

        lawless.install_for_round(
            ModifierContext(frozenset({"lawless"}), session_base_seed=1, round_index=1)
        )
        zone = __import__("pathwise.geom", fromlist=["Rect"]).Rect(100, 100, 80, 80)
        crosswalk = __import__("pathwise.geom", fromlist=["Rect"]).Rect(90, 123, 14, 14)
        car = game.Car(35, 115, 3.0, vertical=False, spawn_id=91)
        car.direction = 1
        car.rect.right = crosswalk.left - 2
        car._sync_collision_shell(force=True)
        state = {
            "crosswalk": crosswalk,
            "light_state": "red",
            "seconds_to_change": 4.0,
            "approach_rect": zone.inflate(200, 200),
        }
        next_rect = car.rect.copy()
        next_rect.x += 4
        self.assertFalse(car._obeys_traffic_signals())
        self.assertFalse(car._crosswalk_advance_blocked(next_rect, [state], [zone]))
        self.assertFalse(
            car._retreat_from_crosswalk_on_red(
                state, inside_intersection=False, intersection_zones=[zone]
            )
        )

    def test_ignored_still_disables_yield_under_lawless(self):
        from pathwise.modifiers import ignored

        ctx = ModifierContext(
            frozenset({"lawless", "ignored"}), session_base_seed=1, round_index=1
        )
        lawless.install_for_round(ctx)
        ignored.install_for_round(ctx)
        self.assertTrue(lawless.is_active())
        self.assertTrue(ignored.should_disable_player_yield())
        ignored.install_for_round(ModifierContext(frozenset()))


class TestLawlessDrawSmoke(unittest.TestCase):
    def tearDown(self):
        lawless.install_for_round(ModifierContext(frozenset()))

    def test_traffic_overlays_return_empty_when_lawless(self):
        from pathwise.game_draw import draw_traffic_light_overlays
        from pathwise.geom import Rect

        lawless.install_for_round(
            ModifierContext(frozenset({"lawless"}), session_base_seed=1, round_index=1)
        )
        labels = draw_traffic_light_overlays(
            720,
            [],
            (0, 0),
            5.0,
            Rect(0, 0, 100, 100),
        )
        self.assertEqual(labels, [])


if __name__ == "__main__":
    unittest.main()
