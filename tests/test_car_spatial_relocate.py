import unittest

from pathwise.geom import Rect


class _ShellCar:
    """Minimal car stub for spatial-index tests."""

    def __init__(self, shell: Rect):
        self._collision_shell = shell
        self._spatial_cell_keys: tuple = ()
        self._spatial_stamp = 0
        self._alive = True

    def alive(self):
        return self._alive


class TestCarSpatialRelocate(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        self.idx = game.CarSpatialIndex(cell_size=64)

    def test_relocate_moves_car_between_cells(self):
        car = _ShellCar(Rect(10, 10, 20, 20))
        self.idx.rebuild([car])
        self.assertIn(car, self.idx.nearby(Rect(0, 0, 40, 40), 0, []))
        car._collision_shell = Rect(210, 210, 20, 20)
        self.idx.relocate_car(car)
        self.assertEqual(car._spatial_cell_keys, ((3, 3),))
        self.assertNotIn(car, self.idx._cells.get((0, 0), ()))
        self.assertIn(car, self.idx._cells.get((3, 3), ()))
        self.assertIn(car, self.idx.nearby(Rect(200, 200, 40, 40), 0, []))

    def test_relocate_removes_dead_car(self):
        car = _ShellCar(Rect(10, 10, 20, 20))
        self.idx.rebuild([car])
        car._alive = False
        self.idx.relocate_car(car)
        scratch: list = []
        self.assertNotIn(car, self.idx.nearby(Rect(0, 0, 80, 80), 0, scratch))

    def test_rebuild_tracks_cell_keys(self):
        car = _ShellCar(Rect(10, 10, 20, 20))
        self.idx.rebuild([car])
        self.assertGreater(len(car._spatial_cell_keys), 0)


if __name__ == "__main__":
    unittest.main()
