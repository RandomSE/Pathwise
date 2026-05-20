"""City-block and road rendering for procedural maps."""

from __future__ import annotations

import random

import pygame

from map import ROAD_THICKNESS

# Block fill palettes (base, accent for simple façades)
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
        br = pygame.Rect(block["x"], block["y"], block["w"], block["h"])
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


def _draw_tree(surface, x: int, y: int, scale: float = 1.0):
    r = int(10 * scale)
    trunk_h = int(14 * scale)
    pygame.draw.rect(surface, (92, 62, 40), (x - 3, y, 6, trunk_h))
    pygame.draw.circle(surface, (42, 110, 52), (x, y - 4), r)
    pygame.draw.circle(surface, (58, 130, 62), (x - 5, y - 2), max(4, r - 4))
    pygame.draw.circle(surface, (48, 100, 48), (x + 5, y - 1), max(4, r - 5))


def _draw_lamp(surface, x: int, y: int):
    pygame.draw.line(surface, (70, 74, 78), (x, y), (x, y - 22), 3)
    pygame.draw.circle(surface, (255, 248, 200), (x, y - 24), 5)
    pygame.draw.circle(surface, (255, 255, 220), (x, y - 24), 2)


def _draw_bench(surface, x: int, y: int, wide: bool):
    if wide:
        pygame.draw.rect(surface, (110, 82, 58), (x - 14, y - 4, 28, 8), border_radius=2)
        pygame.draw.rect(surface, (90, 68, 48), (x - 12, y + 4, 4, 6))
        pygame.draw.rect(surface, (90, 68, 48), (x + 8, y + 4, 4, 6))
    else:
        pygame.draw.rect(surface, (110, 82, 58), (x - 4, y - 12, 8, 24), border_radius=2)
        pygame.draw.rect(surface, (90, 68, 48), (x - 10, y - 8, 6, 4))
        pygame.draw.rect(surface, (90, 68, 48), (x - 10, y + 6, 6, 4))


def draw_decorations(surface, decorations, camera_offset, view_rect):
    for item in decorations:
        sx = item["x"] - camera_offset[0]
        sy = item["y"] - camera_offset[1]
        if not view_rect.collidepoint(sx, sy):
            continue
        kind = item.get("type", "tree")
        if kind == "tree":
            _draw_tree(surface, sx, sy, item.get("scale", 1.0))
        elif kind == "lamp":
            _draw_lamp(surface, sx, sy)
        elif kind == "bench":
            _draw_bench(surface, sx, sy, item.get("wide", True))


def _shift_rect(rect, camera_offset):
    return rect.move(-camera_offset[0], -camera_offset[1])


def draw_background(surface, world_bounds, camera_offset):
    """Soft sky-to-ground gradient behind the map."""
    view = surface.get_rect()
    shifted = _shift_rect(world_bounds, camera_offset)
    top = max(0, shifted.top)
    for y in range(view.height):
        t = y / max(1, view.height - 1)
        r = int(210 + (228 - 210) * t)
        g = int(228 + (238 - 228) * t)
        b = int(245 + (220 - 245) * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (view.width, y))
    if shifted.colliderect(view):
        grass = (
            max(shifted.left, 0),
            max(shifted.top, 0),
            min(shifted.right, view.width) - max(shifted.left, 0),
            min(shifted.bottom, view.height) - max(shifted.top, 0),
        )
        if grass[2] > 0 and grass[3] > 0:
            pygame.draw.rect(surface, GRASS_BASE, grass)


def _draw_block_detail(surface, rect, kind: str, block_seed: int):
    rng = random.Random(block_seed)
    base, accent = BLOCK_STYLES.get(kind, BLOCK_STYLES["residential"])
    pygame.draw.rect(surface, base, rect, border_radius=4)
    pygame.draw.rect(surface, accent, rect, width=2, border_radius=4)

    if kind == "park":
        for _ in range(max(3, rect.w * rect.h // 8000)):
            tx = rng.randint(rect.left + 8, max(rect.left + 8, rect.right - 8))
            ty = rng.randint(rect.top + 8, max(rect.top + 8, rect.bottom - 8))
            pygame.draw.circle(surface, (48, 96, 52), (tx, ty), rng.randint(5, 11))
        return

    cols = max(2, rect.w // 55)
    rows = max(2, rect.h // 55)
    cell_w = max(12, (rect.w - 16) // cols)
    cell_h = max(12, (rect.h - 16) // rows)
    for row in range(rows):
        for col in range(cols):
            if rng.random() < 0.22:
                continue
            bx = rect.left + 8 + col * cell_w
            by = rect.top + 8 + row * cell_h
            bw = min(cell_w - 6, rect.right - bx - 4)
            bh = min(cell_h - 6, rect.bottom - by - 4)
            if bw < 8 or bh < 8:
                continue
            shade = _darken(accent, rng.randint(0, 28))
            win = (220, 230, 245) if rng.random() < 0.35 else (180, 200, 220)
            brect = pygame.Rect(bx, by, bw, bh)
            pygame.draw.rect(surface, shade, brect, border_radius=2)
            if kind == "commercial" and bw > 14 and bh > 14:
                pygame.draw.rect(
                    surface,
                    win,
                    (bx + 3, by + 3, max(4, bw // 2 - 2), max(4, bh // 2 - 2)),
                    border_radius=1,
                )


def _darken(color, amount):
    return tuple(max(0, c - amount) for c in color)


def draw_city_blocks(surface, blocks, camera_offset, view_rect):
    for block in blocks:
        rect = pygame.Rect(block["x"], block["y"], block["w"], block["h"])
        shifted = _shift_rect(rect, camera_offset)
        if not shifted.colliderect(view_rect):
            continue
        _draw_block_detail(
            surface, shifted, block.get("kind", "residential"), block.get("seed", 0)
        )


def draw_city_scape(
    surface, blocks, decorations, camera_offset, view_rect
):
    draw_city_blocks(surface, blocks, camera_offset, view_rect)
    draw_decorations(surface, decorations or [], camera_offset, view_rect)


def draw_road(surface, road_rect, direction: str, camera_offset, view_rect):
    shifted = _shift_rect(road_rect, camera_offset)
    if not shifted.colliderect(view_rect):
        return

    sidewalk_pad = 5
    walk = shifted.inflate(sidewalk_pad * 2, sidewalk_pad * 2)
    pygame.draw.rect(surface, SIDEWALK, walk, border_radius=2)

    pygame.draw.rect(surface, ROAD_ASPHALT, shifted, border_radius=1)
    pygame.draw.rect(surface, ROAD_EDGE, shifted, width=1, border_radius=1)

    # Lane centerline (E-W road = wide rect; N-S = tall rect)
    is_ew = direction == "vertical"
    if is_ew and shifted.width > 80:
        cy = shifted.centery
        for x in range(shifted.left + 12, shifted.right - 12, 22):
            pygame.draw.line(surface, LANE_MARK, (x, cy), (x + 10, cy), 2)
    elif not is_ew and shifted.height > 80:
        cx = shifted.centerx
        for y in range(shifted.top + 12, shifted.bottom - 12, 22):
            pygame.draw.line(surface, LANE_MARK, (cx, y), (cx, y + 10), 2)


def draw_goal(surface, goal_rect, camera_offset):
    shifted = _shift_rect(goal_rect, camera_offset)
    glow = shifted.inflate(16, 16)
    pygame.draw.rect(surface, (255, 220, 80), glow, border_radius=10)
    pygame.draw.rect(surface, (34, 88, 210), shifted, border_radius=8)
    pygame.draw.rect(surface, (255, 255, 255), shifted, width=2, border_radius=8)
    star_cx, star_cy = shifted.center
    pygame.draw.polygon(
        surface,
        (255, 240, 120),
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
    )


def draw_crosswalk(surface, crosswalk_rect, direction: str, camera_offset):
    shifted = _shift_rect(crosswalk_rect, camera_offset)
    pygame.draw.rect(surface, CROSSWALK_WHITE, shifted)
    stripe_step = 10
    if shifted.width >= shifted.height:
        for sx in range(shifted.left, shifted.right, stripe_step):
            pygame.draw.line(
                surface,
                (210, 210, 215),
                (sx, shifted.top),
                (sx, shifted.bottom),
                2,
            )
    else:
        for sy in range(shifted.top, shifted.bottom, stripe_step):
            pygame.draw.line(
                surface,
                (210, 210, 215),
                (shifted.left, sy),
                (shifted.right, sy),
                2,
            )
