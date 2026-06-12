"""Coverage for pathwise.sprites drawing helpers."""

import unittest
from unittest.mock import MagicMock, patch

from pathwise.geom import Rect


class TestSpriteDrawingHelpers(unittest.TestCase):
    def test_rgba_and_draw_helpers(self):
        from pathwise import sprites

        self.assertEqual(len(sprites._rgba((1, 2, 3))), 4)
        self.assertEqual(sprites._rgba((1, 2, 3, 4)), (1, 2, 3, 4))
        img, draw = sprites._new_canvas(10, 10)
        self.assertIsNone(sprites._rect_xyxy(0, 0, 0, 5))
        sprites._draw_round_rect(draw, (1, 1, 8, 8), fill=(1, 2, 3), radius=2)
        sprites._draw_round_rect(draw, (1, 1, 8, 8), outline=(1, 2, 3), width=1)
        sprites._draw_round_rect(draw, None)

    def test_signal_corners_all_quadrants(self):
        from pathwise.sprites import _signal_corner, _draw_turn_signal_dots

        img, draw = __import__("pathwise.sprites", fromlist=["_new_canvas"])._new_canvas(60, 30)
        _draw_turn_signal_dots(draw, 60, 30, vertical=False)
        for vertical in (False, True):
            for direction in (-1, 1):
                for side in (-1, 1):
                    pos = _signal_corner(60, 30, vertical, direction, side)
                    self.assertEqual(len(pos), 2)


if __name__ == "__main__":
    unittest.main()
