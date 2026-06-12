import unittest

from analytics.traffic_lights import (
    GREEN_FRAC,
    RED_FRAC,
    YELLOW_FRAC,
    cycle_durations,
    light_state_at,
    perpendicular_arm_offset,
    perpendicular_phase_offsets,
    protected_turn_light_at,
    seconds_to_change,
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
        v_off, h_off = perpendicular_phase_offsets(0.0, g, y)
        for t in range(200):
            elapsed = t * 0.1
            v_state = light_state_at(elapsed + v_off, g, y, r)
            h_state = light_state_at(elapsed + h_off, g, y, r)
            if v_state == "green":
                self.assertNotEqual(h_state, "green", msg=f"t={elapsed}")
            if h_state == "green":
                self.assertNotEqual(v_state, "green", msg=f"t={elapsed}")

    def test_seconds_to_change_counts_down(self):
        g, y, r = cycle_durations(20.0)
        state, secs, nxt = seconds_to_change(0.0, 0.0, g, y, r)
        self.assertEqual(state, "green")
        self.assertAlmostEqual(secs, g)
        self.assertEqual(nxt, "yellow")

    def test_protected_turn_green_when_perpendicular_red(self):
        g, y, r = cycle_durations(20.0)
        v_off, h_off = perpendicular_phase_offsets(0.0, g, y)
        elapsed = 0.0
        perp_state = light_state_at(elapsed + h_off, g, y, r)
        self.assertEqual(perp_state, "red")
        turn_state, turn_secs = protected_turn_light_at(elapsed, v_off, g, y, r)
        self.assertEqual(turn_state, "green")
        self.assertGreater(turn_secs, 0.0)

    def test_protected_turn_red_when_perpendicular_green(self):
        g, y, r = cycle_durations(20.0)
        v_off, h_off = perpendicular_phase_offsets(0.0, g, y)
        elapsed = g + 0.5
        perp_state = light_state_at(elapsed + h_off, g, y, r)
        self.assertEqual(perp_state, "green")
        turn_state, _ = protected_turn_light_at(elapsed, v_off, g, y, r)
        self.assertEqual(turn_state, "red")


if __name__ == "__main__":
    unittest.main()
