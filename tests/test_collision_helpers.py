import unittest

from pathwise.geom import Rect
from pathwise.map import make_rectangle
from pathwise.sprites import car_collision_rect, car_collision_rect_turn, player_body_hitbox


class TestMakeRectangle(unittest.TestCase):
    def test_returns_geom_rect(self):
        r = make_rectangle(10, 20, 30, 40)
        self.assertIsInstance(r, Rect)
        self.assertEqual(r.topleft, (10, 20))
        self.assertEqual(r.size, (30, 40))


class TestPlayerBodyHitbox(unittest.TestCase):
    def test_tighter_than_full_square(self):
        world = Rect(100, 200, 28, 28)
        hitbox = player_body_hitbox(world)
        self.assertLess(hitbox.width, world.width)
        self.assertLess(hitbox.height, world.height)
        self.assertTrue(world.contains(hitbox))

    def test_degenerate_rect_returns_copy(self):
        empty = Rect(5, 5, 0, 0)
        self.assertEqual(player_body_hitbox(empty), empty)


class TestCarCollisionRect(unittest.TestCase):
    def test_horizontal_inset(self):
        rect = Rect(0, 0, 60, 30)
        shell = car_collision_rect(rect, vertical=False)
        self.assertEqual(shell.topleft, (1, 5))
        self.assertEqual(shell.size, (58, 20))

    def test_vertical_inset(self):
        rect = Rect(0, 0, 30, 60)
        shell = car_collision_rect(rect, vertical=True)
        self.assertEqual(shell.topleft, (5, 1))
        self.assertEqual(shell.size, (20, 58))


class TestCarCollisionRectTurn(unittest.TestCase):
    def test_shrinks_rect(self):
        rect = Rect(0, 0, 40, 40)
        shell = car_collision_rect_turn(rect)
        self.assertLess(shell.width, rect.width)
        self.assertLess(shell.height, rect.height)
        self.assertTrue(rect.contains(shell))


class TestGeneratorRectTypes(unittest.TestCase):
    def test_spawn_probe_uses_geom_rect(self):
        from map_generation.generator import _spawn_clear
        from pathwise.map import Road

        roads = [Road(Rect(50, 50, 90, 200), "vertical")]
        self.assertFalse(_spawn_clear(95, 120, roads))
        self.assertTrue(_spawn_clear(10, 10, roads))
