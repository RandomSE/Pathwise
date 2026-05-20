"""Pre-game menu and round transition screens."""

from dataclasses import dataclass

import pygame

from map_generation.difficulty import DifficultyProfile

MENU_BG = (245, 248, 252)
MENU_CARD = (255, 255, 255)
MENU_ACCENT = (61, 139, 253)
MENU_TEXT = (22, 28, 36)
MENU_MUTED = (95, 110, 130)
MENU_BORDER = (210, 220, 235)

MIN_ROUNDS = 1
MAX_ROUNDS = 5
DEFAULT_ROUNDS = 1
MAX_SEED_DIGITS = 10

DIFFICULTY_PRESETS = [
    ("easy", "Easy", "Relaxed traffic · forgiving timing"),
    ("normal", "Normal", "Balanced challenge"),
    ("hard", "Hard", "Dense traffic · tight lights"),
]


@dataclass
class SessionConfig:
    preset: str
    num_rounds: int = DEFAULT_ROUNDS
    seed: int | None = None  # None => random session seed (logged); same seed spans all rounds


def _parse_seed_text(text: str) -> int | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if not cleaned.isdigit():
        return None
    return int(cleaned) % (2**31)


def _blit_centered(surface, font, text, color, center):
    rendered = font.render(text, True, color)
    surface.blit(rendered, rendered.get_rect(center=center))


def _draw_button(surface, rect, label, font, selected=False, primary=False):
    if primary:
        fill, text_color, border = MENU_ACCENT, (255, 255, 255), MENU_ACCENT
    elif selected:
        fill, text_color, border = (230, 242, 255), MENU_ACCENT, MENU_ACCENT
    else:
        fill, text_color, border = MENU_CARD, MENU_TEXT, MENU_BORDER
    pygame.draw.rect(surface, fill, rect, border_radius=10)
    pygame.draw.rect(surface, border, rect, width=2, border_radius=10)
    _blit_centered(surface, font, label, text_color, rect.center)


def _width_center(screen):
    return screen.get_width() // 2


def run_pre_game_menu(screen, clock, title_font, body_font, small_font) -> SessionConfig | None:
    selected_preset = "normal"
    num_rounds = DEFAULT_ROUNDS
    seed_text = ""
    seed_editing = False
    minus_rect = pygame.Rect(0, 0, 0, 0)
    plus_rect = pygame.Rect(0, 0, 0, 0)
    seed_field_rect = pygame.Rect(0, 0, 0, 0)
    start_rect = pygame.Rect(_width_center(screen) - 120, 500, 240, 52)
    preset_rects = {}
    y = 300
    for preset_id, label, _desc in DIFFICULTY_PRESETS:
        preset_rects[preset_id] = pygame.Rect(_width_center(screen) - 200, y, 400, 44)
        y += 54

    def finish_config():
        return SessionConfig(
            preset=selected_preset,
            num_rounds=num_rounds,
            seed=_parse_seed_text(seed_text),
        )

    while True:
        cx = _width_center(screen)
        minus_rect = pygame.Rect(cx - 120, 128, 44, 40)
        plus_rect = pygame.Rect(cx + 76, 128, 44, 40)
        seed_field_rect = pygame.Rect(cx - 160, 198, 320, 44)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if seed_editing:
                        seed_editing = False
                    else:
                        return None
                elif seed_editing:
                    if event.key == pygame.K_BACKSPACE:
                        seed_text = seed_text[:-1]
                    elif event.key == pygame.K_RETURN:
                        seed_editing = False
                    elif event.unicode.isdigit() and len(seed_text) < MAX_SEED_DIGITS:
                        seed_text += event.unicode
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return finish_config()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                pos = event.pos
                seed_editing = seed_field_rect.collidepoint(pos)
                for preset_id, rect in preset_rects.items():
                    if rect.collidepoint(pos):
                        selected_preset = preset_id
                        seed_editing = False
                if minus_rect.collidepoint(pos):
                    num_rounds = max(MIN_ROUNDS, num_rounds - 1)
                    seed_editing = False
                if plus_rect.collidepoint(pos):
                    num_rounds = min(MAX_ROUNDS, num_rounds + 1)
                    seed_editing = False
                if start_rect.collidepoint(pos):
                    return finish_config()

        screen.fill(MENU_BG)
        _blit_centered(screen, title_font, "Pathwise", MENU_TEXT, (cx, 52))
        _blit_centered(
            screen, body_font, "Configure your session, then start", MENU_MUTED, (cx, 92)
        )
        _blit_centered(screen, small_font, "Number of rounds", MENU_MUTED, (cx, 108))
        _draw_button(screen, minus_rect, "-", body_font)
        _blit_centered(screen, body_font, str(num_rounds), MENU_TEXT, (cx, 148))
        _draw_button(screen, plus_rect, "+", body_font)
        if num_rounds > 1:
            _blit_centered(
                screen,
                small_font,
                "One seed — each round uses a derived map from that seed",
                MENU_MUTED,
                (cx, 172),
            )
        _blit_centered(screen, small_font, "Map seed (optional)", MENU_MUTED, (cx, 188))
        field_border = MENU_ACCENT if seed_editing else MENU_BORDER
        pygame.draw.rect(screen, MENU_CARD, seed_field_rect, border_radius=10)
        pygame.draw.rect(screen, field_border, seed_field_rect, width=2, border_radius=10)
        if seed_text:
            seed_label = seed_text + ("|" if seed_editing else "")
        else:
            seed_label = "random" + ("|" if seed_editing else "")
        seed_color = MENU_TEXT if seed_text else MENU_MUTED
        _blit_centered(screen, body_font, seed_label, seed_color, seed_field_rect.center)
        _blit_centered(
            screen,
            small_font,
            "Digits only · empty = random seed (shown after game)",
            MENU_MUTED,
            (cx, 258),
        )
        _blit_centered(screen, small_font, "Starting difficulty", MENU_MUTED, (cx, 282))
        for preset_id, label, desc in DIFFICULTY_PRESETS:
            rect = preset_rects[preset_id]
            _draw_button(screen, rect, label, body_font, selected=(preset_id == selected_preset))
            d = small_font.render(desc, True, MENU_MUTED)
            screen.blit(d, d.get_rect(midleft=(rect.right + 12, rect.centery)))

        _draw_button(screen, start_rect, "Start game", body_font, primary=True)
        _blit_centered(screen, small_font, "Enter or Space to start · Esc to quit", MENU_MUTED, (cx, 565))

        pygame.display.flip()
        clock.tick(60)


def run_round_intro(screen, clock, title_font, body_font, round_index: int, total_rounds: int, profile: DifficultyProfile):
    wait_ms = 2200
    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < wait_ms:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                return True

        screen.fill(MENU_BG)
        cx = _width_center(screen)
        _blit_centered(
            screen, title_font, f"Round {round_index} of {total_rounds}", MENU_TEXT, (cx, 175)
        )
        hint = (
            f"~{profile.min_crossings}-{profile.max_crossings} roads · "
            f"{profile.target_play_time_s}s · denser traffic"
        )
        if round_index > 1:
            hint += f" (+{int(profile.round_escalation * 100)}% vs round 1)"
        _blit_centered(screen, body_font, hint, MENU_MUTED, (cx, 235))
        _blit_centered(screen, body_font, "Go!", MENU_ACCENT, (cx, 295))
        pygame.display.flip()
        clock.tick(60)
    return True


def run_between_rounds(screen, clock, title_font, body_font, round_index: int, total_rounds: int, outcome: str):
    labels = {"success": "Goal reached", "collision": "Collision", "timeout": "Time expired"}
    label = labels.get(outcome, outcome)
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                return True

        screen.fill(MENU_BG)
        cx = _width_center(screen)
        _blit_centered(
            screen,
            title_font,
            f"Round {round_index} complete — {label}",
            MENU_TEXT,
            (cx, 220),
        )
        if round_index < total_rounds:
            sub = "Next round will be harder"
        else:
            sub = "Session finishing…"
        _blit_centered(screen, body_font, sub, MENU_MUTED, (cx, 280))
        _blit_centered(
            screen, body_font, "Click or press any key to continue", MENU_ACCENT, (cx, 340)
        )
        pygame.display.flip()
        clock.tick(60)


def run_session_complete(
    screen,
    clock,
    title_font,
    body_font,
    outcomes: list[str],
    total_rounds: int,
    session_seed: int | None = None,
):
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                return

        screen.fill(MENU_BG)
        cx = _width_center(screen)
        _blit_centered(
            screen, title_font, f"All {total_rounds} rounds complete", MENU_TEXT, (cx, 180)
        )
        summary = " · ".join(f"R{i + 1}: {o}" for i, o in enumerate(outcomes))
        _blit_centered(screen, body_font, summary, MENU_MUTED, (cx, 230))
        if session_seed is not None:
            _blit_centered(
                screen, body_font, f"Session seed: {session_seed}", MENU_TEXT, (cx, 270)
            )
        _blit_centered(
            screen,
            body_font,
            "Open logs_dashboard.html for per-round replays",
            MENU_ACCENT,
            (cx, 310),
        )
        pygame.display.flip()
        clock.tick(60)
