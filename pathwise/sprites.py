"""Top-down car and pedestrian sprites, car appearance archetypes, and honk visuals."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import arcade
from PIL import Image, ImageDraw

from .commonUtils import CAR_WIDTH, CAR_HEIGHT, PEDESTRIAN_SIZE
from .geom import Rect


@dataclass(frozen=True)
class SpriteAsset:
    """Procedural art packaged for logic (size) and Arcade rendering (texture)."""

    texture: arcade.Texture
    width: int
    height: int

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height


def _rgba(color, alpha=255):
    if len(color) == 4:
        return color
    return (*color, alpha)


def _new_canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _rect_xyxy(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    if w <= 0 or h <= 0:
        return None
    return (x, y, x + w, y + h)


def _draw_round_rect(draw, xy, fill=None, outline=None, width=1, radius=0):
    if xy is None:
        return
    x0, y0, x1, y1 = xy
    if x1 <= x0 or y1 <= y0:
        return
    if radius > 0:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    elif outline is not None and width:
        draw.rectangle(xy, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(xy, fill=fill)


def _texture_from_image(img: Image.Image, name: str) -> arcade.Texture:
    return arcade.Texture(img, hash=name)


def _asset_from_image(img: Image.Image, name: str) -> SpriteAsset:
    return SpriteAsset(texture=_texture_from_image(img, name), width=img.width, height=img.height)


def _paste_center(canvas: Image.Image, piece: Image.Image) -> None:
    cx = (canvas.width - piece.width) // 2
    cy = (canvas.height - piece.height) // 2
    canvas.alpha_composite(piece, (cx, cy))

WHEEL = (33, 33, 33)
HEADLIGHT = (255, 249, 196)
TAILLIGHT = (255, 143, 0)
PLAYER_FILL = (38, 166, 154)
PLAYER_OUTLINE = (255, 255, 255)

ARCHETYPE_COUNT = 100
WHITE_ARCHETYPE_COUNT = 50
TURN_SIGNAL_COLOR = (255, 214, 64)
TURN_SIGNAL_DIM = (180, 140, 40)

WHITE_STYLES = ("sedan", "sport", "compact", "suv", "wagon", "pickup", "van", "hatch")
WHITE_TONES = (
    (252, 252, 252),
    (248, 248, 250),
    (245, 245, 248),
    (250, 248, 242),
    (242, 246, 250),
    (255, 253, 248),
    (238, 240, 244),
    (248, 250, 252),
    (253, 251, 245),
    (246, 248, 252),
)
WHITE_GLASS_TINTS = (
    (188, 214, 238),
    (200, 220, 240),
    (175, 205, 230),
    (210, 225, 242),
    (165, 198, 225),
    (195, 215, 235),
    (180, 210, 228),
    (205, 222, 240),
    (170, 200, 222),
    (190, 212, 234),
)
WHITE_TRIMS = (
    (55, 55, 58),
    (75, 78, 82),
    (40, 40, 44),
    (95, 98, 102),
    (30, 32, 36),
    (110, 112, 118),
    (65, 68, 72),
    (88, 90, 94),
    (48, 50, 54),
    (100, 102, 108),
)
WHITE_ACCENTS = (
    None,
    (180, 30, 35),
    (30, 60, 120),
    (40, 40, 44),
    (120, 125, 130),
    (200, 170, 40),
    (25, 110, 95),
    None,
    (90, 90, 95),
    (170, 90, 30),
)

COLOR_PALETTE = (
    ((198, 40, 40), (229, 57, 53), (200, 230, 255), (120, 25, 25)),
    ((25, 70, 140), (40, 95, 175), (170, 210, 245), (15, 45, 95)),
    ((35, 35, 40), (58, 58, 64), (190, 205, 220), (20, 20, 24)),
    ((120, 125, 130), (150, 155, 160), (200, 220, 235), (80, 84, 88)),
    ((170, 140, 35), (200, 168, 50), (210, 230, 245), (120, 95, 20)),
    ((55, 110, 75), (75, 140, 95), (195, 225, 240), (35, 75, 50)),
    ((130, 55, 120), (160, 75, 145), (210, 225, 245), (90, 35, 85)),
    ((210, 95, 35), (235, 125, 55), (215, 235, 250), (140, 60, 20)),
    ((90, 50, 30), (120, 70, 45), (195, 215, 230), (60, 32, 18)),
    ((15, 120, 130), (35, 150, 160), (185, 220, 240), (8, 85, 95)),
    ((200, 50, 70), (225, 75, 95), (210, 230, 248), (130, 30, 45)),
    ((75, 75, 175), (100, 100, 205), (200, 225, 245), (48, 48, 120)),
    ((140, 160, 50), (170, 190, 70), (205, 228, 242), (95, 110, 30)),
    ((60, 60, 60), (88, 88, 88), (185, 200, 215), (35, 35, 35)),
    ((220, 200, 185), (240, 220, 205), (215, 230, 245), (150, 130, 115)),
    ((100, 30, 30), (130, 50, 50), (200, 220, 238), (65, 18, 18)),
    ((30, 90, 170), (50, 120, 200), (180, 210, 240), (18, 60, 120)),
    ((160, 80, 40), (190, 105, 55), (210, 228, 242), (110, 52, 22)),
    ((110, 110, 200), (140, 140, 225), (205, 225, 245), (70, 70, 150)),
    ((45, 95, 45), (65, 125, 65), (190, 220, 235), (28, 68, 28)),
    ((255, 140, 0), (255, 170, 40), (220, 235, 250), (180, 95, 0)),
)


def _clamp_channel(value):
    return max(0, min(255, int(value)))


def _darken(rgb, amount=32):
    return tuple(_clamp_channel(c - amount) for c in rgb)


def _lighten(rgb, amount=18):
    return tuple(_clamp_channel(c + amount) for c in rgb)


def _shift_tone(rgb, delta):
    return tuple(_clamp_channel(c + delta) for c in rgb)


def _build_white_archetype(style_index, tone_index):
    style = WHITE_STYLES[style_index]
    body = _shift_tone(WHITE_TONES[tone_index], (style_index % 3) - 1)
    cabin = _lighten(body, 6 + (tone_index % 4))
    trim = WHITE_TRIMS[(style_index + tone_index) % len(WHITE_TRIMS)]
    glass = WHITE_GLASS_TINTS[tone_index]
    accent = WHITE_ACCENTS[(style_index + tone_index) % len(WHITE_ACCENTS)]
    return {
        "style": style,
        "body": body,
        "cabin": cabin,
        "trim": trim,
        "glass": glass,
        "accent": list(accent) if accent else None,
        "stripe": (style_index + tone_index) % 4 == 0,
        "roof_rack": style in ("suv", "wagon", "van") and tone_index % 5 == 0,
    }


def _build_car_archetypes(count=ARCHETYPE_COUNT, white_count=WHITE_ARCHETYPE_COUNT):
    archetypes = []
    styles_n = len(WHITE_STYLES)
    tones_n = len(WHITE_TONES)
    for i in range(white_count):
        archetypes.append(_build_white_archetype(i % styles_n, i % tones_n))

    color_styles = WHITE_STYLES
    remaining = count - white_count
    for i in range(remaining):
        body, cabin, glass, trim = COLOR_PALETTE[i % len(COLOR_PALETTE)]
        variant = i // len(COLOR_PALETTE)
        body = _shift_tone(body, -variant * 5)
        cabin = _shift_tone(cabin, -variant * 4)
        archetypes.append(
            {
                "style": color_styles[i % len(color_styles)],
                "body": body,
                "cabin": cabin,
                "trim": trim,
                "glass": glass,
                "accent": None,
                "stripe": i % 3 == 0,
                "roof_rack": False,
            }
        )
    return archetypes


CAR_ARCHETYPES = _build_car_archetypes()


def pick_random_archetype_index(rng=None):
    r = rng if rng is not None else random
    if r.random() < 0.5:
        return r.randrange(WHITE_ARCHETYPE_COUNT)
    return WHITE_ARCHETYPE_COUNT + r.randrange(ARCHETYPE_COUNT - WHITE_ARCHETYPE_COUNT)


def get_archetype(index):
    return CAR_ARCHETYPES[index % len(CAR_ARCHETYPES)]


def serialize_archetypes_for_log():
    out = []
    for archetype in CAR_ARCHETYPES:
        entry = {
            "style": archetype["style"],
            "body": list(archetype["body"]),
            "cabin": list(archetype["cabin"]),
            "trim": list(archetype["trim"]),
            "glass": list(archetype["glass"]),
            "stripe": bool(archetype.get("stripe")),
            "roof_rack": bool(archetype.get("roof_rack")),
        }
        if archetype.get("accent"):
            entry["accent"] = list(archetype["accent"])
        out.append(entry)
    return out


def _layout(style, width, height, vertical):
    if style == "sport":
        cab = (0.26, 0.48, 0.12, 0.76) if not vertical else (0.12, 0.26, 0.76, 0.48)
    elif style == "compact":
        cab = (0.24, 0.50, 0.14, 0.72) if not vertical else (0.14, 0.24, 0.72, 0.50)
    elif style == "suv":
        cab = (0.12, 0.78, 0.08, 0.84) if not vertical else (0.08, 0.12, 0.84, 0.78)
    elif style == "wagon":
        cab = (0.14, 0.76, 0.10, 0.82) if not vertical else (0.10, 0.14, 0.82, 0.76)
    elif style == "pickup":
        cab = (0.14, 0.42, 0.10, 0.80) if not vertical else (0.10, 0.14, 0.80, 0.42)
    elif style == "van":
        cab = (0.10, 0.80, 0.08, 0.86) if not vertical else (0.08, 0.10, 0.86, 0.80)
    elif style == "hatch":
        cab = (0.18, 0.58, 0.12, 0.78) if not vertical else (0.12, 0.18, 0.78, 0.58)
    else:
        cab = (0.18, 0.64, 0.12, 0.78) if not vertical else (0.12, 0.18, 0.78, 0.64)
    return cab


def _wheel(draw, cx, cy, rx, ry):
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=_rgba(WHEEL))


def _draw_car_body(draw, width, height, vertical, archetype):
    body = archetype["body"]
    cabin = archetype["cabin"]
    trim = archetype["trim"]
    glass = archetype["glass"]
    style = archetype.get("style", "sedan")
    accent = tuple(archetype["accent"]) if archetype.get("accent") else None
    stripe = archetype.get("stripe", False)
    roof_rack = archetype.get("roof_rack", False)

    corner = min(6, (height if not vertical else width) // 3)
    cx, cw, cy, ch = _layout(style, width, height, vertical)

    cab_x = int(width * cx)
    cab_y = int(height * cy)
    cab_w = int(width * cw)
    cab_h = int(height * ch)
    cab_rect = _rect_xyxy(cab_x, cab_y, cab_w, cab_h)

    if not vertical:
        _draw_round_rect(
            draw,
            _rect_xyxy(1, 5, width - 2, height - 10),
            fill=_rgba(body),
            outline=_rgba(trim),
            width=1,
            radius=corner,
        )
        if style == "pickup":
            bed_x = int(width * 0.48)
            _draw_round_rect(
                draw,
                _rect_xyxy(bed_x, 7, width - bed_x - 2, height - 14),
                fill=_rgba(_darken(body, 18)),
                radius=2,
            )
        _draw_round_rect(draw, cab_rect, fill=_rgba(cabin), radius=3)
        glass_rect = _rect_xyxy(
            cab_x + int(cab_w * 0.14),
            cab_y + 2,
            int(cab_w * 0.72),
            max(1, cab_h - 4),
        )
        _draw_round_rect(draw, glass_rect, fill=_rgba(glass), radius=2)
        if stripe and accent:
            _draw_round_rect(
                draw, _rect_xyxy(2, height // 2 - 1, width - 4, 2), fill=_rgba(accent)
            )
        if roof_rack and cab_rect is not None:
            draw.line(
                (cab_rect[0], cab_rect[1] - 2, cab_rect[2], cab_rect[1] - 2),
                fill=_rgba(trim),
                width=2,
            )
        _wheel(draw, 7, 3, 4, 2)
        _wheel(draw, width - 7, 3, 4, 2)
        _wheel(draw, 7, height - 3, 4, 2)
        _wheel(draw, width - 7, height - 3, 4, 2)
        draw.ellipse((width - 7, height // 2 - 2, width - 3, height // 2 + 2), fill=_rgba(HEADLIGHT))
        draw.ellipse((3, height // 2 - 2, 7, height // 2 + 2), fill=_rgba(TAILLIGHT))
        _draw_turn_signal_dots(draw, width, height, vertical=False)
    else:
        _draw_round_rect(
            draw,
            _rect_xyxy(5, 1, width - 10, height - 2),
            fill=_rgba(body),
            outline=_rgba(trim),
            width=1,
            radius=corner,
        )
        if style == "pickup":
            bed_y = int(height * 0.48)
            _draw_round_rect(
                draw,
                _rect_xyxy(7, bed_y, width - 14, height - bed_y - 2),
                fill=_rgba(_darken(body, 18)),
                radius=2,
            )
        _draw_round_rect(draw, cab_rect, fill=_rgba(cabin), radius=3)
        glass_rect = _rect_xyxy(
            cab_x + 2,
            cab_y + int(cab_h * 0.14),
            max(1, cab_w - 4),
            max(1, int(cab_h * 0.86)),
        )
        _draw_round_rect(draw, glass_rect, fill=_rgba(glass), radius=2)
        if stripe and accent:
            _draw_round_rect(
                draw, _rect_xyxy(width // 2 - 1, 2, 2, height - 4), fill=_rgba(accent)
            )
        if roof_rack and cab_rect is not None:
            draw.line(
                (cab_rect[0] - 2, cab_rect[1], cab_rect[0] - 2, cab_rect[3]),
                fill=_rgba(trim),
                width=2,
            )
        _wheel(draw, 3, 7, 2, 4)
        _wheel(draw, width - 3, 7, 2, 4)
        _wheel(draw, 3, height - 7, 2, 4)
        _wheel(draw, width - 3, height - 7, 2, 4)
        draw.ellipse((width // 2 - 2, 3, width // 2 + 2, 7), fill=_rgba(HEADLIGHT))
        draw.ellipse((width // 2 - 2, height - 7, width // 2 + 2, height - 3), fill=_rgba(TAILLIGHT))
        _draw_turn_signal_dots(draw, width, height, vertical=True)


def _signal_corner(width, height, vertical: bool, direction: int, side: int) -> tuple[int, int]:
    """side: -1 left, 1 right in driver's frame (before direction flip)."""
    if not vertical:
        if direction > 0:
            return (width // 2, 4 if side < 0 else height - 5)
        return (width // 2, height - 5 if side < 0 else 4)
    if direction > 0:
        return (4 if side < 0 else width - 5, height // 2)
    return (width - 5 if side < 0 else 4, height // 2)


def _draw_turn_signal_dots(draw, width, height, vertical: bool):
    """Static dim markers; active blink drawn in draw_turn_signal overlay."""
    for side in (-1, 1):
        pos = _signal_corner(width, height, vertical, 1, side)
        draw.ellipse((pos[0] - 2, pos[1] - 2, pos[0] + 2, pos[1] + 2), fill=_rgba(TURN_SIGNAL_DIM))


def _left_of_travel_vector(vertical: bool, direction: int) -> tuple[int, int]:
    """Screen-space unit-ish vector to the left of travel (y down)."""
    direction = 1 if direction >= 0 else -1
    if not vertical:
        fx, fy = direction, 0
    else:
        fx, fy = 0, direction
    return fy, -fx


def _corner_side_for_screen_vector(
    vertical: bool, direction: int, vx: int, vy: int
) -> int:
    """Pick sprite corner (-1/+1) that points most toward screen vector (vx, vy)."""
    direction = 1 if direction >= 0 else -1
    bw, bh = _body_dimensions(vertical)
    best_side = -1
    best_dot = -1e9
    for side in (-1, 1):
        lx, ly = _signal_corner(bw, bh, vertical, direction, side)
        dot = (lx - bw * 0.5) * vx + (ly - bh * 0.5) * vy
        if dot > best_dot:
            best_dot = dot
            best_side = side
    return best_side


def turn_signal_corner_side(vertical: bool, direction: int, turn_side: int) -> int:
    """Blinker on the body side that faces the turn (top-down), not driver-side LH."""
    if turn_side == 0:
        return 0
    lvx, lvy = _left_of_travel_vector(vertical, direction)
    if turn_side > 0:
        lvx, lvy = -lvx, -lvy
    return _corner_side_for_screen_vector(vertical, direction, lvx, lvy)


def _body_dimensions(vertical: bool) -> tuple[int, int]:
    if vertical:
        return CAR_HEIGHT, CAR_WIDTH
    return CAR_WIDTH, CAR_HEIGHT


def _turn_signal_local_offset(
    vertical: bool, direction: int, corner_side: int
) -> tuple[float, float]:
    """Offset from body center to blinker on the unrotated body (east-facing base)."""
    bw, bh = _body_dimensions(vertical)
    lx, ly = _signal_corner(bw, bh, vertical, direction, corner_side)
    return lx - bw * 0.5, ly - bh * 0.5


def _rotate_offset(ox: float, oy: float, angle_deg: float) -> tuple[float, float]:
    """Match PIL rotate (CCW, screen y down)."""
    rad = math.radians(angle_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    return ox * cos_r - oy * sin_r, ox * sin_r + oy * cos_r


def turn_signal_screen_pos(
    car_rect: Rect,
    vertical: bool,
    direction: int,
    turn_side: int,
    camera_offset: tuple[int, int],
    angle_deg: float | None = None,
) -> tuple[int, int] | None:
    """World blinker position; pass angle_deg while the car sprite is rotated in a square box."""
    corner_side = turn_signal_corner_side(vertical, direction, turn_side)
    if corner_side == 0:
        return None
    ox, oy = _turn_signal_local_offset(vertical, direction, corner_side)
    if angle_deg is not None:
        ox, oy = _rotate_offset(ox, oy, angle_deg)
        sx = car_rect.centerx + ox - camera_offset[0]
        sy = car_rect.centery + oy - camera_offset[1]
        return int(round(sx)), int(round(sy))
    bw, bh = _body_dimensions(vertical)
    lx, ly = _signal_corner(bw, bh, vertical, direction, corner_side)
    return (
        car_rect.x + lx - camera_offset[0],
        car_rect.y + ly - camera_offset[1],
    )


def draw_turn_signal(
    window_height: int,
    car_rect,
    vertical: bool,
    direction: int,
    turn_side: int,
    blink_on: bool,
    camera_offset,
    angle_deg: float | None = None,
):
    """Amber indicator on the driver's side for the intended turn (left-hand traffic)."""
    pos = turn_signal_screen_pos(
        car_rect, vertical, direction, turn_side, camera_offset, angle_deg
    )
    if pos is None:
        return
    from .pathwise_render import sim_point_to_arcade

    ax, ay = sim_point_to_arcade(pos[0], pos[1], window_height)
    color = TURN_SIGNAL_COLOR if blink_on else TURN_SIGNAL_DIM
    arcade.draw_circle_filled(ax, ay, 3, color)
    arcade.draw_circle_filled(ax, ay, 1, (255, 240, 180))


_car_surface_cache: dict[tuple[int, int, int], SpriteAsset] = {}
_car_box_surface_cache: dict[tuple[int, int, int, int], SpriteAsset] = {}


def car_surface_cache_key(vertical=False, direction=1, archetype_index=0) -> tuple[int, int, int]:
    d_sign = 1 if direction >= 0 else -1
    v_key = 1 if vertical else 0
    return (v_key, d_sign, int(archetype_index) % ARCHETYPE_COUNT)


def car_box_surface_cache_key(
    archetype_index: int, angle_deg: float, box_w: int, box_h: int
) -> tuple[int, int, int, int]:
    angle_q = int(round(angle_deg / 2.0) * 2) % 360
    ai = int(archetype_index) % ARCHETYPE_COUNT
    return (ai, angle_q, int(box_w), int(box_h))


def clear_texture_caches() -> None:
    _car_surface_cache.clear()
    _car_box_surface_cache.clear()


def car_travel_angle_deg(vertical: bool, direction: int) -> float:
    """Degrees for PIL rotate from the east-facing horizontal base sprite."""
    direction = 1 if direction >= 0 else -1
    if not vertical:
        return 0.0 if direction > 0 else 180.0
    return -90.0 if direction > 0 else 90.0


def make_car_surface_at_angle(archetype_index: int, angle_deg: float) -> SpriteAsset:
    """Rotated car on a square canvas (legacy); prefer make_car_rotated_in_box for turns."""
    side = max(CAR_WIDTH, CAR_HEIGHT)
    return make_car_rotated_in_box(archetype_index, angle_deg, side, side)


def make_car_rotated_in_box(
    archetype_index: int, angle_deg: float, box_w: int, box_h: int
) -> SpriteAsset:
    key = car_box_surface_cache_key(archetype_index, angle_deg, box_w, box_h)
    cached = _car_box_surface_cache.get(key)
    if cached is not None:
        return cached
    angle_q = key[1]
    ai = key[0]
    base = make_car_surface(vertical=False, direction=1, archetype_index=ai)
    base_img = base.texture.image.copy()
    if angle_q == 0:
        rotated = base_img
    else:
        rotated = base_img.rotate(angle_q, expand=True, resample=Image.Resampling.BICUBIC)
    canvas, _ = _new_canvas(box_w, box_h)
    _paste_center(canvas, rotated)
    asset = _asset_from_image(canvas, f"car_box_{key}")
    _car_box_surface_cache[key] = asset
    return asset


def make_car_surface(vertical=False, direction=1, archetype_index=0) -> SpriteAsset:
    key = car_surface_cache_key(vertical, direction, archetype_index)
    cached = _car_surface_cache.get(key)
    if cached is not None:
        return cached

    if vertical:
        width, height = CAR_HEIGHT, CAR_WIDTH
    else:
        width, height = CAR_WIDTH, CAR_HEIGHT

    img, draw = _new_canvas(width, height)
    archetype = get_archetype(archetype_index)
    _draw_car_body(draw, width, height, vertical, archetype)

    if not vertical and direction < 0:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    elif vertical and direction < 0:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    asset = _asset_from_image(img, f"car_{key}")
    _car_surface_cache[key] = asset
    return asset


def player_body_hitbox(world_rect: Rect) -> Rect:
    """
    Tight hitbox matching head + torso in make_pedestrian_surface (not the full square).
    """
    w, h = world_rect.width, world_rect.height
    if w <= 0 or h <= 0:
        return world_rect.copy()
    cx = world_rect.left + w // 2
    head_r = max(2, int(w * 0.24))
    shoulder_w = max(4, int(w * 0.62))
    body_h = max(4, int(h * 0.42))
    head_cy = world_rect.top + int(h * 0.36)
    body_cy = world_rect.top + int(h * 0.62)

    head = Rect(0, 0, head_r * 2, head_r * 2)
    head.center = (cx, head_cy)
    body = Rect(0, 0, shoulder_w, body_h)
    body.center = (cx, body_cy)
    return head.union(body)


def car_collision_rect_into(rect: Rect, vertical: bool, out: Rect) -> Rect:
    """
    Body shell aligned with _draw_car_body (horizontal: (1,5,w-2,h-10), vertical: (5,1,w-10,h-2)).
    Writes into ``out`` to avoid per-peer allocations in hot collision loops.
    """
    if not vertical:
        out.x = rect.x + 1
        out.y = rect.y + 5
        out.w = max(1, rect.w - 2)
        out.h = max(1, rect.h - 10)
    else:
        out.x = rect.x + 5
        out.y = rect.y + 1
        out.w = max(1, rect.w - 10)
        out.h = max(1, rect.h - 2)
    return out


def car_collision_rect(rect: Rect, vertical: bool) -> Rect:
    """Allocate a new body-shell rect (prefer car_collision_rect_into in hot paths)."""
    return car_collision_rect_into(rect, vertical, rect.copy())


def car_collision_rect_turn(rect: Rect) -> Rect:
    """Axis-aligned shell while the car sprite is rotated mid-turn."""
    inset = max(2, min(rect.width, rect.height) // 8)
    r = rect.inflate(-inset * 2, -inset * 2)
    r.width = max(1, r.width)
    r.height = max(1, r.height)
    return r


_pedestrian_asset: SpriteAsset | None = None


def make_pedestrian_surface(size=PEDESTRIAN_SIZE) -> SpriteAsset:
    global _pedestrian_asset
    if _pedestrian_asset is not None and _pedestrian_asset.width == size:
        return _pedestrian_asset
    img, draw = _new_canvas(size, size)
    cx = size // 2
    head_r = max(4, int(size * 0.24))
    shoulder_w = int(size * 0.62)
    body_h = int(size * 0.42)
    head_cy = int(size * 0.36)
    body_cy = int(size * 0.62)

    draw.ellipse(
        (cx - shoulder_w // 2, body_cy - body_h // 2, cx + shoulder_w // 2, body_cy + body_h // 2),
        fill=_rgba(PLAYER_FILL),
        outline=_rgba(PLAYER_OUTLINE),
        width=1,
    )
    draw.ellipse(
        (cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r),
        fill=_rgba(PLAYER_FILL),
        outline=_rgba(PLAYER_OUTLINE),
        width=1,
    )
    _pedestrian_asset = _asset_from_image(img, "pedestrian")
    return _pedestrian_asset


_honk_label: arcade.Text | None = None


def draw_honk_bubble(window_height: int, car_rect, camera_offset):
    global _honk_label
    shifted = car_rect.move(-camera_offset[0], -camera_offset[1])
    cx = shifted.centerx
    cy = shifted.top - 8
    from .pathwise_render import sim_point_to_arcade, sim_rect_to_arcade_lbwh

    if _honk_label is None:
        _honk_label = arcade.Text(
            "HONK!",
            0,
            0,
            (122, 74, 0),
            font_size=20,
            anchor_x="center",
            anchor_y="center",
        )
    label = _honk_label
    pad_x, pad_y = 8, 4
    bubble_w = label.content_width + pad_x * 2
    bubble_h = label.content_height + pad_y * 2
    bubble_cx = cx
    bubble_cy = cy - 12
    left = bubble_cx - bubble_w // 2
    top = bubble_cy - bubble_h // 2
    lbwh = sim_rect_to_arcade_lbwh(left, top, bubble_w, bubble_h, window_height)
    arcade.draw_lbwh_rectangle_filled(lbwh[0], lbwh[1], bubble_w, bubble_h, (255, 243, 205))
    arcade.draw_lbwh_rectangle_outline(lbwh[0], lbwh[1], bubble_w, bubble_h, (245, 165, 36), 2)
    tx, ty = sim_point_to_arcade(bubble_cx, bubble_cy, window_height)
    label.x = tx
    label.y = ty
    label.draw()
    for offset in (-18, 18):
        arc_cx, arc_cy = sim_point_to_arcade(cx + offset, cy - 20, window_height)
        arcade.draw_arc_outline(
            arc_cx,
            arc_cy,
            20,
            16,
            (245, 165, 36),
            11,
            160,
            2,
        )
