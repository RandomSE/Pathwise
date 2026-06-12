"""Traffic signal housing placement and bulb layout (top-down, far-side, driver-facing)."""

from __future__ import annotations

from .geom import Rect

SIGNAL_GAP = 4
VERT_HOUSING_W = 22
VERT_HOUSING_H = 56
HORIZ_HOUSING_W = 56
HORIZ_HOUSING_H = 22

# approach: traffic flows toward this compass direction into the intersection
APPROACH_WEST = "west"  # +x eastbound on E-W road
APPROACH_EAST = "east"  # -x westbound
APPROACH_NORTH = "north"  # +y southbound on N-S road
APPROACH_SOUTH = "south"  # -y northbound


def traffic_housing_rect(
    crosswalk: Rect, road_direction: str, approach: str
) -> Rect:
    """
    Place the signal head on the far side of the crosswalk from approaching traffic.

    road_direction "vertical" = E-W carriageway (bulbs stacked top→bottom R,Y,G).
    road_direction "horizontal" = N-S carriageway (bulbs left→right R,Y,G).
    """
    if road_direction == "vertical":
        stack_top = crosswalk.centery - VERT_HOUSING_H // 2
        if approach == APPROACH_WEST:
            return Rect(
                crosswalk.right + SIGNAL_GAP,
                stack_top,
                VERT_HOUSING_W,
                VERT_HOUSING_H,
            )
        if approach == APPROACH_EAST:
            return Rect(
                crosswalk.left - SIGNAL_GAP - VERT_HOUSING_W,
                stack_top,
                VERT_HOUSING_W,
                VERT_HOUSING_H,
            )
    else:
        stack_left = crosswalk.centerx - HORIZ_HOUSING_W // 2
        if approach == APPROACH_NORTH:
            return Rect(
                stack_left,
                crosswalk.bottom + SIGNAL_GAP,
                HORIZ_HOUSING_W,
                HORIZ_HOUSING_H,
            )
        if approach == APPROACH_SOUTH:
            return Rect(
                stack_left,
                crosswalk.top - SIGNAL_GAP - HORIZ_HOUSING_H,
                HORIZ_HOUSING_W,
                HORIZ_HOUSING_H,
            )
    return _legacy_housing_rect(crosswalk, road_direction)


def _legacy_housing_rect(crosswalk: Rect, road_direction: str) -> Rect:
    if road_direction == "vertical":
        return Rect(
            crosswalk.centerx - VERT_HOUSING_W // 2,
            crosswalk.top - SIGNAL_GAP - VERT_HOUSING_H,
            VERT_HOUSING_W,
            VERT_HOUSING_H,
        )
    return Rect(
        crosswalk.left - SIGNAL_GAP - HORIZ_HOUSING_W,
        crosswalk.centery - HORIZ_HOUSING_H // 2,
        HORIZ_HOUSING_W,
        HORIZ_HOUSING_H,
    )


def bulb_positions(
    housing: Rect, road_direction: str, approach: str
) -> list[tuple[int, int]]:
    """Red, yellow, green bulb centers on the face visible to approaching traffic."""
    if road_direction == "vertical":
        if approach == APPROACH_EAST:
            bx = housing.right - VERT_HOUSING_W // 2
        else:
            bx = housing.left + VERT_HOUSING_W // 2
        return [
            (bx, housing.top + 10),
            (bx, housing.top + 28),
            (bx, housing.top + 46),
        ]
    if approach == APPROACH_SOUTH:
        by = housing.bottom - HORIZ_HOUSING_H // 2
    else:
        by = housing.top + HORIZ_HOUSING_H // 2
    return [
        (housing.left + 10, by),
        (housing.left + 28, by),
        (housing.left + 46, by),
    ]


def turn_bulb_position(
    housing: Rect, road_direction: str, approach: str
) -> tuple[int, int]:
    """Protected turn arrow bulb beside the through stack (driver-facing side)."""
    if road_direction == "vertical":
        bx = housing.left + VERT_HOUSING_W // 2
        if approach == APPROACH_EAST:
            bx = housing.right - VERT_HOUSING_W // 2
        return (bx + 18, housing.top + 28)
    by = housing.top + HORIZ_HOUSING_H // 2
    if approach == APPROACH_SOUTH:
        by = housing.bottom - HORIZ_HOUSING_H // 2
    return (housing.left + 28, by - 18)


def approach_sign_rect(
    housing: Rect, road_direction: str, approach: str
) -> Rect:
    """Small lane marker beside the head, on the driver's side of the stop line."""
    if road_direction == "vertical":
        if approach == APPROACH_WEST:
            return Rect(housing.right + 6, housing.top + 8, 14, 14)
        if approach == APPROACH_EAST:
            return Rect(housing.left - 20, housing.top + 8, 14, 14)
    else:
        if approach == APPROACH_NORTH:
            return Rect(housing.left + 8, housing.bottom + 6, 14, 14)
        if approach == APPROACH_SOUTH:
            return Rect(housing.left + 8, housing.top - 20, 14, 14)
    return Rect(housing.x - 20, housing.y - 20, 14, 14)


def housing_as_list(housing: Rect) -> list[int]:
    return [housing.x, housing.y, housing.w, housing.h]
