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

if __name__ == "__main__":
    unittest.main()
