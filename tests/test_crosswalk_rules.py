"""Unit tests for pathwise.crosswalk_rules (direct module import)."""

import unittest
from unittest.mock import MagicMock

from pathwise.crosswalk_rules import (
    car_shares_crossing_plane,
    crosswalk_crossing_is_legal,
    player_conflicting_car_vertical,
    road_midline_crossed,
    should_honk_at_player_precomputed,
    update_legal_crossing_commit,
)
from pathwise.geom import Rect
from pathwise.map import Road, make_rectangle
from pathwise import commonUtils


class TestCrosswalkRules(unittest.TestCase):
    def test_update_legal_crossing_commit_latches_on_red(self):
        self.assertTrue(update_legal_crossing_commit(False, True, True))
        self.assertTrue(update_legal_crossing_commit(True, True, False))
        self.assertTrue(update_legal_crossing_commit(True, False, False, on_road=True))
        self.assertFalse(update_legal_crossing_commit(True, False, False, on_road=False))

    def test_update_legal_crossing_commit_unsignalized_latches_without_red(self):
        self.assertTrue(
            update_legal_crossing_commit(False, True, False, unsignalized=True)
        )
        self.assertFalse(
            update_legal_crossing_commit(False, True, False, unsignalized=False)
        )

    def test_commit_survives_light_change_on_road(self):
        active = update_legal_crossing_commit(False, True, True)
        active = update_legal_crossing_commit(active, True, False)
        self.assertTrue(active)
        active = update_legal_crossing_commit(active, False, False, on_road=True)
        self.assertTrue(active)
        self.assertTrue(crosswalk_crossing_is_legal(False, active))

    def test_crosswalk_crossing_is_legal(self):
        self.assertTrue(crosswalk_crossing_is_legal(True, False))
        self.assertTrue(crosswalk_crossing_is_legal(False, True))
        self.assertFalse(crosswalk_crossing_is_legal(False, False))

    def test_should_honk_precomputed_blocks_legal_crosswalk(self):
        self.assertFalse(
            should_honk_at_player_precomputed(
                feet_on_road=True,
                mostly_on_legal_crosswalk=True,
                on_crosswalk=True,
                on_car_red_crosswalk=True,
            )
        )
        self.assertTrue(
            should_honk_at_player_precomputed(
                feet_on_road=True,
                mostly_on_legal_crosswalk=False,
                on_crosswalk=False,
                on_car_red_crosswalk=False,
            )
        )

    def test_vertical_crosswalk_conflicts_with_horizontal_traffic(self):
        body = Rect(102, 220, 20, 20)
        states = [
            {
                "direction": "vertical",
                "crosswalk": Rect(100, 200, 14, 90),
                "light_state": "green",
            }
        ]
        self.assertFalse(player_conflicting_car_vertical(body, states, []))

    def test_car_shares_crossing_plane(self):
        car = MagicMock(vertical=False)
        self.assertTrue(car_shares_crossing_plane(car, None))
        self.assertTrue(car_shares_crossing_plane(car, conflict_car_vertical=False))
        car.vertical = True
        self.assertFalse(car_shares_crossing_plane(car, conflict_car_vertical=False))

    def test_road_midline_crossed_vertical(self):
        road = Road(make_rectangle(100, 200, 110, 400), commonUtils.VERTICAL)
        self.assertTrue(road_midline_crossed((155, 500), (155, 300), road))
        self.assertFalse(road_midline_crossed((120, 300), (180, 300), road))
        mid = road.rect.centery
        self.assertTrue(road_midline_crossed((155, mid + 1), (155, mid), road))


if __name__ == "__main__":
    unittest.main()
