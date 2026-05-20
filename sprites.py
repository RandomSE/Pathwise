"""Top-down car and pedestrian sprites, car appearance archetypes, and honk visuals."""

import random

import pygame

from commonUtils import CAR_WIDTH, CAR_HEIGHT, PEDESTRIAN_SIZE

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


def _wheel(surf, cx, cy, rx, ry):
    pygame.draw.ellipse(surf, WHEEL, (cx - rx, cy - ry, rx * 2, ry * 2))


def _draw_car_body(surf, width, height, vertical, archetype):
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

    if not vertical:
        body_rect = (1, 5, width - 2, height - 10)
        pygame.draw.rect(surf, body, body_rect, border_radius=corner)
        pygame.draw.rect(surf, trim, body_rect, width=1, border_radius=corner)
        if style == "pickup":
            bed_x = int(width * 0.48)
            pygame.draw.rect(surf, _darken(body, 18), (bed_x, 7, width - bed_x - 2, height - 14), border_radius=2)
        cab_rect = (int(width * cx), int(height * cy), int(width * cw), int(height * ch))
        pygame.draw.rect(surf, cabin, cab_rect, border_radius=3)
        glass_rect = (
            cab_rect[0] + int(cab_rect[2] * 0.14),
            cab_rect[1] + 2,
            int(cab_rect[2] * 0.72),
            cab_rect[3] - 4,
        )
        pygame.draw.rect(surf, glass, glass_rect, border_radius=2)
        if stripe and accent:
            pygame.draw.rect(surf, accent, (2, height // 2 - 1, width - 4, 2))
        if roof_rack:
            pygame.draw.line(surf, trim, (cab_rect[0], cab_rect[1] - 2), (cab_rect[0] + cab_rect[2], cab_rect[1] - 2), 2)
        _wheel(surf, 7, 3, 4, 2)
        _wheel(surf, width - 7, 3, 4, 2)
        _wheel(surf, 7, height - 3, 4, 2)
        _wheel(surf, width - 7, height - 3, 4, 2)
        pygame.draw.circle(surf, HEADLIGHT, (width - 5, height // 2), 2)
        pygame.draw.circle(surf, TAILLIGHT, (5, height // 2), 2)
        _draw_turn_signal_dots(surf, width, height, vertical=False)
    else:
        body_rect = (5, 1, width - 10, height - 2)
        pygame.draw.rect(surf, body, body_rect, border_radius=corner)
        pygame.draw.rect(surf, trim, body_rect, width=1, border_radius=corner)
        if style == "pickup":
            bed_y = int(height * 0.48)
            pygame.draw.rect(surf, _darken(body, 18), (7, bed_y, width - 14, height - bed_y - 2), border_radius=2)
        cab_rect = (int(width * cx), int(height * cy), int(width * cw), int(height * ch))
        pygame.draw.rect(surf, cabin, cab_rect, border_radius=3)
        glass_rect = (
            cab_rect[0] + 2,
            cab_rect[1] + int(cab_rect[3] * 0.14),
            cab_rect[2] - 4,
            int(cab_rect[3] * 0.72),
        )
        pygame.draw.rect(surf, glass, glass_rect, border_radius=2)
        if stripe and accent:
            pygame.draw.rect(surf, accent, (width // 2 - 1, 2, 2, height - 4))
        if roof_rack:
            pygame.draw.line(surf, trim, (cab_rect[0] - 2, cab_rect[1]), (cab_rect[0] - 2, cab_rect[1] + cab_rect[3]), 2)
        _wheel(surf, 3, 7, 2, 4)
        _wheel(surf, width - 3, 7, 2, 4)
        _wheel(surf, 3, height - 7, 2, 4)
        _wheel(surf, width - 3, height - 7, 2, 4)
        pygame.draw.circle(surf, HEADLIGHT, (width // 2, 5), 2)
        pygame.draw.circle(surf, TAILLIGHT, (width // 2, height - 5), 2)
        _draw_turn_signal_dots(surf, width, height, vertical=True)


def _signal_corner(width, height, vertical: bool, direction: int, side: int) -> tuple[int, int]:
    """side: -1 left, 1 right in driver's frame (before direction flip)."""
    if not vertical:
        if direction > 0:
            return (width // 2, 4 if side < 0 else height - 5)
        return (width // 2, height - 5 if side < 0 else 4)
    if direction > 0:
        return (4 if side < 0 else width - 5, height // 2)
    return (width - 5 if side < 0 else 4, height // 2)


def _draw_turn_signal_dots(surf, width, height, vertical: bool):
    """Static dim markers; active blink drawn in draw_turn_signal overlay."""
    for side in (-1, 1):
        pos = _signal_corner(width, height, vertical, 1, side)
        pygame.draw.circle(surf, TURN_SIGNAL_DIM, pos, 2)


def draw_turn_signal(
    surface,
    car_rect,
    vertical: bool,
    direction: int,
    turn_side: int,
    blink_on: bool,
    camera_offset,
):
    """Amber indicator on the side the car will turn (left-hand traffic)."""
    if turn_side == 0:
        return
    w = CAR_HEIGHT if vertical else CAR_WIDTH
    h = CAR_WIDTH if vertical else CAR_HEIGHT
    pos = _signal_corner(w, h, vertical, 1, turn_side)
    lx, ly = pos
    if not vertical and direction < 0:
        lx = w - lx
    elif vertical and direction < 0:
        ly = h - ly
    color = TURN_SIGNAL_COLOR if blink_on else TURN_SIGNAL_DIM
    cx = car_rect.x - camera_offset[0] + lx
    cy = car_rect.y - camera_offset[1] + ly
    pygame.draw.circle(surface, color, (cx, cy), 3)
    pygame.draw.circle(surface, (255, 240, 180), (cx, cy), 1)


def make_car_surface(vertical=False, direction=1, archetype_index=0):
    if vertical:
        width, height = CAR_HEIGHT, CAR_WIDTH
    else:
        width, height = CAR_WIDTH, CAR_HEIGHT

    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    archetype = get_archetype(archetype_index)
    _draw_car_body(surf, width, height, vertical, archetype)

    if not vertical and direction < 0:
        surf = pygame.transform.flip(surf, True, False)
    elif vertical and direction < 0:
        surf = pygame.transform.flip(surf, False, True)
    return surf


def player_body_hitbox(world_rect: pygame.Rect) -> pygame.Rect:
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

    head = pygame.Rect(0, 0, head_r * 2, head_r * 2)
    head.center = (cx, head_cy)
    body = pygame.Rect(0, 0, shoulder_w, body_h)
    body.center = (cx, body_cy)
    return head.union(body)


def car_collision_rect(rect: pygame.Rect, vertical: bool) -> pygame.Rect:
    """
    Body shell aligned with _draw_car_body (horizontal: (1,5,w-2,h-10), vertical: (5,1,w-10,h-2)).
    """
    r = rect.copy()
    if not vertical:
        r.x += 1
        r.y += 5
        r.w -= 2
        r.h -= 10
    else:
        r.x += 5
        r.y += 1
        r.w -= 10
        r.h -= 2
    r.width = max(1, r.width)
    r.height = max(1, r.height)
    return r


def make_pedestrian_surface(size=PEDESTRIAN_SIZE):
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = size // 2
    head_r = max(4, int(size * 0.24))
    shoulder_w = int(size * 0.62)
    body_h = int(size * 0.42)
    head_cy = int(size * 0.36)
    body_cy = int(size * 0.62)

    pygame.draw.ellipse(
        surf, PLAYER_FILL, (cx - shoulder_w // 2, body_cy - body_h // 2, shoulder_w, body_h)
    )
    pygame.draw.ellipse(
        surf, PLAYER_OUTLINE, (cx - shoulder_w // 2, body_cy - body_h // 2, shoulder_w, body_h), 1
    )
    pygame.draw.circle(surf, PLAYER_FILL, (cx, head_cy), head_r)
    pygame.draw.circle(surf, PLAYER_OUTLINE, (cx, head_cy), head_r, 1)
    return surf


def draw_honk_bubble(surface, car_rect, camera_offset, font):
    shifted = car_rect.move(-camera_offset[0], -camera_offset[1])
    cx = shifted.centerx
    cy = shifted.top - 8
    label = font.render("HONK!", True, (122, 74, 0))
    pad_x, pad_y = 8, 4
    bubble = label.get_rect(center=(cx, cy - 12))
    bubble.inflate_ip(pad_x * 2, pad_y * 2)
    pygame.draw.rect(surface, (255, 243, 205), bubble, border_radius=10)
    pygame.draw.rect(surface, (245, 165, 36), bubble, width=2, border_radius=10)
    surface.blit(label, label.get_rect(center=bubble.center))
    for offset in (-18, 18):
        pygame.draw.arc(
            surface,
            (245, 165, 36),
            (cx + offset - 10, cy - 28, 20, 16),
            0.2,
            2.8,
            2,
        )
