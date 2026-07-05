"""City-block and road rendering for procedural maps."""

from __future__ import annotations

import random
from dataclasses import dataclass

import arcade
from PIL import Image, ImageDraw

from .geom import Rect, collide
from .map import ROAD_THICKNESS
from .traffic_signal_layout import (
    APPROACH_WEST,
    bulb_positions as _signal_bulb_positions,
    traffic_housing_rect as _signal_housing_rect,
    turn_bulb_position as _signal_turn_bulb_position,
)

BLOCK_STYLES = {
    "park": ((72, 128, 78), (58, 108, 64)),
    "residential": ((196, 178, 152), (168, 148, 128)),
    "commercial": ((120, 138, 168), (92, 108, 138)),
    "plaza": ((210, 200, 188), (185, 175, 165)),
}

ROAD_ASPHALT = (58, 62, 68)
ROAD_EDGE = (42, 45, 50)
LANE_MARK = (220, 200, 70)
CROSSWALK_WHITE = (238, 238, 240)
SIDEWALK = (168, 162, 152)
GRASS_BASE = (198, 214, 178)
GRASS_ALT = (186, 202, 168)


MAP_TILE_SIZE = 512


@dataclass(frozen=True)
class MapTile:
    world_rect: Rect
    texture: arcade.Texture


@dataclass(frozen=True)
class BakedMapLayer:
    texture: arcade.Texture
    world_bounds: Rect
    tiles: tuple[MapTile, ...] = ()


def _rgba(color, alpha=255):
    if len(color) == 4:
        return color
    return (*color, alpha)


def _draw_round_rect(draw, xy, fill=None, outline=None, width=1, radius=0):
    if radius > 0:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    elif outline is not None and width:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(xy, fill=fill)


def generate_city_blocks(
    h_ys: list[int],
    v_xs: list[int],
    world_left: int,
    world_top: int,
    world_right: int,
    world_bottom: int,
    seed: int,
    pad: int = 14,
) -> list[dict]:
    """One city block per grid cell between road segments."""
    rng = random.Random(seed ^ 0xC17A_B10C)
    kinds = ("residential", "residential", "commercial", "park", "plaza")
    blocks = []
    x_edges = [world_left] + list(v_xs) + [world_right]
    y_edges = [world_top] + list(h_ys) + [world_bottom]

    for row in range(len(y_edges) - 1):
        for col in range(len(x_edges) - 1):
            left = x_edges[col] + (ROAD_THICKNESS + pad if col > 0 else pad)
            right = (
                x_edges[col + 1] - pad
                if col + 1 < len(x_edges)
                else x_edges[col + 1] - pad
            )
            top = y_edges[row] + (ROAD_THICKNESS + pad if row > 0 else pad)
            bottom = (
                y_edges[row + 1] - pad
                if row + 1 < len(y_edges)
                else y_edges[row + 1] - pad
            )
            w, h = right - left, bottom - top
            if w < 48 or h < 48:
                continue
            kind = kinds[int(rng.random() * len(kinds))]
            if rng.random() < 0.12:
                kind = "park"
            blocks.append(
                {
                    "x": left,
                    "y": top,
                    "w": w,
                    "h": h,
                    "kind": kind,
                    "seed": rng.randint(0, 9999),
                }
            )
    return blocks


def generate_map_decorations(city_blocks: list[dict], seed: int) -> list[dict]:
    """Trees, lamps, and benches scattered in city blocks (not on roads)."""
    rng = random.Random(seed ^ 0xDEC0_71E5)
    decor: list[dict] = []
    for block in city_blocks:
        br = Rect(block["x"], block["y"], block["w"], block["h"])
        if br.w < 56 or br.h < 56:
            continue
        block_rng = random.Random(block.get("seed", 0) + seed)
        kind = block.get("kind", "residential")
        if kind == "park":
            tree_n = block_rng.randint(4, 9)
            lamp_n, bench_n = 0, block_rng.randint(0, 2)
        elif kind == "residential":
            tree_n = block_rng.randint(1, 4)
            lamp_n = block_rng.randint(0, 2)
            bench_n = block_rng.randint(0, 1)
        elif kind == "commercial":
            tree_n = block_rng.randint(0, 2)
            lamp_n = block_rng.randint(1, 3)
            bench_n = block_rng.randint(0, 2)
        else:
            tree_n = block_rng.randint(0, 2)
            lamp_n = block_rng.randint(0, 1)
            bench_n = block_rng.randint(1, 2)

        def _point_in_block():
            margin = 10
            return (
                block_rng.randint(br.left + margin, br.right - margin),
                block_rng.randint(br.top + margin, br.bottom - margin),
            )

        for _ in range(tree_n):
            x, y = _point_in_block()
            decor.append(
                {
                    "type": "tree",
                    "x": x,
                    "y": y,
                    "scale": block_rng.uniform(0.85, 1.2),
                }
            )
        for _ in range(lamp_n):
            x, y = _point_in_block()
            decor.append({"type": "lamp", "x": x, "y": y})
        for _ in range(bench_n):
            x, y = _point_in_block()
            decor.append({"type": "bench", "x": x, "y": y, "wide": block_rng.choice([True, False])})
    return decor


def _world_to_local(x: int, y: int, origin: tuple[int, int]) -> tuple[int, int]:
    return x - origin[0], y - origin[1]


def _draw_tree(draw, x: int, y: int, scale: float = 1.0):
    r = int(10 * scale)
    trunk_h = int(14 * scale)
    draw.rectangle((x - 3, y, x + 3, y + trunk_h), fill=_rgba((92, 62, 40)))
    draw.ellipse((x - r, y - 4 - r, x + r, y - 4 + r), fill=_rgba((42, 110, 52)))
    draw.ellipse((x - 5 - max(4, r - 4), y - 2 - max(4, r - 4), x - 5 + max(4, r - 4), y - 2 + max(4, r - 4)), fill=_rgba((58, 130, 62)))
    draw.ellipse((x + 5 - max(4, r - 5), y - 1 - max(4, r - 5), x + 5 + max(4, r - 5), y - 1 + max(4, r - 5)), fill=_rgba((48, 100, 48)))


def _draw_lamp(draw, x: int, y: int):
    draw.line((x, y, x, y - 22), fill=_rgba((70, 74, 78)), width=3)
    draw.ellipse((x - 5, y - 24 - 5, x + 5, y - 24 + 5), fill=_rgba((255, 248, 200)))
    draw.ellipse((x - 2, y - 24 - 2, x + 2, y - 24 + 2), fill=_rgba((255, 255, 220)))


def _draw_bench(draw, x: int, y: int, wide: bool):
    if wide:
        _draw_round_rect(draw, (x - 14, y - 4, x + 14, y + 4), fill=_rgba((110, 82, 58)), radius=2)
        draw.rectangle((x - 12, y + 4, x - 8, y + 10), fill=_rgba((90, 68, 48)))
        draw.rectangle((x + 8, y + 4, x + 12, y + 10), fill=_rgba((90, 68, 48)))
    else:
        _draw_round_rect(draw, (x - 4, y - 12, x + 4, y + 12), fill=_rgba((110, 82, 58)), radius=2)
        draw.rectangle((x - 10, y - 8, x - 4, y - 4), fill=_rgba((90, 68, 48)))
        draw.rectangle((x - 10, y + 6, x - 4, y + 10), fill=_rgba((90, 68, 48)))


def _draw_decorations_pil(draw, decorations, origin: tuple[int, int]):
    for item in decorations:
        lx, ly = _world_to_local(item["x"], item["y"], origin)
        kind = item.get("type", "tree")
        if kind == "tree":
            _draw_tree(draw, lx, ly, item.get("scale", 1.0))
        elif kind == "lamp":
            _draw_lamp(draw, lx, ly)
        elif kind == "bench":
            _draw_bench(draw, lx, ly, item.get("wide", True))


def _darken(color, amount):
    return tuple(max(0, c - amount) for c in color)


def _draw_background_pil(draw, canvas_w: int, canvas_h: int, grass_rect: tuple[int, int, int, int] | None):
    for y in range(canvas_h):
        t = y / max(1, canvas_h - 1)
        r = int(210 + (228 - 210) * t)
        g = int(228 + (238 - 228) * t)
        b = int(245 + (220 - 245) * t)
        draw.line((0, y, canvas_w, y), fill=_rgba((r, g, b)))
    if grass_rect and grass_rect[2] > 0 and grass_rect[3] > 0:
        gx, gy, gw, gh = grass_rect
        draw.rectangle((gx, gy, gx + gw, gy + gh), fill=_rgba(GRASS_BASE))


def _draw_block_detail_pil(draw, rect: tuple[int, int, int, int], kind: str, block_seed: int):
    rng = random.Random(block_seed)
    base, accent = BLOCK_STYLES.get(kind, BLOCK_STYLES["residential"])
    left, top, right, bottom = rect
    _draw_round_rect(draw, rect, fill=_rgba(base), outline=_rgba(accent), width=2, radius=4)

    if kind == "park":
        area = max(1, (right - left) * (bottom - top))
        for _ in range(max(3, area // 8000)):
            tx = rng.randint(left + 8, max(left + 8, right - 8))
            ty = rng.randint(top + 8, max(top + 8, bottom - 8))
            rr = rng.randint(5, 11)
            draw.ellipse((tx - rr, ty - rr, tx + rr, ty + rr), fill=_rgba((48, 96, 52)))
        return

    cols = max(2, (right - left) // 55)
    rows = max(2, (bottom - top) // 55)
    cell_w = max(12, (right - left - 16) // cols)
    cell_h = max(12, (bottom - top - 16) // rows)
    for row in range(rows):
        for col in range(cols):
            if rng.random() < 0.22:
                continue
            bx = left + 8 + col * cell_w
            by = top + 8 + row * cell_h
            bw = min(cell_w - 6, right - bx - 4)
            bh = min(cell_h - 6, bottom - by - 4)
            if bw < 8 or bh < 8:
                continue
            shade = _darken(accent, rng.randint(0, 28))
            win = (220, 230, 245) if rng.random() < 0.35 else (180, 200, 220)
            _draw_round_rect(draw, (bx, by, bx + bw, by + bh), fill=_rgba(shade), radius=2)
            if kind == "commercial" and bw > 14 and bh > 14:
                _draw_round_rect(
                    draw,
                    (bx + 3, by + 3, bx + bw // 2 + 1, by + bh // 2 + 1),
                    fill=_rgba(win),
                    radius=1,
                )


def _draw_city_blocks_pil(draw, blocks, origin: tuple[int, int]):
    ox, oy = origin
    for block in blocks:
        left = block["x"] - ox
        top = block["y"] - oy
        rect = (left, top, left + block["w"], top + block["h"])
        _draw_block_detail_pil(draw, rect, block.get("kind", "residential"), block.get("seed", 0))


def _draw_road_pil(draw, road_rect: Rect, direction: str, origin: tuple[int, int]):
    ox, oy = origin
    left = road_rect.left - ox
    top = road_rect.top - oy
    right = road_rect.right - ox
    bottom = road_rect.bottom - oy
    sidewalk_pad = 5
    walk = (left - sidewalk_pad, top - sidewalk_pad, right + sidewalk_pad, bottom + sidewalk_pad)
    _draw_round_rect(draw, walk, fill=_rgba(SIDEWALK), radius=2)
    _draw_round_rect(draw, (left, top, right, bottom), fill=_rgba(ROAD_ASPHALT), outline=_rgba(ROAD_EDGE), width=1, radius=1)

    is_ew = direction == "vertical"
    width = right - left
    height = bottom - top
    if is_ew and width > 80:
        cy = (top + bottom) // 2
        for x in range(left + 12, right - 12, 22):
            draw.line((x, cy, x + 10, cy), fill=_rgba(LANE_MARK), width=2)
    elif not is_ew and height > 80:
        cx = (left + right) // 2
        for y in range(top + 12, bottom - 12, 22):
            draw.line((cx, y, cx, y + 10), fill=_rgba(LANE_MARK), width=2)


def _draw_goal_pil(draw, goal_rect: Rect, origin: tuple[int, int]):
    ox, oy = origin
    left = goal_rect.left - ox
    top = goal_rect.top - oy
    right = goal_rect.right - ox
    bottom = goal_rect.bottom - oy
    glow = (left - 16, top - 16, right + 16, bottom + 16)
    _draw_round_rect(draw, glow, fill=_rgba((255, 220, 80)), radius=10)
    _draw_round_rect(draw, (left, top, right, bottom), fill=_rgba((34, 88, 210)), outline=_rgba((255, 255, 255)), width=2, radius=8)
    star_cx = (left + right) // 2
    star_cy = (top + bottom) // 2
    draw.polygon(
        [
            (star_cx, star_cy - 10),
            (star_cx + 4, star_cy - 2),
            (star_cx + 10, star_cy - 2),
            (star_cx + 5, star_cy + 3),
            (star_cx + 7, star_cy + 10),
            (star_cx, star_cy + 6),
            (star_cx - 7, star_cy + 10),
            (star_cx - 5, star_cy + 3),
            (star_cx - 10, star_cy - 2),
            (star_cx - 4, star_cy - 2),
        ],
        fill=_rgba((255, 240, 120)),
    )


def traffic_housing_rect(
    crosswalk: Rect, direction: str, approach: str = APPROACH_WEST
) -> Rect:
    return _signal_housing_rect(crosswalk, direction, approach)


def _draw_crosswalk_pil(draw, crosswalk: Rect, origin: tuple[int, int]) -> None:
    ox, oy = origin
    left = crosswalk.left - ox
    top = crosswalk.top - oy
    right = crosswalk.right - ox
    bottom = crosswalk.bottom - oy
    _draw_round_rect(draw, (left, top, right, bottom), fill=_rgba(CROSSWALK_WHITE), radius=1)
    stripe_step = 10
    stripe_color = _rgba((210, 210, 215))
    if right - left >= bottom - top:
        for sx in range(left, right, stripe_step):
            draw.line((sx, top, sx, bottom), fill=stripe_color, width=2)
    else:
        for sy in range(top, bottom, stripe_step):
            draw.line((left, sy, right, sy), fill=stripe_color, width=2)


def _draw_traffic_static_pil(draw, road_states: list, origin: tuple[int, int]) -> None:
    for state in road_states:
        crosswalk = state["crosswalk"]
        _draw_crosswalk_pil(draw, crosswalk, origin)

        approach = state.get("approach", "west")
        housing = traffic_housing_rect(crosswalk, state["direction"], approach)
        h_left = housing.left - origin[0]
        h_top = housing.top - origin[1]
        h_right = housing.right - origin[0]
        h_bottom = housing.bottom - origin[1]
        _draw_round_rect(draw, (h_left, h_top, h_right, h_bottom), fill=_rgba((25, 25, 25)), radius=2)
        _draw_round_rect(
            draw,
            (h_left, h_top, h_right, h_bottom),
            outline=_rgba((70, 70, 70)),
            width=2,
            radius=2,
        )
        for bx, by in _bulb_positions_pil(
            housing, state["direction"], approach, origin
        ):
            draw.ellipse((bx - 5, by - 5, bx + 5, by + 5), fill=_rgba((45, 45, 48)))


def _turn_bulb_position_pil(
    housing: Rect, direction: str, approach: str, origin: tuple[int, int]
) -> tuple[int, int]:
    ox, oy = origin
    tx, ty = _signal_turn_bulb_position(housing, direction, approach)
    return (tx - ox, ty - oy)


def _bulb_positions_pil(
    housing: Rect, direction: str, approach: str, origin: tuple[int, int]
) -> list[tuple[int, int]]:
    ox, oy = origin
    return [(bx - ox, by - oy) for bx, by in _signal_bulb_positions(housing, direction, approach)]


def bake_static_map(
    roads,
    city_blocks,
    decorations,
    world_bounds: Rect,
    goal_rect: Rect,
    *,
    map_id: str = "map",
    road_states: list | None = None,
) -> BakedMapLayer:
    """Rasterize gradient, blocks, decor, roads, traffic static, and goal once per map."""
    w, h = world_bounds.width, world_bounds.height
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    origin = (world_bounds.left, world_bounds.top)
    grass = (0, 0, w, h)
    _draw_background_pil(draw, w, h, grass)
    if city_blocks:
        _draw_city_blocks_pil(draw, city_blocks, origin)
        _draw_decorations_pil(draw, decorations or [], origin)
    for road in roads:
        _draw_road_pil(draw, road.rect, road.direction, origin)
    if road_states:
        _draw_traffic_static_pil(draw, road_states, origin)
    _draw_goal_pil(draw, goal_rect, origin)
    texture = arcade.Texture(img, hash=f"map_{map_id}_{world_bounds.width}x{world_bounds.height}")
    tiles = _tile_baked_image(img, world_bounds, map_id)
    return BakedMapLayer(texture=texture, world_bounds=world_bounds.copy(), tiles=tiles)


def _tile_baked_image(img: Image.Image, world_bounds: Rect, map_id: str) -> tuple[MapTile, ...]:
    """Split the baked map into fixed-size tiles for viewport-culled drawing."""
    tile_size = MAP_TILE_SIZE
    w, h = img.width, img.height
    tiles: list[MapTile] = []
    for top_px in range(0, h, tile_size):
        for left_px in range(0, w, tile_size):
            tile_w = min(tile_size, w - left_px)
            tile_h = min(tile_size, h - top_px)
            if tile_w <= 0 or tile_h <= 0:
                continue
            crop = img.crop((left_px, top_px, left_px + tile_w, top_px + tile_h))
            world_rect = Rect(
                world_bounds.left + left_px,
                world_bounds.top + top_px,
                tile_w,
                tile_h,
            )
            tile_texture = arcade.Texture(
                crop,
                hash=f"map_tile_{map_id}_{left_px}_{top_px}_{tile_w}x{tile_h}",
            )
            tiles.append(MapTile(world_rect=world_rect, texture=tile_texture))
    return tuple(tiles)


def draw_baked_map(
    baked: BakedMapLayer,
    camera_offset: tuple[int, int],
    sim_height: int,
    view_rect: Rect | None = None,
    *,
    layout=None,
) -> None:
    from .pathwise_render import draw_sim_texture_rect

    if baked.tiles and view_rect is not None:
        for tile in baked.tiles:
            if collide(view_rect, tile.world_rect):
                draw_sim_texture_rect(
                    tile.world_rect, tile.texture, camera_offset, sim_height, layout
                )
        return

    draw_sim_texture_rect(
        baked.world_bounds, baked.texture, camera_offset, sim_height, layout
    )
