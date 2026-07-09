import unittest
from unittest.mock import patch

from pathwise.geom import Rect
from pathwise.game_draw import draw_traffic_light_overlays


def _road_state(direction: str) -> dict:
    crosswalk = Rect(100, 200, 14, 90) if direction == "vertical" else Rect(80, 300, 120, 14)
    sign = Rect(crosswalk.left - 28, crosswalk.top - 26, 18, 18)
    return {
        "road_rect": crosswalk.inflate(40, 40),
        "direction": direction,
        "crosswalk": crosswalk,
        "sign_rect": sign,
        "light_state": "green",
        "seconds_to_change": 12.5,
        "next_light": "yellow",
    }


class TestTrafficLightOverlays(unittest.TestCase):
    @patch("pathwise.game_draw.shared_traffic_light_batch")
    def test_batched_bulbs_skip_static_housing(self, batch_factory):
        batch = batch_factory.return_value
        batch.draw_bulbs.return_value = 6
        states = [_road_state("vertical"), _road_state("horizontal")]
        view_rect = Rect(0, 0, 800, 600)
        draw_traffic_light_overlays(
            600, states, (0, 0), light_green_duration=20.0, view_rect=view_rect,
            draw_timer_bar=False,
        )
        batch.draw_bulbs.assert_called_once()

    @patch("pathwise.game_draw.shared_traffic_light_batch")
    def test_lights_draw_with_camera_offset(self, batch_factory):
        batch = batch_factory.return_value
        batch.draw_bulbs.return_value = 3
        crosswalk = Rect(500, 400, 14, 90)
        state = {
            "road_rect": crosswalk.inflate(40, 40),
            "direction": "vertical",
            "crosswalk": crosswalk,
            "sign_rect": Rect(crosswalk.left - 28, crosswalk.top - 26, 18, 18),
            "light_state": "red",
            "seconds_to_change": 3.2,
            "next_light": "green",
        }
        camera = (480, 360)
        view_rect = Rect(480, 360, 800, 600)
        draw_traffic_light_overlays(
            600, [state], camera, light_green_duration=20.0, view_rect=view_rect,
            draw_timer_bar=False,
        )
        batch.draw_bulbs.assert_called_once()
        self.assertEqual(batch.draw_bulbs.call_args[0][1], camera)


if __name__ == "__main__":
    unittest.main()
