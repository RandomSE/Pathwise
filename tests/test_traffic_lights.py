import unittest

from analytics.traffic_lights import (
    FORBIDDEN_PERPENDICULAR_PAIRS,
    GREEN_FRAC,
    RED_FRAC,
    YELLOW_FRAC,
    alternation_cycle_length,
    arm_light_state_at,
    cycle_durations,
    light_state_at,
    perpendicular_light_states_at,
    perpendicular_phase_offsets,
    perpendicular_pair_legal,
    protected_turn_light_at,
    seconds_to_change,
    seconds_to_change_arm,
)


class TestTrafficLightTiming(unittest.TestCase):
    def test_cycle_durations_45_10_45(self):
        g, y, r = cycle_durations(20.0)
        self.assertAlmostEqual(g, 9.0)
        self.assertAlmostEqual(y, 2.0)
        self.assertAlmostEqual(r, 9.0)
        self.assertAlmostEqual(g + y + r, 20.0)

    def test_state_fractions_over_cycle(self):
        g, y, r = cycle_durations(100.0)
        cycle = g + y + r
        counts = {"green": 0, "yellow": 0, "red": 0}
        steps = 1000
        for i in range(steps):
            t = (i / steps) * cycle
            counts[light_state_at(t, g, y, r)] += 1
        self.assertAlmostEqual(counts["green"] / steps, GREEN_FRAC, delta=0.02)
        self.assertAlmostEqual(counts["yellow"] / steps, YELLOW_FRAC, delta=0.02)
        self.assertAlmostEqual(counts["red"] / steps, RED_FRAC, delta=0.02)

    def test_perpendicular_arms_opposite(self):
        g, y, r = cycle_durations(20.0)
        alt = alternation_cycle_length(g, y)
        for i in range(400):
            elapsed = (i / 400.0) * alt
            v_state, h_state = perpendicular_light_states_at(elapsed, 0.0, g, y)
            self.assertTrue(
                perpendicular_pair_legal(v_state, h_state),
                msg=f"t={elapsed} v={v_state} h={h_state}",
            )
            if v_state == "green":
                self.assertEqual(h_state, "red", msg=f"t={elapsed}")
            if h_state == "green":
                self.assertEqual(v_state, "red", msg=f"t={elapsed}")
            if v_state == "yellow":
                self.assertEqual(h_state, "red", msg=f"t={elapsed}")
            if h_state == "yellow":
                self.assertEqual(v_state, "red", msg=f"t={elapsed}")

    def test_no_forbidden_perpendicular_pairs_full_cycle(self):
        g, y, r = cycle_durations(20.0)
        alt = alternation_cycle_length(g, y)
        steps = 500
        for i in range(steps):
            elapsed = (i / steps) * alt
            pair = perpendicular_light_states_at(elapsed, 0.0, g, y)
            self.assertNotIn(pair, FORBIDDEN_PERPENDICULAR_PAIRS, msg=f"t={elapsed}")

    def test_seconds_to_change_counts_down(self):
        g, y, r = cycle_durations(20.0)
        state, secs, nxt = seconds_to_change(0.0, 0.0, g, y, r)
        self.assertEqual(state, "green")
        self.assertAlmostEqual(secs, g)
        self.assertEqual(nxt, "yellow")

    def test_protected_turn_matches_approach_straight_signal(self):
        g, y, r = cycle_durations(20.0)
        elapsed = 0.0
        straight = arm_light_state_at(
            elapsed, 0.0, arm_vertical=True, green_s=g, yellow_s=y
        )
        turn_state, _ = protected_turn_light_at(elapsed, 0.0, g, y, r, arm_vertical=True)
        self.assertEqual(turn_state, straight)

    def test_protected_turn_red_when_approach_red(self):
        g, y, r = cycle_durations(20.0)
        alt = alternation_cycle_length(g, y)
        elapsed = g + y + 0.1
        while elapsed < alt:
            straight = arm_light_state_at(
                elapsed, 0.0, arm_vertical=True, green_s=g, yellow_s=y
            )
            if straight == "red":
                break
            elapsed += 0.05
        turn_state, _ = protected_turn_light_at(
            elapsed, 0.0, g, y, r, arm_vertical=True
        )
        self.assertEqual(straight, "red")
        self.assertEqual(turn_state, "red")


if __name__ == "__main__":
    unittest.main()
