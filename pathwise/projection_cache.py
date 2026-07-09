"""Cached orthogonal projection matrices for Arcade draw paths."""

from __future__ import annotations

from pyglet.math import Mat4

_Z_NEAR = -8192
_Z_FAR = 8192

_cache: dict[tuple[int, int, int, int], Mat4] = {}


def orthogonal_projection(
    left: float,
    right: float,
    bottom: float,
    top: float,
    *,
    z_near: float = _Z_NEAR,
    z_far: float = _Z_FAR,
) -> Mat4:
    key = (int(left), int(right), int(bottom), int(top))
    mat = _cache.get(key)
    if mat is None:
        mat = Mat4.orthogonal_projection(left, right, bottom, top, z_near, z_far)
        _cache[key] = mat
    return mat


def screen_projection(window_width: int, window_height: int) -> Mat4:
    return orthogonal_projection(0, window_width, 0, window_height)


def sim_projection(sim_width: int, sim_height: int) -> Mat4:
    return orthogonal_projection(0, sim_width, 0, sim_height)


def reset_projection_cache() -> None:
    _cache.clear()
