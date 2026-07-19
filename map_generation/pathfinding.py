"""Grid pathfinding: BFS solvability and A* time-budget estimates."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

# Pedestrian ~60 px/s at PEDESTRIAN_SPEED=1, 60 FPS; sprint is 2× on sidewalks.
PX_PER_SECOND = 60.0
SPRINT_SPEED_MULT = 2.0
CROSSING_BASE_S = 1.8
MODERATE_SAFE_WAIT_FRAC = 0.35


@dataclass(frozen=True)
class Cell:
    col: int
    row: int


TOP_EDGE, RIGHT_EDGE, BOTTOM_EDGE, LEFT_EDGE = 0, 1, 2, 3


def opposite_edge(edge: int) -> int:
    return (edge + 2) % 4


def perimeter_cells(cols: int, rows: int) -> list[Cell]:
    seen: set[Cell] = set()
    ordered: list[Cell] = []
    for col in range(cols + 1):
        for row in (0, rows):
            cell = Cell(col, row)
            if cell not in seen:
                seen.add(cell)
                ordered.append(cell)
    for row in range(1, rows):
        for col in (0, cols):
            cell = Cell(col, row)
            if cell not in seen:
                seen.add(cell)
                ordered.append(cell)
    return ordered


def is_perimeter_cell(cell: Cell, cols: int, rows: int) -> bool:
    return (
        cell.row == 0
        or cell.row == rows
        or cell.col == 0
        or cell.col == cols
    )


def manhattan_cells(a: Cell, b: Cell) -> int:
    return abs(a.col - b.col) + abs(a.row - b.row)


def walk_cell_cost_s(stride_px: float) -> float:
    """Seconds to walk one block along a street segment."""
    return max(1.0, stride_px / PX_PER_SECOND * 0.92)


def sprint_cell_cost_s(stride_px: float) -> float:
    """Seconds to sprint one block on sidewalk (2× walk speed)."""
    return walk_cell_cost_s(stride_px) / SPRINT_SPEED_MULT


def cross_road_cost_s(crossing_wait_s: float) -> float:
    """Extra time to cross one road at walk speed (moderate-safe light waits)."""
    return CROSSING_BASE_S + crossing_wait_s * MODERATE_SAFE_WAIT_FRAC


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


def _heuristic(a: Cell, b: Cell, stride_px: float) -> float:
    # Admissible under the same cost model as _edge_cost: sidewalks use sprint
    # seconds, and crossings only add non-negative wait. Manhattan * sprint
    # never overestimates g, and is consistent because each step reduces
    # Manhattan by 1 while costing at least one sprint cell.
    sprint = sprint_cell_cost_s(stride_px)
    return (abs(a.col - b.col) + abs(a.row - b.row)) * sprint


def _edge_cost(a: Cell, b: Cell, crossing_wait_s: float, stride_px: float) -> float:
    cost = sprint_cell_cost_s(stride_px)
    cross = cross_road_cost_s(crossing_wait_s)
    if a.col != b.col:
        cost += cross
    if a.row != b.row:
        cost += cross
    return cost


def _route_crossings_between(a: Cell, b: Cell) -> int:
    """Road crossings when moving between adjacent grid cells along the A* model."""
    return int(a.col != b.col) + int(a.row != b.row)


def astar_route_estimate(
    start: Cell,
    goal: Cell,
    cols: int,
    rows: int,
    crossing_wait_s: float,
    stride_px: float,
) -> tuple[float, int] | None:
    """Estimated seconds and road crossings along the shortest time-aware path."""
    if not bfs_solvable(start, goal, cols, rows):
        return None

    open_heap: list[tuple[float, int, float, int, Cell]] = []
    tie = 0
    heapq.heappush(open_heap, (0.0, tie, 0.0, 0, start))
    g_score: dict[Cell, float] = {start: 0.0}
    crossings_score: dict[Cell, int] = {start: 0}

    while open_heap:
        _, _, g, crossings, current = heapq.heappop(open_heap)
        if g > g_score.get(current, math.inf):
            continue
        if current == goal:
            return g, crossings

        for nxt in _neighbors(current, cols, rows):
            tentative = g + _edge_cost(current, nxt, crossing_wait_s, stride_px)
            if tentative < g_score.get(nxt, math.inf):
                step_crossings = _route_crossings_between(current, nxt)
                g_score[nxt] = tentative
                crossings_score[nxt] = crossings + step_crossings
                f = tentative + _heuristic(nxt, goal, stride_px)
                tie += 1
                heapq.heappush(
                    open_heap,
                    (f, tie, tentative, crossings_score[nxt], nxt),
                )

    return None


def astar_travel_time(
    start: Cell,
    goal: Cell,
    cols: int,
    rows: int,
    crossing_wait_s: float,
    stride_px: float,
) -> float | None:
    """Estimated seconds along shortest time-aware path (None if unreachable)."""
    result = astar_route_estimate(
        start, goal, cols, rows, crossing_wait_s, stride_px
    )
    if result is None:
        return None
    travel_s, _crossings = result
    return travel_s
