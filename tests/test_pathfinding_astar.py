"""A* route estimate admissibility / consistency checks."""

from __future__ import annotations

import unittest

from map_generation.pathfinding import (
    Cell,
    _edge_cost,
    _heuristic,
    sprint_cell_cost_s,
)


class TestAStarAdmissibility(unittest.TestCase):
    def test_heuristic_never_exceeds_edge_plus_neighbor_heuristic(self):
        """Triangle inequality for consistent heuristic under sprint edge costs."""
        stride = 120.0
        wait = 3.0
        a = Cell(0, 0)
        goal = Cell(3, 2)
        for nxt in (Cell(1, 0), Cell(0, 1)):
            cost = _edge_cost(a, nxt, wait, stride)
            self.assertGreaterEqual(
                cost + _heuristic(nxt, goal, stride),
                _heuristic(a, goal, stride),
            )

    def test_heuristic_uses_same_sidewalk_rate_as_edges(self):
        stride = 96.0
        a = Cell(0, 0)
        b = Cell(2, 0)
        sprint = sprint_cell_cost_s(stride)
        self.assertAlmostEqual(_heuristic(a, b, stride), 2 * sprint)
        # Edge may only add crossing wait; sidewalk term matches heuristic step.
        self.assertGreaterEqual(_edge_cost(a, Cell(1, 0), 0.0, stride), sprint)


if __name__ == "__main__":
    unittest.main()
