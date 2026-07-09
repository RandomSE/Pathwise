"""Batched traffic-signal bulb drawing (dynamic state only; housings are baked)."""

from __future__ import annotations

import arcade
from PIL import Image, ImageDraw

from .geom import Rect, rects_overlap
from .pathwise_render import sim_y_to_arcade
from .traffic_signal_layout import bulb_positions as _signal_bulb_positions

_BULB_RADIUS = 6

_OFF_BULB_COLORS = ((120, 35, 35), (120, 100, 30), (35, 100, 35))
_ON_BULB_COLORS = ((220, 30, 30), (235, 185, 40), (40, 200, 40))
_BULB_TEXTURE_KEYS = (
    ("off", 0),
    ("on", 0),
    ("off", 1),
    ("on", 1),
    ("off", 2),
    ("on", 2),
)


def _bulb_texture_name(state: str, index: int) -> str:
    return f"signal_bulb_{state}_{index}"


def _bulb_diameter() -> int:
    from pathwise import sprites

    return _BULB_RADIUS * 2 * max(1, sprites.render_bake_multiplier())


def _make_bulb_texture(color: tuple[int, int, int], name: str) -> arcade.Texture:
    diam = _bulb_diameter()
    img = Image.new("RGBA", (diam, diam), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, diam - 1, diam - 1), fill=(*color, 255))
    return arcade.Texture(img, hash=name)


class TrafficLightBatch:
    """Draw only dynamic bulb states via a single SpriteList batch per frame."""

    def __init__(self) -> None:
        self._sprites = arcade.SpriteList(use_spatial_hash=False)
        self._pool: list[arcade.Sprite] = []
        self._textures: dict[str, arcade.Texture] = {}

    def _texture(self, on: bool, color_index: int) -> arcade.Texture:
        state = "on" if on else "off"
        key = _bulb_texture_name(state, color_index)
        cached = self._textures.get(key)
        if cached is not None:
            return cached
        palette = _ON_BULB_COLORS if on else _OFF_BULB_COLORS
        tex = _make_bulb_texture(palette[color_index], key)
        self._textures[key] = tex
        return tex

    def _ensure_pool(self, count: int) -> None:
        diam = _bulb_diameter()
        while len(self._pool) < count:
            sprite = arcade.SpriteSolidColor(diam, diam, (0, 0, 0, 0))
            sprite.center_x = 0
            sprite.center_y = 0
            sprite.visible = False
            self._pool.append(sprite)
            self._sprites.append(sprite)

    def draw_bulbs(
        self,
        road_states: list,
        camera_offset: tuple[int, int],
        sim_height: int,
        view_rect: Rect,
        *,
        housing_for_state,
        cull_pad: int = 80,
        visible_states: list | None = None,
    ) -> int:
        """Return number of bulbs drawn (for tests)."""
        cam_x, cam_y = camera_offset
        if visible_states is None:
            seen_crosswalk: set[tuple[int, int, int, int]] = set()
            visible_states = []
            for state in road_states:
                crosswalk = state["crosswalk"]
                key = (crosswalk.x, crosswalk.y, crosswalk.w, crosswalk.h)
                if key in seen_crosswalk:
                    continue
                approach = state.get("approach", "west")
                housing = housing_for_state(crosswalk, state["direction"], approach)
                if not rects_overlap(view_rect, housing.inflate(cull_pad, cull_pad)):
                    continue
                seen_crosswalk.add(key)
                visible_states.append((state, housing, approach))

        write_index = 0
        for state, housing, approach in visible_states:
            light = state["light_state"]
            flags = (
                light == "red",
                light == "yellow",
                light == "green",
            )
            for color_index, (world_x, world_y) in enumerate(
                _signal_bulb_positions(housing, state["direction"], approach)
            ):
                self._ensure_pool(write_index + 1)
                sprite = self._pool[write_index]
                sprite.texture = self._texture(flags[color_index], color_index)
                sprite.width = _BULB_RADIUS * 2
                sprite.height = _BULB_RADIUS * 2
                sx = world_x - cam_x
                sy = world_y - cam_y
                sprite.center_x = sx
                sprite.center_y = sim_y_to_arcade(sy, sim_height)
                sprite.visible = True
                write_index += 1

        for index in range(write_index, len(self._pool)):
            self._pool[index].visible = False
        if write_index:
            self._sprites.draw()
        return write_index


_shared_batch: TrafficLightBatch | None = None


def shared_traffic_light_batch() -> TrafficLightBatch:
    global _shared_batch
    if _shared_batch is None:
        _shared_batch = TrafficLightBatch()
    return _shared_batch
