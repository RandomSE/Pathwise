"""Grid pathfinding: BFS solvability and A* time-budget estimates."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

PED_SPEED = 1.0
WALK_CELL_COST_S = 0.55
CROSS_ROAD_COST_S = 2.2


@dataclass(frozen=True)
class Cell:
    col: int
    row: int


def _neighbors(cell: Cell, cols: int, rows: int) -> list[Cell]:
    result = []
    if cell.col > 0:
        result.append(Cell(cell.col - 1, cell.row))
    if cell.col < cols:
        result.append(Cell(cell.col + 1, cell.row))
    if cell.row > 0:
        result.append(Cell(cell.col, cell.row - 1))
    if cell.row < rows:
        result.append(Cell(cell.col, cell.row + 1))
    return result


def bfs_solvable(start: Cell, goal: Cell, cols: int, rows: int) -> bool:
    if start == goal:
        return True
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for nxt in _neighbors(current, cols, rows):
            if nxt in seen:
                continue
            if nxt == goal:
                return True
            seen.add(nxt)
            queue.append(nxt)
    return False


def _heuristic(a: Cell, b: Cell) -> float:
    return (abs(a.col - b.col) + abs(a.row - b.row)) * WALK_CELL_COST_S


def _edge_cost(a: Cell, b: Cell, crossing_wait_s: float) -> float:
    cost = WALK_CELL_COST_S
    if a.col != b.col:
        cost += CROSS_ROAD_COST_S + crossing_wait_s * 0.55
    if a.row != b.row:
        cost += CROSS_ROAD_COST_S + crossing_wait_s * 0.55
    return cost


def astar_travel_time(
    start: Cell,
    goal: Cell,
    cols: int,
    rows: int,
    crossing_wait_s: float,
) -> float | None:
    """Estimated seconds along shortest time-aware path (None if unreachable)."""
    if not bfs_solvable(start, goal, cols, rows):
        return None

    open_heap: list[tuple[float, int, float, Cell]] = []
    tie = 0
    heapq.heappush(open_heap, (0.0, tie, 0.0, start))
    g_score: dict[Cell, float] = {start: 0.0}

    while open_heap:
        _, _, g, current = heapq.heappop(open_heap)
        if g > g_score.get(current, math.inf):
            continue
        if current == goal:
            return g

        for nxt in _neighbors(current, cols, rows):
            tentative = g + _edge_cost(current, nxt, crossing_wait_s)
            if tentative < g_score.get(nxt, math.inf):
                g_score[nxt] = tentative
                f = tentative + _heuristic(nxt, goal)
                tie += 1
                heapq.heappush(open_heap, (f, tie, tentative, nxt))

    return None
