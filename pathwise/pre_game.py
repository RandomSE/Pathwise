"""Pre-game menu and round transition screens (Arcade)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import arcade

from .arcade_loop import pump_frame
from .geom import Rect
from map_generation.difficulty import DifficultyProfile
from .menu_layout import CandidateLayout, RecruiterLayout, layout_candidate, layout_recruiter
from .session_seed import (
    MAP_SEED_MOD,
    SeedInputState,
    classify_seed_input,
    decode_recruiter_seed,
    encode_recruiter_seed,
    parse_seed_value,
)

MENU_BG = (245, 248, 252)
MENU_CARD = (255, 255, 255)
MENU_ACCENT = (61, 139, 253)
MENU_TEXT = (22, 28, 36)
MENU_MUTED = (95, 110, 130)
MENU_BORDER = (210, 220, 235)
MENU_ERROR = (220, 53, 69)

MIN_ROUNDS = 1
MAX_ROUNDS = 5
DEFAULT_ROUNDS = 1
MAX_SEED_DIGITS = 10

ROUND_CONTROLS_HINT = (
    "Move: Arrow keys or WASD\n"
    "Sprint: Shift - toggle 2× speed (risky on roads & crosswalks; \n stops when you enter road)"
)
ROUND_START_PROMPT = "Click or press any key to go"

DIFFICULTY_PRESETS = [
    ("easy", "Easy", "Relaxed traffic · forgiving timing"),
    ("normal", "Normal", "Balanced challenge"),
    ("hard", "Hard", "Dense traffic · tight lights"),
]

INVALID_SEED_MESSAGE = "That is an invalid seed"
STALE_SEED_MESSAGE = "Settings changed — regenerate seed"
COPY_FEEDBACK_SECONDS = 1.5
COPY_FEEDBACK_MESSAGE = "Copied!"


@dataclass
class SessionConfig:
    preset: str
    num_rounds: int = DEFAULT_ROUNDS
    seed: int | None = None


def _parse_seed_text(text: str) -> int | None:
    return parse_seed_value(text)


def candidate_play_button_label(seed_state: SeedInputState) -> str:
    if seed_state == "valid":
        return "Play set seed"
    return "Play random seed"


def candidate_play_disabled(seed_state: SeedInputState) -> bool:
    return seed_state == "invalid"


def build_candidate_session_config(seed_text: str) -> SessionConfig:
    decoded = decode_recruiter_seed(seed_text)
    if decoded is not None:
        return SessionConfig(
            preset=decoded.preset,
            num_rounds=decoded.num_rounds,
            seed=decoded.map_seed,
        )
    state = classify_seed_input(seed_text)
    seed = parse_seed_value(seed_text) if state == "valid" else None
    return SessionConfig(preset="normal", num_rounds=1, seed=seed)


def build_recruiter_session_config(
    generated_seed_text: str,
    *,
    preset: str,
    num_rounds: int,
) -> SessionConfig:
    decoded = decode_recruiter_seed(generated_seed_text)
    if decoded is None:
        raise ValueError("generate a recruiter seed before starting a session")
    return SessionConfig(
        preset=decoded.preset,
        num_rounds=decoded.num_rounds,
        seed=decoded.map_seed,
    )


def normalize_pasted_seed(text: str) -> str:
    return "".join(str(text).split())


def recruiter_copy_enabled(generated_seed_text: str) -> bool:
    return bool(str(generated_seed_text).strip())


def recruiter_settings_fingerprint(preset: str, num_rounds: int) -> str:
    return f"{preset}:{num_rounds}"


def recruiter_seed_stale(
    generated_seed_text: str,
    *,
    current_fingerprint: str,
    generated_fingerprint: str,
) -> bool:
    if not recruiter_copy_enabled(generated_seed_text):
        return False
    return current_fingerprint != generated_fingerprint


def _arcade_y(window: arcade.Window, top_offset: int) -> int:
    """Convert a y-down offset from the window top to Arcade's bottom-origin y."""
    return window.height - top_offset


def _screen_y(window: arcade.Window, rect: Rect) -> int:
    return window.height - rect.centery


def _mouse_screen_pos(window: arcade.Window, x: float, y: float) -> tuple[int, int]:
    return int(x), int(window.height - y)


class _MenuView(arcade.View):
    def __init__(self, *, on_complete: Callable | None = None) -> None:
        super().__init__()
        self._done = False
        self._result = None
        self._on_complete = on_complete

    def finish(self, value):
        self._result = value
        self._done = True
        if self._on_complete is not None:
            self._on_complete(value)

    def _draw_button(
        self,
        rect: Rect,
        label: str,
        font_size: int,
        *,
        selected: bool = False,
        primary: bool = False,
        disabled: bool = False,
        border: tuple[int, int, int] | None = None,
    ) -> None:
        h = self.window.height
        left, bottom, w, bh = rect.left, h - rect.bottom, rect.width, rect.height
        if disabled:
            fill, text_color, border_color = (235, 238, 242), MENU_MUTED, MENU_BORDER
        elif primary:
            fill, text_color, border_color = MENU_ACCENT, (255, 255, 255), MENU_ACCENT
        elif selected:
            fill, text_color, border_color = (230, 242, 255), MENU_ACCENT, MENU_ACCENT
        else:
            fill, text_color, border_color = MENU_CARD, MENU_TEXT, border or MENU_BORDER
        arcade.draw_lbwh_rectangle_filled(left, bottom, w, bh, fill)
        arcade.draw_lbwh_rectangle_outline(left, bottom, w, bh, border_color, 2)
        if label:
            arcade.Text(
                label,
                rect.centerx,
                _screen_y(self.window, rect),
                text_color,
                font_size,
                anchor_x="center",
                anchor_y="center",
            ).draw()

    def _draw_seed_field(
        self,
        rect: Rect,
        seed_text: str,
        *,
        editing: bool,
        placeholder: str = "random",
    ) -> None:
        field_border = MENU_ACCENT if editing else MENU_BORDER
        self._draw_button(rect, "", 18, border=field_border)
        if seed_text:
            seed_label = seed_text
            seed_color = MENU_TEXT
        else:
            seed_label = placeholder
            seed_color = MENU_MUTED
        arcade.Text(
            seed_label,
            rect.centerx,
            _screen_y(self.window, rect),
            seed_color,
            22,
            anchor_x="center",
            anchor_y="center",
        ).draw()

    def _seed_field_hit(self, x: float, y: float, rect: Rect) -> bool:
        return rect.collidepoint(_mouse_screen_pos(self.window, x, y))

    def _apply_seed_paste(self, pasted: str) -> None:
        self.seed_text = normalize_pasted_seed(pasted)
        self.seed_editing = True

    def _paste_seed_from_clipboard(self) -> None:
        try:
            pasted = self.window.get_clipboard_text() or ""
        except Exception:
            pasted = ""
        self._apply_seed_paste(pasted)

    def _copy_text_to_clipboard(self, text: str) -> None:
        try:
            self.window.set_clipboard_text(text)
        except Exception:
            pass

    def _draw_preset_option(
        self,
        rect: Rect,
        label: str,
        desc: str,
        *,
        selected: bool,
    ) -> None:
        self._draw_button(rect, "", 20, selected=selected)
        center_y = _screen_y(self.window, rect)
        arcade.Text(
            label,
            rect.centerx,
            center_y + 8,
            MENU_ACCENT if selected else MENU_TEXT,
            20,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            desc,
            rect.centerx,
            center_y - 10,
            MENU_MUTED,
            12,
            anchor_x="center",
            anchor_y="center",
        ).draw()


class CandidateHomeView(_MenuView):
    def __init__(
        self,
        *,
        seed_text: str = "",
        on_complete: Callable[[SessionConfig | None], None] | None = None,
        on_configure: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(on_complete=on_complete)
        self.seed_text = seed_text
        self._on_configure = on_configure
        self.seed_editing = False
        self._layout_state: CandidateLayout | None = None
        self.seed_field_rect = Rect(0, 0, 0, 0)
        self.paste_rect = Rect(0, 0, 0, 0)
        self.play_rect = Rect(0, 0, 0, 0)
        self.configure_rect = Rect(0, 0, 0, 0)

    @property
    def seed_state(self) -> SeedInputState:
        return classify_seed_input(self.seed_text)

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _layout(self) -> None:
        layout = layout_candidate(self.window.width, self.window.height)
        self._layout_state = layout
        self.seed_field_rect = layout.seed_field_rect
        self.paste_rect = layout.paste_rect
        self.play_rect = layout.play_rect
        self.configure_rect = layout.configure_rect

    def _try_play(self) -> None:
        if candidate_play_disabled(self.seed_state):
            return
        self.finish(build_candidate_session_config(self.seed_text))

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            if self.seed_editing:
                self.seed_editing = False
            else:
                self.finish(None)
            return True
        if self.seed_editing:
            if symbol == arcade.key.BACKSPACE:
                self.seed_text = self.seed_text[:-1]
            elif symbol in (arcade.key.ENTER, arcade.key.RETURN):
                self.seed_editing = False
            elif symbol == arcade.key.V and modifiers & arcade.key.MOD_CTRL:
                self._paste_seed_from_clipboard()
            return True
        if symbol == arcade.key.V and modifiers & arcade.key.MOD_CTRL:
            self._paste_seed_from_clipboard()
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN, arcade.key.SPACE):
            self._try_play()
        return True

    def on_text(self, text: str) -> bool | None:
        if not self.seed_editing or not text:
            return True
        if len(text) > 1:
            self._apply_seed_paste(text)
        elif not text.isspace():
            self.seed_text += text
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        self.seed_editing = self._seed_field_hit(x, y, self.seed_field_rect)
        if self.paste_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            self._paste_seed_from_clipboard()
        if self.play_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            self._try_play()
        if self.configure_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            if self._on_configure is not None:
                self._on_configure(self.seed_text)
        return True

    def on_draw(self) -> None:
        self.clear()
        layout = self._layout_state or layout_candidate(self.window.width, self.window.height)
        cx = self.window.width // 2
        arcade.Text(
            "Pathwise",
            cx,
            _arcade_y(self.window, layout.title_top),
            MENU_TEXT,
            48,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Enter a recruiter seed or play a random map",
            cx,
            _arcade_y(self.window, layout.subtitle_top),
            MENU_MUTED,
            22,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        if self.seed_state == "invalid":
            arcade.Text(
                INVALID_SEED_MESSAGE,
                cx,
                _arcade_y(self.window, layout.error_label_top),
                MENU_ERROR,
                18,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        arcade.Text(
            "Map seed (optional)",
            cx,
            _arcade_y(self.window, layout.seed_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(self.seed_field_rect, self.seed_text, editing=self.seed_editing)
        self._draw_button(self.paste_rect, "Paste", 18)
        play_disabled = candidate_play_disabled(self.seed_state)
        self._draw_button(
            self.play_rect,
            candidate_play_button_label(self.seed_state),
            22,
            primary=not play_disabled,
            disabled=play_disabled,
        )
        self._draw_button(self.configure_rect, "Configure seed", 20)
        arcade.Text(
            "Esc to quit",
            cx,
            18,
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()


class RecruiterConfigView(_MenuView):
    def __init__(
        self,
        *,
        generated_seed_text: str = "",
        on_back: Callable[[str], None] | None = None,
        on_start: Callable[[SessionConfig], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__()
        self.selected_preset = "normal"
        self.num_rounds = DEFAULT_ROUNDS
        self.generated_seed_text = generated_seed_text
        self._generated_settings_fingerprint = ""
        decoded = decode_recruiter_seed(generated_seed_text)
        if decoded is not None:
            self._generated_settings_fingerprint = recruiter_settings_fingerprint(
                decoded.preset,
                decoded.num_rounds,
            )
        self._copy_feedback_until = 0.0
        self._rng = rng or random.Random()
        self._on_back = on_back
        self._on_start = on_start
        self._layout_state: RecruiterLayout | None = None
        self.minus_rect = Rect(0, 0, 0, 0)
        self.plus_rect = Rect(0, 0, 0, 0)
        self.seed_display_rect = Rect(0, 0, 0, 0)
        self.copy_rect = Rect(0, 0, 0, 0)
        self.generate_rect = Rect(0, 0, 0, 0)
        self.start_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)
        self.preset_rects: dict[str, Rect] = {}

    @property
    def seed_stale(self) -> bool:
        return recruiter_seed_stale(
            self.generated_seed_text,
            current_fingerprint=recruiter_settings_fingerprint(self.selected_preset, self.num_rounds),
            generated_fingerprint=self._generated_settings_fingerprint,
        )

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _layout(self) -> None:
        layout = layout_recruiter(
            self.window.width,
            self.window.height,
            num_rounds=self.num_rounds,
            show_stale_hint=self.seed_stale,
        )
        self._layout_state = layout
        self.minus_rect = layout.minus_rect
        self.plus_rect = layout.plus_rect
        self.preset_rects = layout.preset_rects
        self.seed_display_rect = layout.seed_display_rect
        self.copy_rect = layout.copy_rect
        self.generate_rect = layout.generate_rect
        self.start_rect = layout.start_rect
        self.back_rect = layout.back_rect

    def _generate_seed(self) -> None:
        map_seed = self._rng.randint(0, MAP_SEED_MOD - 1)
        self.generated_seed_text = encode_recruiter_seed(
            map_seed,
            self.selected_preset,
            self.num_rounds,
        )
        self._generated_settings_fingerprint = recruiter_settings_fingerprint(
            self.selected_preset,
            self.num_rounds,
        )
        self._layout()

    def _try_start(self) -> None:
        if self._on_start is None:
            return
        config = build_recruiter_session_config(
            self.generated_seed_text,
            preset=self.selected_preset,
            num_rounds=self.num_rounds,
        )
        self._on_start(config)

    def _go_back(self) -> None:
        if self._on_back is not None:
            self._on_back(self.generated_seed_text)

    def _copy_generated_seed(self) -> None:
        if not recruiter_copy_enabled(self.generated_seed_text):
            return
        self._copy_text_to_clipboard(self.generated_seed_text)
        self._copy_feedback_until = time.monotonic() + COPY_FEEDBACK_SECONDS

    def on_update(self, delta_time: float) -> None:
        if self._copy_feedback_until and time.monotonic() >= self._copy_feedback_until:
            self._copy_feedback_until = 0.0

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            self._go_back()
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN, arcade.key.SPACE):
            if self.generated_seed_text:
                self._try_start()
            else:
                self._generate_seed()
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        pos = _mouse_screen_pos(self.window, x, y)
        for preset_id, rect in self.preset_rects.items():
            if rect.collidepoint(pos):
                self.selected_preset = preset_id
                self._layout()
        if self.minus_rect.collidepoint(pos):
            self.num_rounds = max(MIN_ROUNDS, self.num_rounds - 1)
            self._layout()
        if self.plus_rect.collidepoint(pos):
            self.num_rounds = min(MAX_ROUNDS, self.num_rounds + 1)
            self._layout()
        if self.generate_rect.collidepoint(pos):
            self._generate_seed()
        if self.copy_rect.collidepoint(pos):
            self._copy_generated_seed()
        if self.start_rect.collidepoint(pos):
            self._try_start()
        if self.back_rect.collidepoint(pos):
            self._go_back()
        return True

    def on_draw(self) -> None:
        self.clear()
        layout = self._layout_state or layout_recruiter(
            self.window.width,
            self.window.height,
            num_rounds=self.num_rounds,
            show_stale_hint=self.seed_stale,
        )
        cx = self.window.width // 2
        arcade.Text(
            "Pathwise",
            cx,
            _arcade_y(self.window, layout.title_top),
            MENU_TEXT,
            48,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Recruiter session configuration",
            cx,
            _arcade_y(self.window, layout.subtitle_top),
            MENU_MUTED,
            24,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Number of rounds",
            cx,
            _arcade_y(self.window, layout.rounds_label_top),
            MENU_MUTED,
            18,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(self.minus_rect, "-", 24)
        arcade.Text(
            str(self.num_rounds),
            cx,
            _arcade_y(self.window, layout.rounds_value_top),
            MENU_TEXT,
            24,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(self.plus_rect, "+", 24)
        if layout.rounds_hint_top is not None:
            arcade.Text(
                "One seed — each round uses a derived map from that seed",
                cx,
                _arcade_y(self.window, layout.rounds_hint_top),
                MENU_MUTED,
                14,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        arcade.Text(
            "Starting difficulty",
            cx,
            _arcade_y(self.window, layout.difficulty_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        for preset_id, label, desc in DIFFICULTY_PRESETS:
            rect = layout.preset_rects[preset_id]
            self._draw_preset_option(rect, label, desc, selected=(preset_id == self.selected_preset))
        arcade.Text(
            "Special modifiers",
            cx,
            _arcade_y(self.window, layout.modifiers_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Coming soon",
            cx,
            _arcade_y(self.window, layout.modifiers_hint_top),
            MENU_MUTED,
            18,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        if self.seed_stale:
            arcade.Text(
                STALE_SEED_MESSAGE,
                cx,
                _arcade_y(self.window, layout.stale_hint_top),
                MENU_ERROR,
                16,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        arcade.Text(
            "Generated candidate seed",
            cx,
            _arcade_y(self.window, layout.generated_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        if self.generated_seed_text:
            self._draw_seed_field(self.seed_display_rect, self.generated_seed_text, editing=False)
        else:
            self._draw_seed_field(
                self.seed_display_rect,
                "",
                editing=False,
                placeholder="— generate to create —",
            )
        copy_disabled = not recruiter_copy_enabled(self.generated_seed_text)
        self._draw_button(self.copy_rect, "Copy", 18, disabled=copy_disabled)
        self._draw_button(self.generate_rect, "Generate seed", 20)
        start_disabled = not bool(self.generated_seed_text)
        self._draw_button(
            self.start_rect,
            "Start session",
            22,
            primary=not start_disabled,
            disabled=start_disabled,
        )
        self._draw_button(self.back_rect, "Back to play area", 20)
        if self._copy_feedback_until and time.monotonic() < self._copy_feedback_until:
            arcade.Text(
                COPY_FEEDBACK_MESSAGE,
                cx,
                _arcade_y(self.window, layout.copy_feedback_top),
                MENU_ACCENT,
                16,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        arcade.Text(
            "Generate encodes rounds and difficulty · Copy shares seed with candidates",
            cx,
            18,
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()


# Backward-compatible alias for tests and external callers.
PreGameMenuView = RecruiterConfigView


class MessageView(_MenuView):
    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        accent: str = "",
        details: str = "",
        auto_advance_s: float | None = None,
        on_complete: Callable | None = None,
    ) -> None:
        super().__init__(on_complete=on_complete)
        self.title = title
        self.subtitle = subtitle
        self.accent = accent
        self.details = details
        self.auto_advance_s = auto_advance_s
        self._elapsed = 0.0

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)

    def on_update(self, delta_time: float) -> None:
        if self.auto_advance_s is None:
            return
        self._elapsed += delta_time
        if self._elapsed >= self.auto_advance_s:
            self.finish(True)

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        self.finish(True)
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        self.finish(True)
        return True

    def on_draw(self) -> None:
        self.clear()
        cx = self.window.width // 2
        h = self.window.height
        arcade.Text(
            self.title,
            cx,
            h * 0.55,
            MENU_TEXT,
            40,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        if self.subtitle:
            arcade.Text(
                self.subtitle,
                cx,
                h * 0.45,
                MENU_MUTED,
                22,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        if self.accent:
            arcade.Text(
                self.accent,
                cx,
                h * 0.38,
                MENU_ACCENT,
                24,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        if self.details:
            arcade.Text(
                self.details,
                cx,
                h * 0.28,
                MENU_MUTED,
                16,
                anchor_x="center",
                anchor_y="center",
                multiline=True,
                width=min(560, self.window.width - 80),
            ).draw()


def run_pre_game_menu(window: arcade.Window) -> SessionConfig | None:
    view = CandidateHomeView()
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
    return view._result


def run_round_intro(
    window: arcade.Window,
    round_index: int,
    total_rounds: int,
    profile: DifficultyProfile,
) -> bool:
    hint = (
        f"~{profile.min_crossings}-{profile.max_crossings} roads · "
        f"{profile.target_play_time_s}s · denser traffic"
    )
    if round_index > 1:
        hint += f" (+{int(profile.round_escalation * 100)}% vs round 1)"
    view = MessageView(
        title=f"Round {round_index} of {total_rounds}",
        subtitle=hint,
        accent=ROUND_START_PROMPT,
        details=ROUND_CONTROLS_HINT,
    )
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
    return bool(view._result)


def run_between_rounds(
    window: arcade.Window,
    round_index: int,
    total_rounds: int,
    outcome: str,
) -> bool:
    labels = {"success": "Goal reached", "collision": "Collision", "timeout": "Time expired"}
    label = labels.get(outcome, outcome)
    sub = "Next round will be harder" if round_index < total_rounds else "Session finishing…"
    view = MessageView(
        title=f"Round {round_index} complete — {label}",
        subtitle=sub,
        accent="Click or press any key to continue",
    )
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
    return bool(view._result)


def run_session_complete(
    window: arcade.Window,
    outcomes: list[str],
    total_rounds: int,
    session_seed: int | None = None,
) -> None:
    summary = " · ".join(f"R{i + 1}: {o}" for i, o in enumerate(outcomes))
    subtitle = summary
    if session_seed is not None:
        subtitle += f"\nSession seed: {session_seed}"
    view = MessageView(
        title=f"All {total_rounds} rounds complete",
        subtitle=subtitle,
        accent="Open logs_dashboard.html for per-round replays",
    )
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
