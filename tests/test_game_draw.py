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
    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw._entity_batch.draw_entities")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    def test_vertical_and_horizontal_states_draw_without_error(
        self,
        _rect_fill,
        _circle,
        _text_cls,
        _entity_batch,
        _outline,
    ):
        states = [_road_state("vertical"), _road_state("horizontal")]
        view_rect = Rect(0, 0, 800, 600)
        draw_traffic_light_overlays(
            600, states, (0, 0), light_green_duration=20.0, view_rect=view_rect
        )

    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    def test_lights_draw_with_camera_offset(
        self,
        _rect_fill,
        circle_world,
        _text_cls,
        _outline,
    ):
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
            600, [state], camera, light_green_duration=20.0, view_rect=view_rect
        )
        self.assertGreater(circle_world.call_count, 0)
        args = circle_world.call_args_list[0][0]
        self.assertEqual(args[2], camera)

    @patch("pathwise.game_draw.draw_sim_rect_outline")
    @patch("pathwise.game_draw.arcade.Text")
    @patch("pathwise.game_draw.draw_sim_circle_filled_world")
    @patch("pathwise.game_draw.draw_sim_rect_filled")
    def test_turn_light_drawn_when_protected_green(
        self,
        _rect_fill,
        circle_world,
        _text_cls,
        _outline,
    ):
        crosswalk = Rect(100, 200, 14, 90)
        state = _road_state("vertical")
        state["light_state"] = "red"
        state["turn_light_state"] = "green"
        view_rect = Rect(0, 0, 800, 600)
        draw_traffic_light_overlays(
            600, [state], (0, 0), light_green_duration=20.0, view_rect=view_rect
        )
        self.assertGreaterEqual(circle_world.call_count, 4)


if __name__ == "__main__":
    unittest.main()
