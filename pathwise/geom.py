"""Renderer-agnostic rectangle type used by Pathwise simulation."""

from __future__ import annotations

from typing import Iterable, overload


def _as_int(value: float | int) -> int:
    return int(round(value))


class Rect:
    """Axis-aligned rectangle with top-left origin, y-down."""

    __slots__ = ("_x", "_y", "_w", "_h")

    @overload
    def __init__(self, left: float | int, top: float | int, width: float | int, height: float | int) -> None: ...

    @overload
    def __init__(self, rect: "Rect") -> None: ...

    @overload
    def __init__(self, values: Iterable[float | int]) -> None: ...

    def __init__(self, *args) -> None:
        if len(args) == 1:
            other = args[0]
            if isinstance(other, Rect):
                self._x, self._y, self._w, self._h = other._x, other._y, other._w, other._h
                return
            left, top, width, height = other
            self._x = _as_int(left)
            self._y = _as_int(top)
            self._w = _as_int(width)
            self._h = _as_int(height)
            return
        if len(args) == 4:
            self._x = _as_int(args[0])
            self._y = _as_int(args[1])
            self._w = _as_int(args[2])
            self._h = _as_int(args[3])
            return
        raise TypeError("Rect expects (left, top, width, height), another Rect, or a 4-tuple")

    # --- position / size aliases ---

    @property
    def x(self) -> int:
        return self._x

    @x.setter
    def x(self, value: float | int) -> None:
        self._x = _as_int(value)

    @property
    def y(self) -> int:
        return self._y

    @y.setter
    def y(self, value: float | int) -> None:
        self._y = _as_int(value)

    @property
    def w(self) -> int:
        return self._w

    @w.setter
    def w(self, value: float | int) -> None:
        self._w = max(0, _as_int(value))

    @property
    def h(self) -> int:
        return self._h

    @h.setter
    def h(self, value: float | int) -> None:
        self._h = max(0, _as_int(value))

    @property
    def width(self) -> int:
        return self._w

    @width.setter
    def width(self, value: float | int) -> None:
        self.w = value

    @property
    def height(self) -> int:
        return self._h

    @height.setter
    def height(self, value: float | int) -> None:
        self.h = value

    @property
    def left(self) -> int:
        return self._x

    @left.setter
    def left(self, value: float | int) -> None:
        self._x = _as_int(value)

    @property
    def top(self) -> int:
        return self._y

    @top.setter
    def top(self, value: float | int) -> None:
        self._y = _as_int(value)

    @property
    def right(self) -> int:
        return self._x + self._w

    @right.setter
    def right(self, value: float | int) -> None:
        self._x = _as_int(value) - self._w

    @property
    def bottom(self) -> int:
        return self._y + self._h

    @bottom.setter
    def bottom(self, value: float | int) -> None:
        self._y = _as_int(value) - self._h

    @property
    def centerx(self) -> int:
        return self._x + self._w // 2

    @centerx.setter
    def centerx(self, value: float | int) -> None:
        self._x = _as_int(value) - self._w // 2

    @property
    def centery(self) -> int:
        return self._y + self._h // 2

    @centery.setter
    def centery(self, value: float | int) -> None:
        self._y = _as_int(value) - self._h // 2

    @property
    def center(self) -> tuple[int, int]:
        return (self.centerx, self.centery)

    @center.setter
    def center(self, value: tuple[float | int, float | int]) -> None:
        cx, cy = value
        self.centerx = cx
        self.centery = cy

    @property
    def topleft(self) -> tuple[int, int]:
        return (self._x, self._y)

    @topleft.setter
    def topleft(self, value: tuple[float | int, float | int]) -> None:
        self._x, self._y = _as_int(value[0]), _as_int(value[1])

    @property
    def size(self) -> tuple[int, int]:
        return (self._w, self._h)

    # --- geometry ops ---

    def copy(self) -> Rect:
        return Rect(self)

    def move(self, x: float | int, y: float | int) -> Rect:
        moved = self.copy()
        moved._x += _as_int(x)
        moved._y += _as_int(y)
        return moved

    def inflate(self, x: float | int, y: float | int) -> Rect:
        dx = _as_int(x)
        dy = _as_int(y)
        inflated = Rect(
            self._x - dx // 2,
            self._y - dy // 2,
            self._w + dx,
            self._h + dy,
        )
        return inflated

    def inflate_ip(self, x: float | int, y: float | int) -> None:
        inflated = self.inflate(x, y)
        self._x, self._y, self._w, self._h = inflated._x, inflated._y, inflated._w, inflated._h

    def clip(self, other: Rect) -> Rect:
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        width = max(0, right - left)
        height = max(0, bottom - top)
        return Rect(left, top, width, height)

    def colliderect(self, other: Rect) -> bool:
        return (
            self.left < other.right
            and self.right > other.left
            and self.top < other.bottom
            and self.bottom > other.top
        )

    def collidepoint(self, *args) -> bool:
        if len(args) == 1:
            px, py = args[0]
        elif len(args) == 2:
            px, py = args
        else:
            raise TypeError("collidepoint expects (x, y) or a point tuple")
        return self.left <= px < self.right and self.top <= py < self.bottom

    def contains(self, other: Rect) -> bool:
        inner = as_rect(other)
        return (
            inner.left >= self.left
            and inner.right <= self.right
            and inner.top >= self.top
            and inner.bottom <= self.bottom
        )

    def clamp(self, other: Rect) -> Rect:
        """Return a copy clamped inside other."""
        clamped = self.copy()
        clamped.clamp_ip(other)
        return clamped

    def clamp_ip(self, other: Rect | object) -> None:
        """Move this rect in-place to stay inside other."""
        bounds = as_rect(other)
        if self.width > bounds.width:
            self.left = bounds.left
        elif self.left < bounds.left:
            self.left = bounds.left
        elif self.right > bounds.right:
            self.right = bounds.right
        if self.height > bounds.height:
            self.top = bounds.top
        elif self.top < bounds.top:
            self.top = bounds.top
        elif self.bottom > bounds.bottom:
            self.bottom = bounds.bottom

    def union(self, other: Rect) -> Rect:
        left = min(self.left, other.left)
        top = min(self.top, other.top)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return Rect(left, top, right - left, bottom - top)

    def __repr__(self) -> str:
        return f"Rect({self._x}, {self._y}, {self._w}, {self._h})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rect):
            return NotImplemented
        return (self._x, self._y, self._w, self._h) == (other._x, other._y, other._w, other._h)


def as_rect(value: Rect | object) -> Rect:
    """Normalize geom.Rect or duck-typed rect-likes."""
    if isinstance(value, Rect):
        return value
    return Rect(value.left, value.top, value.width, value.height)


def rects_overlap(a: Rect, b: Rect) -> bool:
    """Fast AABB overlap test without allocating temporary rects."""
    return a.left < b.right and a.right > b.left and a.top < b.bottom and a.bottom > b.top


def rect_overlap_area(a: Rect, b: Rect) -> int:
    """Pixel area of AABB intersection without allocating rects."""
    w = min(a.right, b.right) - max(a.left, b.left)
    if w <= 0:
        return 0
    h = min(a.bottom, b.bottom) - max(a.top, b.top)
    if h <= 0:
        return 0
    return w * h


def collide(a: Rect | object, b: Rect | object) -> bool:
    if isinstance(a, Rect) and isinstance(b, Rect):
        return rects_overlap(a, b)
    return as_rect(a).colliderect(as_rect(b))


def clip_rect(a: Rect | object, b: Rect | object) -> Rect:
    return as_rect(a).clip(as_rect(b))


def contains_rect(outer: Rect | object, inner: Rect | object) -> bool:
    o = as_rect(outer)
    i = as_rect(inner)
    return (
        i.left >= o.left
        and i.right <= o.right
        and i.top >= o.top
        and i.bottom <= o.bottom
    )


__all__ = [
    "Rect",
    "as_rect",
    "collide",
    "clip_rect",
    "contains_rect",
    "rects_overlap",
    "rect_overlap_area",
]
