"""Tests for crossing-plane honk/risk rules and risk tiers."""

import unittest
from unittest.mock import MagicMock

from pathwise.geom import Rect
from pathwise.car import Car


class TestCrossingPlane(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game

    def _vertical_crosswalk_state(self, light="green"):
        return {
            "direction": "vertical",
            "crosswalk": Rect(100, 200, 14, 90),
            "light_state": light,
        }

    def _horizontal_crosswalk_state(self, light="red"):
        return {
            "direction": "horizontal",
            "crosswalk": Rect(80, 300, 120, 14),
            "light_state": light,
        }

    def test_vertical_crosswalk_conflicts_with_horizontal_traffic(self):
        body = Rect(102, 220, 20, 20)
        axis = self.game.player_conflicting_car_vertical(
            body, [self._vertical_crosswalk_state()], []
        )
        self.assertFalse(axis)

    def test_horizontal_crosswalk_conflicts_with_vertical_traffic(self):
        body = Rect(90, 302, 20, 20)
        axis = self.game.player_conflicting_car_vertical(
            body, [self._horizontal_crosswalk_state()], []
        )
        self.assertTrue(axis)

    def test_horizontal_street_car_not_on_vertical_crosswalk_plane(self):
        # Cars on a horizontal road travel along Y (vertical=True).
        car = Car(100, 100, 3.0, vertical=True, spawn_id=1)
        self.assertFalse(
            self.game.car_shares_crossing_plane(car, conflict_car_vertical=False)
        )

    def test_vertical_street_car_on_vertical_crosswalk_plane(self):
        car = Car(100, 100, 3.0, vertical=False, spawn_id=1)
        self.assertTrue(
            self.game.car_shares_crossing_plane(car, conflict_car_vertical=False)
        )

    def test_vertical_street_car_on_horizontal_crosswalk_plane(self):
        car = Car(100, 100, 3.0, vertical=True, spawn_id=1)
        self.assertTrue(
            self.game.car_shares_crossing_plane(car, conflict_car_vertical=True)
        )

    def test_perpendicular_car_cannot_honk_on_vertical_crosswalk(self):
        # Stopped traffic on the horizontal road (vertical=True) while ped crosses vertical road.
        car = Car(105, 230, 0.0, vertical=True, spawn_id=1)
        car._sync_collision_shell(force=True)
        player = Rect(102, 220, 20, 20)
        global_ok = self.game.should_honk_at_player_precomputed(
            feet_on_road=True,
            mostly_on_legal_crosswalk=False,
            on_crosswalk=True,
            on_car_red_crosswalk=False,
        )
        self.assertTrue(global_ok)
        car_ok = global_ok and self.game.car_shares_crossing_plane(
            car, conflict_car_vertical=False
        )
        self.assertFalse(car_ok)
        car.evaluate_honk(player, True, car_ok, game_time=10.0)
        self.assertFalse(car.honk_risk_pending)

    def test_same_plane_car_can_honk_when_jaywalking(self):
        car = Car(105, 210, 3.0, vertical=False, spawn_id=1)
        car._sync_collision_shell(force=True)
        player = Rect(102, 220, 20, 20)
        car_ok = self.game.car_shares_crossing_plane(car, conflict_car_vertical=False)
        self.assertTrue(car_ok)
        car.evaluate_honk(player, False, True, game_time=10.0)
        self.assertIsInstance(car.honk_risk_pending, bool)

    def test_legal_red_crossing_records_no_risks(self):
        body = Rect(102, 220, 20, 20)
        states = [self._vertical_crosswalk_state(light="red")]
        self.assertTrue(self.game.player_crossing_cars_have_red(body, states))

        stopped = Car(105, 210, 0.0, vertical=False, spawn_id=2)
        stopped._sync_collision_shell(force=True)
        self.game.reasonable_risk_events = 0
        self.game.risky_risk_events = 0
        self.game.risk_events = 0
        self.game.last_risk_time = 0
        self.game.decision_logger = MagicMock()

        # Legal crossing with stopped traffic: no risk events at all.
        if self.game.player_crossing_cars_have_red(body, states):
            threatening = [
                c
                for c in [stopped]
                if self.game.car_is_traffic_threat(c)
            ]
            if not threatening:
                pass
        self.assertEqual(self.game.reasonable_risk_events, 0)
        self.assertEqual(self.game.risky_risk_events, 0)
        self.game.decision_logger.note_risk.assert_not_called()

    def test_record_risk_tiers(self):
        self.game.reasonable_risk_events = 0
        self.game.risky_risk_events = 0
        self.game.risk_events = 0
        self.game.last_risk_time = 0
        self.game.decision_logger = MagicMock()

        self.game.record_risk("legal_crosswalk_clear", tier="reasonable", cooldown=0)
        self.game.record_risk("jaywalk", tier="risky", cooldown=0)
        self.assertEqual(self.game.reasonable_risk_events, 1)
        self.assertEqual(self.game.risky_risk_events, 1)
        self.assertEqual(self.game.risk_events, 1)

    def test_legal_crossing_commit_latches_on_red(self):
        active = self.game.update_legal_crossing_commit(False, True, True)
        self.assertTrue(active)

    def test_legal_crossing_commit_holds_after_light_turns_green(self):
        active = self.game.update_legal_crossing_commit(True, True, False)
        self.assertTrue(active)
        self.assertTrue(
            self.game.crosswalk_crossing_is_legal(on_car_red=False, legal_commit_active=active)
        )

    def test_legal_crossing_commit_clears_off_crosswalk(self):
        active = self.game.update_legal_crossing_commit(True, False, False)
        self.assertFalse(active)

    def test_legal_crossing_commit_holds_on_road_until_sidewalk(self):
        active = self.game.update_legal_crossing_commit(False, True, True)
        active = self.game.update_legal_crossing_commit(active, False, False, on_road=True)
        self.assertTrue(active)
        active = self.game.update_legal_crossing_commit(active, False, False, on_road=False)
        self.assertFalse(active)

    def test_green_crossing_without_commit_is_not_legal(self):
        self.assertFalse(
            self.game.crosswalk_crossing_is_legal(on_car_red=False, legal_commit_active=False)
        )


if __name__ == "__main__":
    unittest.main()
