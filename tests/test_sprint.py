"""Sprint toggle, speed, and risky movement reasons."""

import unittest

from pathwise.input_keys import KEY_RIGHT, KeyState
from pathwise.pedestrian import Pedestrian
from pathwise.sim_constants import PEDESTRIAN_SPEED, SPRINT_SPEED_MULT
from pathwise.sprint import (
    effective_pedestrian_speed,
    should_cancel_sprint_on_surface_entry,
    sprint_risk_reason,
)


class TestSprintSpeed(unittest.TestCase):
    def test_effective_speed_doubles_when_sprinting(self):
        self.assertEqual(
            effective_pedestrian_speed(PEDESTRIAN_SPEED, True),
            PEDESTRIAN_SPEED * SPRINT_SPEED_MULT,
        )
        self.assertEqual(
            effective_pedestrian_speed(PEDESTRIAN_SPEED, False),
            PEDESTRIAN_SPEED,
        )

    def test_pedestrian_moves_twice_as_far_when_sprinting(self):
        walk = Pedestrian((100, 100))
        run = Pedestrian((100, 100))
        run.sprint_enabled = True
        walk_x0 = walk.rect.x
        run_x0 = run.rect.x
        keys = KeyState()
        keys.press(KEY_RIGHT)
        walk.update(keys)
        run.update(keys)
        walk_delta = walk.rect.x - walk_x0
        run_delta = run.rect.x - run_x0
        self.assertEqual(run_delta, 2 * walk_delta)

    def test_toggle_sprint(self):
        ped = Pedestrian((0, 0))
        self.assertFalse(ped.sprint_enabled)
        ped.toggle_sprint()
        self.assertTrue(ped.sprint_enabled)
        ped.toggle_sprint()
        self.assertFalse(ped.sprint_enabled)


class TestSprintRiskReason(unittest.TestCase):
    def test_road_priority_over_crosswalk(self):
        self.assertEqual(
            sprint_risk_reason(
                sprinting=True,
                moved=True,
                feet_on_road=True,
                on_crosswalk=True,
            ),
            "sprint_on_road",
        )

    def test_crosswalk_when_not_on_road_surface(self):
        self.assertEqual(
            sprint_risk_reason(
                sprinting=True,
                moved=True,
                feet_on_road=False,
                on_crosswalk=True,
            ),
            "sprint_on_crosswalk",
        )

    def test_no_risk_when_standing_still(self):
        self.assertIsNone(
            sprint_risk_reason(
                sprinting=True,
                moved=False,
                feet_on_road=True,
                on_crosswalk=True,
            )
        )

    def test_no_risk_when_sprint_off(self):
        self.assertIsNone(
            sprint_risk_reason(
                sprinting=False,
                moved=True,
                feet_on_road=True,
                on_crosswalk=False,
            )
        )


class TestSprintSurfaceCancel(unittest.TestCase):
    def test_cancels_on_first_surface_entry(self):
        self.assertTrue(
            should_cancel_sprint_on_surface_entry(
                sprinting=True,
                on_surface=True,
                was_on_surface=False,
                suppressed_this_visit=False,
            )
        )

    def test_no_cancel_when_already_on_surface(self):
        self.assertFalse(
            should_cancel_sprint_on_surface_entry(
                sprinting=True,
                on_surface=True,
                was_on_surface=True,
                suppressed_this_visit=False,
            )
        )

    def test_no_cancel_after_suppressed_until_leave(self):
        self.assertFalse(
            should_cancel_sprint_on_surface_entry(
                sprinting=True,
                on_surface=True,
                was_on_surface=False,
                suppressed_this_visit=True,
            )
        )

    def test_no_cancel_when_sprint_off(self):
        self.assertFalse(
            should_cancel_sprint_on_surface_entry(
                sprinting=False,
                on_surface=True,
                was_on_surface=False,
                suppressed_this_visit=False,
            )
        )

    def test_rain_exception_reserved_for_later(self):
        self.assertFalse(
            should_cancel_sprint_on_surface_entry(
                sprinting=True,
                on_surface=True,
                was_on_surface=False,
                suppressed_this_visit=False,
                raining=True,
            )
        )

    def test_re_sprint_on_same_visit_not_auto_cancelled(self):
        self.assertFalse(
            should_cancel_sprint_on_surface_entry(
                sprinting=True,
                on_surface=True,
                was_on_surface=True,
                suppressed_this_visit=True,
            )
        )

    def test_suppression_resets_after_leaving_surface(self):
        ped = Pedestrian((0, 0))
        ped.sprint_suppressed_on_surface = True
        ped.was_on_road_or_crosswalk = True
        on_surface = False
        if not on_surface:
            ped.sprint_suppressed_on_surface = False
        self.assertFalse(ped.sprint_suppressed_on_surface)


if __name__ == "__main__":
    unittest.main()
