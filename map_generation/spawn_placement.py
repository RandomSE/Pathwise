"""Seed-deterministic perimeter spawn and standardized goal placement."""

from __future__ import annotations

import random
from dataclasses import dataclass

from map_generation.pathfinding import Cell, manhattan_cells, opposite_edge

SPAWN_RNG_SALT = 0x5A0A0E51

TOP, RIGHT, BOTTOM, LEFT = 0, 1, 2, 3
_EDGE_NAMES = ("top", "right", "bottom", "left")


def spawn_rng_for_attempt(seed: int, attempt: int) -> random.Random:
    return random.Random((int(seed) + int(attempt)) ^ SPAWN_RNG_SALT)


def min_spawn_goal_manhattan(n_v: int, n_h: int) -> int:
    return max(2, (n_v + n_h) // 3)


def _cells_on_edge(edge: int, n_v: int, n_h: int) -> list[tuple[int, int]]:
    if edge == TOP:
        return [(col, 0) for col in range(n_v + 1)]
    if edge == RIGHT:
        return [(n_v, row) for row in range(n_h + 1)]
    if edge == BOTTOM:
        return [(col, n_h) for col in range(n_v + 1)]
    return [(0, row) for row in range(n_h + 1)]


def _cell_on_edge(edge: int, rng: random.Random, n_v: int, n_h: int) -> tuple[int, int]:
    cells = _cells_on_edge(edge, n_v, n_h)
    return cells[rng.randrange(len(cells))]


def _anti_spawn_corner_on_edge(
    goal_edge: int, start_col: int, start_row: int, n_v: int, n_h: int
) -> tuple[int, int]:
    if goal_edge == TOP:
        return n_v - start_col, 0
    if goal_edge == RIGHT:
        return n_v, n_h - start_row
    if goal_edge == BOTTOM:
        return n_v - start_col, n_h
    return 0, n_h - start_row


def _goal_on_edge(
    goal_edge: int,
    start_col: int,
    start_row: int,
    rng: random.Random,
    n_v: int,
    n_h: int,
    unpredictability: float,
) -> tuple[int, int]:
    base_col, base_row = _anti_spawn_corner_on_edge(
        goal_edge, start_col, start_row, n_v, n_h
    )
    k_max = 1 + int(unpredictability * max(1, min(n_v, n_h) // 2))
    jitter = rng.randint(-k_max, k_max)

    if goal_edge in (TOP, BOTTOM):
        col = max(0, min(n_v, base_col + jitter))
        return col, base_row
    row = max(0, min(n_h, base_row + jitter))
    return base_col, row


@dataclass(frozen=True)
class SpawnPlacement:
    start_cell: Cell
    goal_cell: Cell
    spawn_edge: int
    goal_edge: int

    @property
    def metadata(self) -> dict:
        return {
            "spawn_edge": _EDGE_NAMES[self.spawn_edge],
            "goal_edge": _EDGE_NAMES[self.goal_edge],
            "start_col": self.start_cell.col,
            "start_row": self.start_cell.row,
            "goal_col": self.goal_cell.col,
            "goal_row": self.goal_cell.row,
        }


def pick_spawn_and_goal(
    rng: random.Random,
    n_v: int,
    n_h: int,
    unpredictability: float,
) -> SpawnPlacement:
    edge = rng.randrange(4)
    start_col, start_row = _cell_on_edge(edge, rng, n_v, n_h)
    goal_edge = opposite_edge(edge)
    goal_col, goal_row = _goal_on_edge(
        goal_edge, start_col, start_row, rng, n_v, n_h, unpredictability
    )
    return SpawnPlacement(
        start_cell=Cell(start_col, start_row),
        goal_cell=Cell(goal_col, goal_row),
        spawn_edge=edge,
        goal_edge=goal_edge,
    )


def placement_meets_distance(
    placement: SpawnPlacement, n_v: int, n_h: int
) -> bool:
    if placement.start_cell == placement.goal_cell:
        return False
    return (
        manhattan_cells(placement.start_cell, placement.goal_cell)
        >= min_spawn_goal_manhattan(n_v, n_h)
    )
