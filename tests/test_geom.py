import unittest

from pathwise.geom import Rect, rect_overlap_area


class TestRectBasics(unittest.TestCase):
    def test_constructor_and_aliases(self):
        r = Rect(10, 20, 30, 40)
        self.assertEqual(r.left, 10)
        self.assertEqual(r.top, 20)
        self.assertEqual(r.width, 30)
        self.assertEqual(r.w, 30)
        self.assertEqual(r.height, 40)
        self.assertEqual(r.h, 40)
        self.assertEqual(r.right, 40)
        self.assertEqual(r.bottom, 60)
        self.assertEqual(r.topleft, (10, 20))
        self.assertEqual(r.size, (30, 40))

    def test_copy_from_rect(self):
        original = Rect(1, 2, 3, 4)
        clone = Rect(original)
        self.assertEqual(clone, original)
        clone.x = 9
        self.assertNotEqual(clone, original)

    def test_center_setters(self):
        r = Rect(0, 0, 10, 10)
        r.center = (50, 60)
        self.assertEqual(r.center, (50, 60))
        r.centerx = 100
        r.centery = 200
        self.assertEqual(r.centerx, 100)
        self.assertEqual(r.centery, 200)

    def test_edge_setters(self):
        r = Rect(0, 0, 20, 20)
        r.right = 40
        r.bottom = 50
        self.assertEqual((r.left, r.top, r.right, r.bottom), (20, 30, 40, 50))


class TestRectGeometry(unittest.TestCase):
    def test_move(self):
        r = Rect(5, 5, 10, 10)
        moved = r.move(3, -2)
        self.assertEqual(moved.topleft, (8, 3))
        self.assertEqual(r.topleft, (5, 5))

    def test_inflate(self):
        r = Rect(10, 10, 20, 20)
        inflated = r.inflate(10, 10)
        self.assertEqual(inflated, Rect(5, 5, 30, 30))
        shrunk = r.inflate(-10, -10)
        self.assertEqual(shrunk, Rect(15, 15, 10, 10))

    def test_inflate_ip(self):
        r = Rect(0, 0, 10, 10)
        r.inflate_ip(10, 10)
        self.assertEqual(r, Rect(-5, -5, 20, 20))

    def test_colliderect_overlap_and_touch(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(5, 5, 10, 10)
        c = Rect(10, 0, 5, 5)
        self.assertTrue(a.colliderect(b))
        self.assertFalse(a.colliderect(c))

    def test_collidepoint(self):
        r = Rect(10, 10, 20, 20)
        self.assertTrue(r.collidepoint(15, 15))
        self.assertTrue(r.collidepoint((15, 15)))
        self.assertFalse(r.collidepoint(30, 30))

    def test_contains(self):
        outer = Rect(0, 0, 100, 100)
        inner = Rect(10, 10, 20, 20)
        partial = Rect(90, 90, 20, 20)
        self.assertTrue(outer.contains(inner))
        self.assertFalse(outer.contains(partial))

    def test_clip_no_overlap(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(20, 20, 10, 10)
        # Zero-area clip at clamped corner, not origin.
        self.assertEqual(a.clip(b), Rect(20, 20, 0, 0))

    def test_clip_partial_overlap(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(5, 5, 10, 10)
        self.assertEqual(a.clip(b), Rect(5, 5, 5, 5))

    def test_union(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(5, 5, 10, 10)
        self.assertEqual(a.union(b), Rect(0, 0, 15, 15))


class TestRectClipBehavior(unittest.TestCase):
    def test_clip_zero_area_at_clamped_corner(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(20, 20, 10, 10)
        self.assertEqual(a.clip(b), Rect(20, 20, 0, 0))

    def test_invalid_constructor_raises(self):
        with self.assertRaises(TypeError):
            Rect(1, 2, 3)

    def test_collidepoint_tuple_and_pair(self):
        r = Rect(0, 0, 10, 10)
        self.assertTrue(r.collidepoint((5, 5)))
        self.assertTrue(r.collidepoint(5, 5))
        with self.assertRaises(TypeError):
            r.collidepoint(1, 2, 3)

    def test_clamp_ip_branches(self):
        outer = Rect(0, 0, 100, 100)
        inner = Rect(-10, -10, 120, 120)
        inner.clamp_ip(outer)
        self.assertEqual(inner.left, outer.left)
        inner = Rect(90, 90, 20, 20)
        inner.clamp_ip(outer)
        self.assertEqual(inner.right, outer.right)


class TestPedestrianMovement(unittest.TestCase):
    def test_all_direction_keys(self):
        from pathwise.input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
        from pathwise.pedestrian import Pedestrian

        ped = Pedestrian((100, 100))
        start_y = ped.rect.y
        keys = KeyState()
        keys.press(KEY_LEFT)
        ped.update(keys)
        keys.release(KEY_LEFT)
        keys.press(KEY_DOWN)
        ped.update(keys)
        self.assertGreater(ped.rect.y, start_y)


class TestPathwiseRenderHelpers(unittest.TestCase):
    def test_draw_sprite_asset(self):
        from unittest.mock import MagicMock, patch

        from pathwise.geom import Rect
        from pathwise.pathwise_render import draw_sprite_asset

        asset = MagicMock()
        asset.texture = MagicMock()
        with patch("pathwise.pathwise_render.draw_sim_texture_rect") as draw_tex:
            draw_sprite_asset(asset, Rect(0, 0, 20, 20), (0, 0), 600)
            draw_tex.assert_called_once()


class TestRectOverlapArea(unittest.TestCase):
    def test_disjoint(self):
        self.assertEqual(rect_overlap_area(Rect(0, 0, 10, 10), Rect(30, 0, 10, 10)), 0)

    def test_overlap(self):
        self.assertEqual(rect_overlap_area(Rect(0, 0, 10, 10), Rect(5, 5, 10, 10)), 25)


class TestPathwiseWindowImport(unittest.TestCase):
    def test_window_class_imports_without_running_loop(self):
        from pathwise.pathwise_window import PathwiseWindow, SIM_ORIGIN, WIDTH, HEIGHT

        self.assertEqual(SIM_ORIGIN, "top_left_y_down")
        self.assertEqual(WIDTH, 800)
        self.assertEqual(HEIGHT, 600)
        self.assertTrue(issubclass(PathwiseWindow, __import__("arcade").Window))
