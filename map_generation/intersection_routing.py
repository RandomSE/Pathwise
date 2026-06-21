"""Travel-vector helpers for lane-aligned movement."""

from __future__ import annotations

def travel_vector(vertical: bool, direction: int) -> tuple[int, int]:
    direction = 1 if direction >= 0 else -1
    if not vertical:
        return (direction, 0)
    return (0, direction)


def left_vector(vertical: bool, direction: int) -> tuple[int, int]:
    """Screen coords (y down): left side of travel."""
    fx, fy = travel_vector(vertical, direction)
    return (fy, -fx)


def drive_from_vector(vx: int, vy: int) -> tuple[bool, int]:
    if vx != 0:
        return False, 1 if vx > 0 else -1
    return True, 1 if vy > 0 else -1


