"""Sprint toggle, speed, and risky movement reasons."""

import unittest

from pathwise.input_keys import KEY_RIGHT, KeyState
from pathwise.pedestrian import Pedestrian
from pathwise.sim_constants import PEDESTRIAN_SPEED, SPRINT_SPEED_MULT
from pathwise.sprint import effective_pedestrian_speed, sprint_risk_reason


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

    def test_old_walk_speed_still_moves_via_subpixel_carry(self):
        from pathwise.modifiers.registry import ModifierContext
        from pathwise.modifiers import old, time_pressure

        old.install_for_round(ModifierContext(frozenset({"old", "time_pressure"})))
        time_pressure.install_for_round(
            ModifierContext(frozenset({"old", "time_pressure"})),
            preset_id="normal",
        )
        self.addCleanup(lambda: old.install_for_round(ModifierContext(frozenset())))
        self.addCleanup(
            lambda: time_pressure.install_for_round(ModifierContext(frozenset()))
        )
        ped = Pedestrian((100, 100))
        keys = KeyState()
        keys.press(KEY_RIGHT)
        x0 = ped.rect.x
        for _ in range(4):
            ped.update(keys)
        self.assertGreater(ped.rect.x, x0)

    def test_pedestrian_has_no_crosswalk_suppression_state(self):
        ped = Pedestrian((0, 0))
        self.assertFalse(hasattr(ped, "sprint_suppressed_on_crosswalk"))
        self.assertFalse(hasattr(ped, "was_on_crosswalk"))
        self.assertFalse(hasattr(ped, "was_on_road"))


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


if __name__ == "__main__":
    unittest.main()
