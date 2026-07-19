"""Risk tier and feet-on-road sensitivity tests."""

import unittest

from pathwise.crosswalk_rules import (
    FEET_RISK_ON_ROAD_FRAC,
    crosswalk_crossing_is_legal,
    player_dominant_road_light_state,
    player_feet_fully_on_road,
    player_feet_on_road,
    player_feet_road_overlap_frac,
    player_jaywalking_off_crosswalk,
    update_legal_crossing_commit,
)
from pathwise.geom import Rect
from pathwise.map import Road, make_rectangle
from pathwise import commonUtils
from pathwise.sprint import sprint_risk_reason


class TestFeetOnRoadSensitivity(unittest.TestCase):
    def _road(self):
        return Road(make_rectangle(100, 200, 200, 40), commonUtils.HORIZONTAL)

    def test_graze_overlap_is_not_on_road(self):
        player = Rect(88, 210, 20, 20)
        frac = player_feet_road_overlap_frac(player, [self._road()])
        self.assertGreater(frac, 0.0)
        self.assertLess(frac, FEET_RISK_ON_ROAD_FRAC)
        self.assertFalse(player_feet_on_road(player, [self._road()]))
        self.assertFalse(player_feet_fully_on_road(player, [self._road()]))

    def test_partial_overlap_below_full_threshold(self):
        player = Rect(94, 210, 20, 20)
        frac = player_feet_road_overlap_frac(player, [self._road()])
        self.assertGreaterEqual(frac, 0.5)
        self.assertLess(frac, FEET_RISK_ON_ROAD_FRAC)
        self.assertFalse(player_feet_fully_on_road(player, [self._road()]))

    def test_full_overlap_counts_for_risk(self):
        player = Rect(140, 210, 20, 20)
        self.assertTrue(player_feet_fully_on_road(player, [self._road()]))


class TestLegalCrossingNotRisk(unittest.TestCase):
    def test_commit_holds_through_green_light(self):
        active = update_legal_crossing_commit(True, True, False)
        self.assertTrue(active)
        self.assertTrue(crosswalk_crossing_is_legal(False, active))

    def test_legal_red_entry_is_not_a_risk_event(self):
        """Entering on car-red is expected play: no reasonable/risky counter."""
        active = update_legal_crossing_commit(False, True, True)
        self.assertTrue(active)
        active = update_legal_crossing_commit(active, False, False, on_road=True)
        self.assertTrue(crosswalk_crossing_is_legal(False, active))

    def test_sprint_on_legal_red_crosswalk_is_still_risky(self):
        """Walking on car-red is fine; sprinting on the crosswalk is not."""
        active = update_legal_crossing_commit(False, True, True)
        self.assertTrue(crosswalk_crossing_is_legal(True, active))
        self.assertEqual(
            sprint_risk_reason(
                sprinting=True,
                moved=True,
                feet_on_road=False,
                on_crosswalk=True,
            ),
            "sprint_on_crosswalk",
        )


class TestJaywalkRiskSignals(unittest.TestCase):
    def _road_state(self, *, light="red", direction="horizontal"):
        road = Road(make_rectangle(100, 200, 200, 40), commonUtils.HORIZONTAL)
        return {
            "road_rect": road.rect,
            "direction": direction,
            "light_state": light,
            "crosswalk": Rect(100, 238, 200, 14),
        }

    def test_off_crosswalk_on_car_red_is_jaywalk_signal(self):
        body = Rect(140, 210, 20, 20)
        states = [self._road_state(light="red")]
        self.assertEqual(player_dominant_road_light_state(body, states), "red")
        self.assertTrue(
            player_jaywalking_off_crosswalk(body, states, on_crosswalk=False)
        )

    def test_off_crosswalk_on_car_green_is_not_red_light_jaywalk(self):
        body = Rect(140, 210, 20, 20)
        states = [self._road_state(light="green")]
        self.assertFalse(
            player_jaywalking_off_crosswalk(body, states, on_crosswalk=False)
        )

    def test_on_crosswalk_is_never_off_crosswalk_jaywalk(self):
        body = Rect(102, 238, 20, 20)
        states = [self._road_state(light="red")]
        self.assertFalse(
            player_jaywalking_off_crosswalk(body, states, on_crosswalk=True)
        )


if __name__ == "__main__":
    unittest.main()
