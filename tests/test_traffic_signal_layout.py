import unittest

from pathwise.geom import Rect
from pathwise.traffic_signal_layout import (
    APPROACH_EAST,
    APPROACH_NORTH,
    APPROACH_SOUTH,
    APPROACH_WEST,
    bulb_positions,
    traffic_housing_rect,
)


class TestTrafficSignalLayout(unittest.TestCase):
    def test_west_approach_housing_on_far_east_side_of_crosswalk(self):
        crosswalk = Rect(80, 100, 12, 80)
        housing = traffic_housing_rect(crosswalk, "vertical", APPROACH_WEST)
        self.assertGreaterEqual(housing.left, crosswalk.right)

    def test_east_approach_housing_on_far_west_side_of_crosswalk(self):
        crosswalk = Rect(200, 100, 12, 80)
        housing = traffic_housing_rect(crosswalk, "vertical", APPROACH_EAST)
        self.assertLessEqual(housing.right, crosswalk.left)

    def test_north_approach_housing_on_far_south_side_of_crosswalk(self):
        crosswalk = Rect(100, 80, 80, 12)
        housing = traffic_housing_rect(crosswalk, "horizontal", APPROACH_NORTH)
        self.assertGreaterEqual(housing.top, crosswalk.bottom)

    def test_south_approach_housing_on_far_north_side_of_crosswalk(self):
        crosswalk = Rect(100, 200, 80, 12)
        housing = traffic_housing_rect(crosswalk, "horizontal", APPROACH_SOUTH)
        self.assertLessEqual(housing.bottom, crosswalk.top)

    def test_vertical_bulbs_red_top_green_bottom(self):
        crosswalk = Rect(80, 100, 12, 80)
        housing = traffic_housing_rect(crosswalk, "vertical", APPROACH_WEST)
        bulbs = bulb_positions(housing, "vertical", APPROACH_WEST)
        self.assertEqual(len(bulbs), 3)
        self.assertLess(bulbs[0][1], bulbs[1][1])
        self.assertLess(bulbs[1][1], bulbs[2][1])

    def test_horizontal_bulbs_red_left_green_right(self):
        crosswalk = Rect(100, 80, 80, 12)
        housing = traffic_housing_rect(crosswalk, "horizontal", APPROACH_NORTH)
        bulbs = bulb_positions(housing, "horizontal", APPROACH_NORTH)
        self.assertLess(bulbs[0][0], bulbs[1][0])
        self.assertLess(bulbs[1][0], bulbs[2][0])

    def test_opposing_vertical_approaches_share_phase_in_build(self):
        import main as game
        from map_generation.difficulty import DifficultyProfile

        game.session_base_seed = 1890416619
        game.session_use_adaptive_map = False
        profile = DifficultyProfile.for_menu_preset("normal")
        game.start_round(1, profile, "normal")
        by_approach: dict[str, set[float]] = {}
        for state in game.road_states:
            approach = state.get("approach")
            if not approach:
                continue
            by_approach.setdefault(approach, set()).add(
                round(state["phase_offset"], 4)
            )
        if APPROACH_WEST in by_approach and APPROACH_EAST in by_approach:
            self.assertEqual(by_approach[APPROACH_WEST], by_approach[APPROACH_EAST])
        if APPROACH_NORTH in by_approach and APPROACH_SOUTH in by_approach:
            self.assertEqual(by_approach[APPROACH_NORTH], by_approach[APPROACH_SOUTH])


if __name__ == "__main__":
    unittest.main()
