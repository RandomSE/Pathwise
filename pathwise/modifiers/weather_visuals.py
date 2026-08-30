"""Rain visuals: particles, tint overlay, baked wet road decals."""

from __future__ import annotations

import random

import arcade

from pathwise.geom import Rect
from pathwise.map_visuals import (
    ROAD_ASPHALT,
    BakedMapLayer,
    _tile_baked_image,
    redraw_crosswalks_and_housing_pil,
)

RAIN_PARTICLE_CAP = 48
RAIN_UPDATE_STRIDE = 2
RAIN_TINT = (140, 155, 175, 32)
RAIN_LINE_COLOR = (190, 205, 225, 120)


class RainParticlePool:
    def __init__(self, *, cap: int = RAIN_PARTICLE_CAP, seed: int = 0) -> None:
        self._cap = cap
        self._rng = random.Random(seed ^ 0x0A1E)
        self._particles: list[tuple[float, float, float, float]] = []
        self._frame = 0
        self._init_particles()

    def _init_particles(self) -> None:
        self._particles.clear()
        for _ in range(self._cap):
            self._particles.append(self._spawn_particle())

    def _spawn_particle(self) -> tuple[float, float, float, float]:
        x = self._rng.uniform(0, 1)
        y = self._rng.uniform(0, 1)
        speed = self._rng.uniform(280, 420)
        length = self._rng.uniform(8, 14)
        return (x, y, speed, length)

    def update(self, dt: float) -> None:
        self._frame += 1
        if self._frame % RAIN_UPDATE_STRIDE != 0:
            return
        step = dt * RAIN_UPDATE_STRIDE
        for index, (nx, ny, speed, length) in enumerate(self._particles):
            ny += speed * step * 0.0015
            nx += speed * step * 0.0006
            if ny > 1.05:
                nx, ny, speed, length = self._spawn_particle()
                ny = self._rng.uniform(-0.05, 0.0)
            self._particles[index] = (nx, ny, speed, length)

    def draw(
        self,
        sim_width: int,
        sim_height: int,
        view_rect: Rect,
        camera_offset: tuple[int, int],
    ) -> None:
        cam_x, cam_y = camera_offset
        points: list[tuple[float, float]] = []
        vl, vt, vr, vb = view_rect.left, view_rect.top, view_rect.right, view_rect.bottom
        for nx, ny, _speed, length in self._particles:
            wx = view_rect.left + int(nx * view_rect.width)
            wy = view_rect.top + int(ny * view_rect.height)
            if wx < vl - 8 or wx > vr + 8 or wy < vt - 8 or wy > vb + 8:
                continue
            sx = wx - cam_x
            sy_bottom = sim_height - (wy - cam_y)
            ex = sx + length * 0.35
            ey = sy_bottom - length
            points.append((sx, sy_bottom))
            points.append((ex, ey))
        if len(points) >= 2:
            arcade.draw_lines(points, RAIN_LINE_COLOR, 1)


_pool: RainParticlePool | None = None


def install_rain_visuals(*, session_base_seed: int, round_index: int) -> None:
    global _pool
    seed = (session_base_seed + round_index * 9973) & 0x7FFFFFFF
    _pool = RainParticlePool(seed=seed)


def reset_rain_visuals() -> None:
    global _pool
    _pool = None


def draw_weather_overlay(
    *,
    sim_width: int,
    sim_height: int,
    view_rect: Rect,
    camera_offset: tuple[int, int],
    elapsed: float,
    dt: float = 1 / 60,
) -> None:
    del elapsed
    if _pool is None:
        return
    _pool.update(dt)
    arcade.draw_lbwh_rectangle_filled(0, 0, sim_width, sim_height, RAIN_TINT)
    _pool.draw(sim_width, sim_height, view_rect, camera_offset)


def bake_rainy_road_overlay(
    baked: BakedMapLayer,
    *,
    road_states: list,
    session_base_seed: int,
    round_index: int,
) -> BakedMapLayer:
    """Darken roads, add puddle sheen near crosswalks; restore crosswalk/housing visibility."""
    from PIL import Image, ImageDraw

    rng = random.Random((session_base_seed + round_index * 31) & 0x7FFFFFFF)
    base_img = baked.texture.image.copy()
    draw = ImageDraw.Draw(base_img)
    origin = (baked.world_bounds.left, baked.world_bounds.top)
    wet = tuple(max(0, c - 12) for c in ROAD_ASPHALT)
    puddle = (45, 52, 62, 90)

    seen_crosswalk: set[tuple[int, int, int, int]] = set()
    for state in road_states:
        crosswalk = state["crosswalk"]
        key = (crosswalk.x, crosswalk.y, crosswalk.w, crosswalk.h)
        if key in seen_crosswalk:
            continue
        seen_crosswalk.add(key)
        cx = crosswalk.centerx - origin[0]
        cy = crosswalk.centery - origin[1]
        road_rect = state.get("road_rect")
        if road_rect is not None:
            rl = road_rect.left - origin[0]
            rt = road_rect.top - origin[1]
            rr = road_rect.right - origin[0]
            rb = road_rect.bottom - origin[1]
            draw.rectangle((rl, rt, rr, rb), fill=(*wet, 255))
        pw = rng.randint(24, 36)
        ph = rng.randint(8, 12)
        direction = state.get("direction", "horizontal")
        lane_offset = rng.randint(22, 38)
        sign = -1 if rng.random() < 0.5 else 1
        if direction == "horizontal":
            px, py = cx, cy + sign * lane_offset
        else:
            px, py = cx + sign * lane_offset, cy
        draw.ellipse((px - pw, py - ph, px + pw, py + ph), fill=puddle)

    redraw_crosswalks_and_housing_pil(draw, road_states, origin)

    texture = arcade.Texture(
        base_img,
        hash=f"rain_bake_{session_base_seed}_{round_index}_{baked.world_bounds.width}",
    )
    tiles = _tile_baked_image(
        base_img,
        baked.world_bounds,
        f"rain_{session_base_seed}_{round_index}",
    )
    return BakedMapLayer(texture=texture, world_bounds=baked.world_bounds.copy(), tiles=tiles)
