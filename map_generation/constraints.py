"""Constraint checks for generated street grids."""

from __future__ import annotations

import commonUtils

VERTICAL = commonUtils.VERTICAL
HORIZONTAL = commonUtils.HORIZONTAL


def roads_fully_connected(roads) -> bool:
    """Every road must meet at least one road of the other orientation (no orphan lane)."""
    vertical = [r for r in roads if r.direction == VERTICAL]
    horizontal = [r for r in roads if r.direction == HORIZONTAL]
    if not vertical or not horizontal:
        return len(roads) <= 1
    for v_road in vertical:
        if not any(v_road.rect.colliderect(h_road.rect) for h_road in horizontal):
            return False
    for h_road in horizontal:
        if not any(h_road.rect.colliderect(v_road.rect) for v_road in vertical):
            return False
    return True


def traffic_density_balanced(weights: list[float], max_ratio: float = 2.6) -> bool:
    if not weights:
        return True
    low = min(weights)
    high = max(weights)
    if low <= 0:
        return False
    return high / low <= max_ratio


def road_positions_valid(h_ys: list[int], v_xs: list[int], min_gap: int) -> bool:
    for i in range(1, len(h_ys)):
        if h_ys[i] - h_ys[i - 1] < min_gap:
            return False
    for i in range(1, len(v_xs)):
        if v_xs[i] - v_xs[i - 1] < min_gap:
            return False
    return True
