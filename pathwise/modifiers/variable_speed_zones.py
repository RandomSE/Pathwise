"""Variable speed zones: different cruise speeds by along-road section.

Compatible with Highway: the E-W strip is split into along-travel bands.
No mutual exclusion with Time pressure (crossings unrelated to zone speeds).
No on-map visual markers (behavior-only).

Speed composition for cruise desired_speed (later caps still apply; High speed
scales last):
  base_speed  (= CAR_SPEED * difficulty CAR_SPEED_MULT * highway.car_speed_mult
               at spawn; highway rain is already folded into highway.car_speed_mult)
  * variable_speed_zones.speed_mult_for_pose(...)
  * high_speed.car_speed_scale()
  (* lag.physics_scale when Lag is active)
"""

from __future__ import annotations

from pathwise.geom import Rect
from pathwise.modifiers.registry import ModifierContext

ZONE_COUNT = 3
# Slow / normal / fast pool; per-road permutation is seed-stable.
ZONE_MULT_POOL: tuple[float, ...] = (0.7, 1.0, 1.35)
_ZONE_SALT = 0x25EE

_ctx: ModifierContext | None = None
_active = False
_tables: dict[int, tuple[float, ...]] = {}


def install_for_round(ctx: ModifierContext) -> None:
    global _ctx, _active, _tables
    _ctx = ctx
    _active = ctx.has("variable_speed_zones")
    _tables = {}


def is_active() -> bool:
    return _active


def along_frac_from_pose(road, x: float, y: float) -> float:
    """0..1 along the road travel axis (x for E-W / vertical roads)."""
    if road is None:
        return 0.0
    if getattr(road, "direction", "") == "vertical":
        span = max(1, int(road.rect.width))
        return max(0.0, min(1.0, (float(x) - float(road.rect.left)) / span))
    span = max(1, int(road.rect.height))
    return max(0.0, min(1.0, (float(y) - float(road.rect.top)) / span))


def zone_index_for_frac(along_frac: float) -> int:
    frac = max(0.0, min(0.999999, float(along_frac)))
    return min(ZONE_COUNT - 1, int(frac * ZONE_COUNT))


def _table_for_road(road_index: int) -> tuple[float, ...]:
    if not _active or _ctx is None:
        return tuple(1.0 for _ in range(ZONE_COUNT))
    key = int(road_index)
    cached = _tables.get(key)
    if cached is not None:
        return cached
    rng = _ctx.rng(_ZONE_SALT, key)
    order = list(ZONE_MULT_POOL)
    rng.shuffle(order)
    table = tuple(order)
    _tables[key] = table
    return table


def zone_mults_for_road(road_index: int) -> tuple[float, ...]:
    """Seed-stable mults for each along-road band (length ZONE_COUNT)."""
    return _table_for_road(road_index)


def speed_mult_for_pose(
    road,
    *,
    road_index: int,
    x: float,
    y: float,
) -> float:
    if not _active:
        return 1.0
    band = zone_index_for_frac(along_frac_from_pose(road, x, y))
    return float(_table_for_road(road_index)[band])


def speed_mult_for_car(car, roads) -> float:
    if not _active:
        return 1.0
    road_index = getattr(car, "road_index", None)
    if road_index is None or roads is None:
        return 1.0
    idx = int(road_index)
    if idx < 0 or idx >= len(roads):
        return 1.0
    rect = getattr(car, "rect", None)
    if rect is None:
        return 1.0
    return speed_mult_for_pose(
        roads[idx],
        road_index=idx,
        x=rect.centerx,
        y=rect.centery,
    )


def band_rect_for_road(road, band_index: int) -> Rect:
    """World-space rectangle covering one along-road zone band."""
    n = ZONE_COUNT
    i = max(0, min(n - 1, int(band_index)))
    r = road.rect
    if getattr(road, "direction", "") == "vertical":
        w = max(1, r.width // n)
        left = r.left + i * w
        width = w if i < n - 1 else max(1, r.right - left)
        return Rect(left, r.top, width, r.height)
    h = max(1, r.height // n)
    top = r.top + i * h
    height = h if i < n - 1 else max(1, r.bottom - top)
    return Rect(r.left, top, r.width, height)
