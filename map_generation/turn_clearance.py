"""Bezier turn sampling and corridor bounds (renderer-agnostic)."""

from __future__ import annotations


def bezier_point(
    t: float,
    start: tuple[float, float],
    mid: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    t = max(0.0, min(1.0, t))
    sx, sy = start
    mx, my = mid
    ex, ey = end
    u = 1.0 - t
    cx = u * u * sx + 2.0 * u * t * mx + t * t * ex
    cy = u * u * sy + 2.0 * u * t * my + t * t * ey
    return cx, cy


def sample_bezier(
    start: tuple[float, float],
    mid: tuple[float, float],
    end: tuple[float, float],
    count: int = 9,
) -> list[tuple[float, float]]:
    if count < 2:
        return [bezier_point(0.0, start, mid, end)]
    return [
        bezier_point(i / (count - 1), start, mid, end) for i in range(count)
    ]


def corridor_bounds(
    points: list[tuple[float, float]],
    pad: float,
) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) inclusive bounds with padding."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (
        min(xs) - pad,
        min(ys) - pad,
        max(xs) + pad,
        max(ys) + pad,
    )
