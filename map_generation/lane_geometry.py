"""Left-hand traffic: lane centers on road segments (screen y-down)."""

from __future__ import annotations


def lane_center_xy(road, direction: int) -> tuple[int, int]:
    """
    Center point for a travel direction on this road (keep-left / UK rules).

    road.direction vertical = E-W carriageway (cars move ±x; lanes split on y).
    road.direction horizontal = N-S carriageway (cars move ±y; lanes split on x).
    """
    d = 1 if direction >= 0 else -1
    if road.direction == "vertical":
        half = max(10, int(road.rect.height * 0.22))
        cy = road.rect.centery - half if d > 0 else road.rect.centery + half
        return int(road.rect.centerx), int(cy)
    half = max(10, int(road.rect.width * 0.22))
    cx = road.rect.centerx - half if d > 0 else road.rect.centerx + half
    return int(cx), int(road.rect.centery)


def lateral_axis_value(road, direction: int) -> int:
    """Lane coordinate on the axis perpendicular to travel (for spawn helpers)."""
    cx, cy = lane_center_xy(road, direction)
    if road.direction == "vertical":
        return cy
    return cx
