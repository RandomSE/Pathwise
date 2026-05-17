"""2D gradient noise (simplex-style) for procedural layout variation."""

import math

_PERM = list(range(256))
_rng = __import__("random").Random(42)
_rng.shuffle(_PERM)
_PERM = _PERM * 2

_GRAD2 = (
    (1, 1),
    (-1, 1),
    (1, -1),
    (-1, -1),
    (1, 0),
    (-1, 0),
    (0, 1),
    (0, -1),
)


def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6 - 15) + 10)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _grad(hash_val: int, x: float, y: float) -> float:
    g = _GRAD2[hash_val & 7]
    return g[0] * x + g[1] * y


def simplex2(x: float, y: float, seed: int = 0) -> float:
    """Returns noise in approximately [-1, 1]."""
    offset = seed * 0.0137
    x += offset
    y += offset * 1.31

    s = (x + y) * 0.3660254037844386
    i = int(math.floor(x + s)) & 255
    j = int(math.floor(y + s)) & 255

    t = (i + j) * 0.21132486540518713
    x0 = x - (i - t)
    y0 = y - (j - t)

    i1 = 1 if x0 > y0 else 0
    j1 = 1 if x0 <= y0 else 0

    x1 = x0 - i1 + 0.21132486540518713
    y1 = y0 - j1 + 0.21132486540518713
    x2 = x0 - 1.0 + 0.42264973081037426
    y2 = y0 - 1.0 + 0.42264973081037426

    ii = (i + seed) & 255
    jj = (j + seed) & 255
    gi0 = _PERM[ii + _PERM[jj]]
    gi1 = _PERM[ii + i1 + _PERM[jj + j1]]
    gi2 = _PERM[ii + 1 + _PERM[jj + 1]]

    t0 = max(0.5 - x0 * x0 - y0 * y0, 0.0)
    t1 = max(0.5 - x1 * x1 - y1 * y1, 0.0)
    t2 = max(0.5 - x2 * x2 - y2 * y2, 0.0)

    n0 = t0**4 * _grad(gi0, x0, y0) if t0 else 0.0
    n1 = t1**4 * _grad(gi1, x1, y1) if t1 else 0.0
    n2 = t2**4 * _grad(gi2, x2, y2) if t2 else 0.0

    return 2.3 * (n0 + n1 + n2)


def fbm(x: float, y: float, seed: int = 0, octaves: int = 3) -> float:
    """Fractional Brownian motion in [0, 1]."""
    value = 0.0
    amplitude = 0.5
    frequency = 1.0
    norm = 0.0
    for octave in range(octaves):
        value += amplitude * simplex2(x * frequency, y * frequency, seed + octave * 17)
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return max(0.0, min(1.0, (value / norm + 1.0) * 0.5))
