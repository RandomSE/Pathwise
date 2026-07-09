"""Unit tests for batched traffic-signal bulb drawing."""

import unittest
from unittest.mock import patch

import arcade

from pathwise.geom import Rect
from pathwise.traffic_light_batch import TrafficLightBatch


def _state(direction: str, light: str = "green") -> dict:
    crosswalk = Rect(100, 200, 14, 90) if direction == "vertical" else Rect(80, 300, 120, 14)
    return {
        "direction": direction,
        "crosswalk": crosswalk,
        "light_state": light,
    }


class TestTrafficLightBatch(unittest.TestCase):
    @patch.object(arcade.SpriteList, "draw")
    def test_single_sprite_list_draw_per_frame(self, draw):
        batch = TrafficLightBatch()
        states = [_state("vertical"), _state("horizontal")]
        count = batch.draw_bulbs(
            states,
            (0, 0),
            600,
            Rect(0, 0, 800, 600),
            housing_for_state=lambda cw, direction, approach: Rect(
                cw.left - 30, cw.top, 22, 56
            ),
        )
        draw.assert_called_once()
        self.assertEqual(count, 6)

    @patch.object(arcade.SpriteList, "draw")
    def test_culls_offscreen_signals(self, draw):
        batch = TrafficLightBatch()
        offscreen = _state("vertical")
        offscreen["crosswalk"] = Rect(9000, 9000, 14, 90)
        count = batch.draw_bulbs(
            [offscreen],
            (0, 0),
            600,
            Rect(0, 0, 800, 600),
            housing_for_state=lambda cw, direction, approach: Rect(
                cw.left - 30, cw.top, 22, 56
            ),
        )
        draw.assert_not_called()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
