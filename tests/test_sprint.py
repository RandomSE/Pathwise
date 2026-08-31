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

    def _move_delta(self, *, sprint: bool, frames: int = 8) -> int:
        ped = Pedestrian((400, 400))
        ped.sprint_enabled = sprint
        keys = KeyState()
        keys.press(KEY_RIGHT)
        x0 = ped.rect.x
        for _ in range(frames):
            ped.update(keys)
        return ped.rect.x - x0

    def _install(self, ids: frozenset[str]):
        from pathwise.modifiers import high_speed, highway, lag, old, variable_speed_zones
        from pathwise.modifiers.registry import ModifierContext

        ctx = ModifierContext(ids)
        high_speed.install_for_round(ctx)
        lag.install_for_round(ctx)
        old.install_for_round(ctx)
        highway.install_for_round(ctx)
        variable_speed_zones.install_for_round(ctx)
        self.addCleanup(lambda: high_speed.install_for_round(ModifierContext(frozenset())))
        self.addCleanup(lambda: lag.install_for_round(ModifierContext(frozenset())))
        self.addCleanup(lambda: old.install_for_round(ModifierContext(frozenset())))
        self.addCleanup(lambda: highway.install_for_round(ModifierContext(frozenset())))
        self.addCleanup(
            lambda: variable_speed_zones.install_for_round(ModifierContext(frozenset()))
        )
        return ctx

    def test_sprint_doubles_walk_under_high_speed(self):
        self._install(frozenset({"high_speed"}))
        walk = self._move_delta(sprint=False)
        run = self._move_delta(sprint=True)
        self.assertGreater(walk, 0)
        self.assertEqual(run, 2 * walk)

    def test_sprint_doubles_walk_under_old_and_high_speed(self):
        self._install(frozenset({"old", "high_speed"}))
        walk = self._move_delta(sprint=False, frames=16)
        run = self._move_delta(sprint=True, frames=16)
        self.assertGreater(walk, 0)
        self.assertEqual(run, 2 * walk)

    def test_sprint_doubles_walk_under_lag_physics_scale(self):
        from pathwise.modifiers import lag

        self._install(frozenset({"lag"}))
        lag.begin_frame(0.1)
        walk = self._move_delta(sprint=False)
        run = self._move_delta(sprint=True)
        self.assertGreater(walk, 0)
        self.assertEqual(run, 2 * walk)

    def test_highway_and_zones_do_not_change_player_speed(self):
        baseline = self._move_delta(sprint=True)
        self._install(frozenset({"highway", "variable_speed_zones"}))
        stacked = self._move_delta(sprint=True)
        self.assertEqual(stacked, baseline)

    def test_sprint_is_not_slower_than_walk_when_high_speed_clips_world_edge(self):
        from pathwise.geom import Rect
        from pathwise.round_frame import constrain_player_to_world

        world = Rect(0, 0, 200, 200)
        # 28px body, 2px of room: walk at 2x (2px) stays in, sprint at 2x (4px) exits.
        walk_rect = Rect(170, 80, 28, 28)
        walk_prev = walk_rect.topleft
        walk_rect.x += 2
        constrain_player_to_world(walk_rect, walk_prev, world)
        walk_delta = walk_rect.x - walk_prev[0]

        run_rect = Rect(170, 80, 28, 28)
        run_prev = run_rect.topleft
        run_rect.x += 4
        constrain_player_to_world(run_rect, run_prev, world)
        run_delta = run_rect.x - run_prev[0]

        self.assertGreater(walk_delta, 0)
        self.assertGreaterEqual(run_delta, walk_delta)


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
