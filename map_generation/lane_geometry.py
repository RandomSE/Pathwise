"""Left-hand traffic: lane centers on road segments (screen y-down)."""

from __future__ import annotations

# Offset from road centerline toward the curb; larger keeps straight traffic
# farther from the yellow center line and reduces turn encroachment collisions.
LANE_KEEP_LEFT_FRAC = 0.30
_CENTERLINE_GUARD_FRAC = 0.06
_BAND_EDGE_PAD = 8


def parallel_lanes_per_dir(road) -> int:
    """Travel lanes on each side of the centerline (1 = normal city keep-left)."""
    return max(1, int(getattr(road, "parallel_lanes", 1) or 1))


def _lane_half_extent(road) -> int:
    if road.direction == "vertical":
        return max(10, int(road.rect.height * LANE_KEEP_LEFT_FRAC))
    return max(10, int(road.rect.width * LANE_KEEP_LEFT_FRAC))


def centerline_guard_px(road) -> int:
    """Minimum inset from the yellow center line toward keep-left."""
    if road.direction == "vertical":
        return max(6, int(road.rect.height * _CENTERLINE_GUARD_FRAC))
    return max(6, int(road.rect.width * _CENTERLINE_GUARD_FRAC))


def _direction_band(road, direction: int) -> tuple[float, float]:
    """Inner (near centerline) to outer (near curb) lateral span for this direction."""
    d = 1 if direction >= 0 else -1
    guard = centerline_guard_px(road)
    pad = _BAND_EDGE_PAD
    if road.direction == "vertical":
        mid = float(road.rect.centery)
        if d > 0:
            return mid - guard, float(road.rect.top + pad)
        return mid + guard, float(road.rect.bottom - pad)
    mid = float(road.rect.centerx)
    if d > 0:
        return mid + guard, float(road.rect.right - pad)
    return mid - guard, float(road.rect.left + pad)


def lane_center_xy(road, direction: int, *, lane_index: int = 0) -> tuple[int, int]:
    """
    Center point for a travel direction on this road (keep-left / UK rules).

    road.direction vertical = E-W carriageway (cars move ±x; lanes split on y).
    road.direction horizontal = N-S carriageway (cars move ±y; lanes split on x).
    When road.parallel_lanes > 1, lane_index selects among that many tracks per side.
    """
    d = 1 if direction >= 0 else -1
    n = parallel_lanes_per_dir(road)
    if n <= 1:
        half = _lane_half_extent(road)
        if road.direction == "vertical":
            cy = road.rect.centery - half if d > 0 else road.rect.centery + half
            return int(road.rect.centerx), int(cy)
        cx = road.rect.centerx + half if d > 0 else road.rect.centerx - half
        return int(cx), int(road.rect.centery)

    idx = max(0, min(n - 1, int(lane_index)))
    inner, outer = _direction_band(road, d)
    # idx 0 nearest centerline; idx n-1 nearest curb.
    t = (idx + 0.5) / n
    lateral = inner + (outer - inner) * t
    if road.direction == "vertical":
        return int(road.rect.centerx), int(round(lateral))
    return int(round(lateral)), int(road.rect.centery)


def clamp_keep_left_xy(
    road, direction: int, x: float, y: float, *, strength: float = 1.0
) -> tuple[float, float]:
    """Nudge a point toward the keep-left half: never cross the yellow line."""
    d = 1 if direction >= 0 else -1
    guard = centerline_guard_px(road)
    strength = max(0.0, min(1.0, strength))
    if road.direction == "vertical":
        limit = road.rect.centery - guard if d > 0 else road.rect.centery + guard
        if d > 0 and y > limit:
            y = y + (limit - y) * strength
        elif d < 0 and y < limit:
            y = y + (limit - y) * strength
        return x, y
    limit = road.rect.centerx + guard if d > 0 else road.rect.centerx - guard
    if d > 0 and x < limit:
        x = x + (limit - x) * strength
    elif d < 0 and x > limit:
        x = x + (limit - x) * strength
    return x, y


def lateral_axis_value(road, direction: int, *, lane_index: int = 0) -> int:
    """Lane coordinate on the axis perpendicular to travel (for spawn helpers)."""
    cx, cy = lane_center_xy(road, direction, lane_index=lane_index)
    if road.direction == "vertical":
        return cy
    return cx
