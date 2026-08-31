"""Tests for rainy roads gameplay hooks."""

from __future__ import annotations

import unittest
import unittest.mock

from pathwise.geom import Rect
from pathwise.modifiers.registry import ModifierContext
from pathwise.modifiers import rainy_roads
from pathwise.modifiers.weather_visuals import RainParticlePool
from pathwise.pedestrian import Pedestrian
from pathwise.session_seed import decode_recruiter_seed


class TestRainDrawPoints(unittest.TestCase):
    @unittest.mock.patch("pathwise.modifiers.weather_visuals.arcade.draw_lines")
    def test_draw_lines_uses_flat_xy_pairs(self, mock_draw_lines):
        pool = RainParticlePool(seed=834941, cap=8)
        pool.draw(800, 600, Rect(0, 0, 800, 600), (0, 0))
        mock_draw_lines.assert_called_once()
        points = mock_draw_lines.call_args[0][0]
        self.assertGreaterEqual(len(points), 2)
        for x, y in points:
            self.assertIsInstance(x, (int, float))
            self.assertIsInstance(y, (int, float))

    def test_user_rainy_seed_decodes(self):
        payload = decode_recruiter_seed("911001834941")
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.map_seed, 834941)
        self.assertIn("rainy_roads", payload.modifiers)


class TestRainyBraking(unittest.TestCase):
    def test_effective_brake_weaker_when_active(self):
        rainy_roads.install_for_round(
            ModifierContext(frozenset({"rainy_roads"}), session_base_seed=1, round_index=1)
        )
        self.assertLess(
            rainy_roads.effective_brake_strength(0.42),
            0.42,
        )
        rainy_roads.install_for_round(ModifierContext(frozenset(), session_base_seed=1, round_index=1))
        self.assertEqual(rainy_roads.effective_brake_strength(0.42), 0.42)


class TestCrosswalkOvershoot(unittest.TestCase):
    def test_overshoot_roll_is_deterministic(self):
        ctx = ModifierContext(frozenset({"rainy_roads"}), session_base_seed=42, round_index=1)
        rainy_roads.install_for_round(ctx)
        a = rainy_roads.crosswalk_overshoot_enabled(spawn_id=3, crosswalk_key=7)
        b = rainy_roads.crosswalk_overshoot_enabled(spawn_id=3, crosswalk_key=7)
        c = rainy_roads.crosswalk_overshoot_enabled(spawn_id=4, crosswalk_key=7)
        self.assertEqual(a, b)
        self.assertIsInstance(a, bool)

    def test_no_overshoot_without_modifier(self):
        rainy_roads.install_for_round(ModifierContext(frozenset(), session_base_seed=42, round_index=1))
        self.assertFalse(rainy_roads.crosswalk_overshoot_enabled(spawn_id=1, crosswalk_key=1))


class TestRainSlip(unittest.TestCase):
    def setUp(self):
        rainy_roads.install_for_round(
            ModifierContext(frozenset({"rainy_roads"}), session_base_seed=100, round_index=1)
        )

    def test_slip_chance_ramps_from_five_to_fifteen(self):
        self.assertAlmostEqual(rainy_roads.slip_chance_for_second(0), 0.05)
        self.assertAlmostEqual(rainy_roads.slip_chance_for_second(10), 0.06)
        self.assertAlmostEqual(rainy_roads.slip_chance_for_second(100), 0.15)
        self.assertAlmostEqual(rainy_roads.slip_chance_for_second(200), 0.15)
        self.assertAlmostEqual(rainy_roads.SLIP_CHANCE_BASE, 0.05)
        self.assertAlmostEqual(rainy_roads.SLIP_CHANCE_PER_SECOND, 0.05)

    def test_time_limit_extended(self):
        rainy_roads.install_for_round(
            ModifierContext(frozenset({"rainy_roads"}), session_base_seed=1, round_index=1)
        )
        self.assertEqual(rainy_roads.scaled_time_limit(60), 90.0)
        rainy_roads.install_for_round(ModifierContext(frozenset(), session_base_seed=1, round_index=1))
        self.assertEqual(rainy_roads.scaled_time_limit(60), 60.0)

    def test_slip_stun_blocks_movement(self):
        ped = Pedestrian((100, 100))
        ped.begin_slip_stun(elapsed=1.0, impulse_dx=10, impulse_dy=0)
        keys = unittest.mock.MagicMock()
        keys.pressed.return_value = True

        before_x = ped.rect.x
        ped.update(keys, elapsed=1.5)
        self.assertEqual(ped.rect.x, before_x)
        self.assertEqual(ped.draw_angle, rainy_roads.SLIP_SPRITE_ANGLE)

    def test_slip_respects_player_override(self):
        self.assertFalse(rainy_roads.should_disable_player_yield(slip_stunned=False))
        self.assertTrue(rainy_roads.should_disable_player_yield(slip_stunned=True))

    def test_bucket_slip_roll_deterministic(self):
        tracker = rainy_roads.RainSlipTracker()
        tracker._sprinted_in_bucket[0] = True
        first = tracker._slip_roll_for_bucket(0)
        second = tracker._slip_roll_for_bucket(0)
        self.assertEqual(first, second)

    def test_slip_impulse_uses_facing_not_move_speed(self):
        px = rainy_roads.SLIP_IMPULSE_PX
        walk = rainy_roads.slip_impulse_delta(2.0, 0.0)
        sprint_2x = rainy_roads.slip_impulse_delta(4.0, 0.0)
        self.assertEqual(walk, (px, 0))
        self.assertEqual(sprint_2x, (px, 0))
        down = rainy_roads.slip_impulse_delta(0.0, 4.0)
        self.assertEqual(down, (0, px))


if __name__ == "__main__":
    unittest.main()
