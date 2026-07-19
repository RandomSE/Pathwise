"""Smoke test: rain overlay draw under a real Arcade GL context."""

from __future__ import annotations

import unittest

import arcade

from pathwise.geom import Rect
from pathwise.modifiers.weather_visuals import (
    draw_weather_overlay,
    install_rain_visuals,
    reset_rain_visuals,
)


class TestWeatherDrawSmoke(unittest.TestCase):
    def test_draw_weather_overlay_does_not_raise(self):
        window = arcade.Window(640, 480, "rain_smoke", visible=False)
        try:
            install_rain_visuals(session_base_seed=834941, round_index=1)
            window.switch_to()
            draw_weather_overlay(
                sim_width=640,
                sim_height=480,
                view_rect=Rect(0, 0, 640, 480),
                camera_offset=(0, 0),
                elapsed=1.0,
            )
        finally:
            reset_rain_visuals()
            window.close()


if __name__ == "__main__":
    unittest.main()
