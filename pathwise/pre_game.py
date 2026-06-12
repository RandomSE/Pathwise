"""Pre-game menu and round transition screens (Arcade)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import arcade

from .arcade_loop import pump_frame
from .geom import Rect
from map_generation.difficulty import DifficultyProfile
from .session_seed import parse_seed_value, pathwise_seed_from_env

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
    seed: int | None = None


def _parse_seed_text(text: str) -> int | None:
    return parse_seed_value(text)


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


class PreGameMenuView(_MenuView):
    def __init__(self, *, on_complete: Callable[[SessionConfig | None], None] | None = None) -> None:
        super().__init__(on_complete=on_complete)
        self.selected_preset = "normal"
        self.num_rounds = DEFAULT_ROUNDS
        env_seed = pathwise_seed_from_env()
        self.seed_text = str(env_seed) if env_seed is not None else ""
        self.seed_editing = False
        self.env_seed = env_seed
        self.minus_rect = Rect(0, 0, 0, 0)
        self.plus_rect = Rect(0, 0, 0, 0)
        self.seed_field_rect = Rect(0, 0, 0, 0)
        self.start_rect = Rect(0, 0, 0, 0)
        self.preset_rects: dict[str, Rect] = {}

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def _layout(self) -> None:
        cx = self.window.width // 2
        self.minus_rect = Rect(cx - 120, 128, 44, 40)
        self.plus_rect = Rect(cx + 76, 128, 44, 40)
        self.seed_field_rect = Rect(cx - 160, 198, 320, 44)
        self.start_rect = Rect(cx - 120, 500, 240, 52)
        self.preset_rects = {}
        y = 300
        for preset_id, _label, _desc in DIFFICULTY_PRESETS:
            self.preset_rects[preset_id] = Rect(cx - 200, y, 400, 44)
            y += 54

    def _finish_config(self) -> SessionConfig:
        return SessionConfig(
            preset=self.selected_preset,
            num_rounds=self.num_rounds,
            seed=_parse_seed_text(self.seed_text),
        )

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
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN, arcade.key.SPACE):
            self.finish(self._finish_config())
        return True

    def on_text(self, text: str) -> bool | None:
        if self.seed_editing and text.isdigit() and len(self.seed_text) < MAX_SEED_DIGITS:
            self.seed_text += text
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        sy = self.window.height - y
        pos = (int(x), int(sy))
        self.seed_editing = self.seed_field_rect.collidepoint(pos)
        for preset_id, rect in self.preset_rects.items():
            if rect.collidepoint(pos):
                self.selected_preset = preset_id
                self.seed_editing = False
        if self.minus_rect.collidepoint(pos):
            self.num_rounds = max(MIN_ROUNDS, self.num_rounds - 1)
            self.seed_editing = False
        if self.plus_rect.collidepoint(pos):
            self.num_rounds = min(MAX_ROUNDS, self.num_rounds + 1)
            self.seed_editing = False
        if self.start_rect.collidepoint(pos):
            self.finish(self._finish_config())
        return True

    def on_draw(self) -> None:
        self.clear()
        cx = self.window.width // 2
        h = self.window.height
        arcade.Text("Pathwise", cx, h - 52, MENU_TEXT, 48, anchor_x="center", anchor_y="center").draw()
        arcade.Text(
            "Configure your session, then start",
            cx,
            h - 92,
            MENU_MUTED,
            24,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Number of rounds",
            cx,
            h - 108,
            MENU_MUTED,
            18,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(self.minus_rect, "-", 24)
        arcade.Text(
            str(self.num_rounds),
            cx,
            h - 148,
            MENU_TEXT,
            24,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(self.plus_rect, "+", 24)
        if self.num_rounds > 1:
            arcade.Text(
                "One seed — each round uses a derived map from that seed",
                cx,
                h - 172,
                MENU_MUTED,
                16,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        arcade.Text(
            "Map seed (optional)",
            cx,
            h - 188,
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        field_border = MENU_ACCENT if self.seed_editing else MENU_BORDER
        self._draw_button(self.seed_field_rect, "", 18, border=field_border)
        if self.seed_text:
            seed_label = self.seed_text + ("|" if self.seed_editing else "")
        else:
            seed_label = "random" + ("|" if self.seed_editing else "")
        seed_color = MENU_TEXT if self.seed_text else MENU_MUTED
        arcade.Text(
            seed_label,
            self.seed_field_rect.centerx,
            h - self.seed_field_rect.centery,
            seed_color,
            22,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        hint = (
            "PATHWISE_SEED env active — same map for every candidate"
            if self.env_seed is not None
            else "Digits only · empty = random seed (shown after game)"
        )
        arcade.Text(hint, cx, h - 258, MENU_MUTED, 16, anchor_x="center", anchor_y="center").draw()
        arcade.Text(
            "Starting difficulty",
            cx,
            h - 282,
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        for preset_id, label, desc in DIFFICULTY_PRESETS:
            rect = self.preset_rects[preset_id]
            self._draw_button(rect, label, 22, selected=(preset_id == self.selected_preset))
            arcade.Text(
                desc,
                rect.right + 12,
                h - rect.centery,
                MENU_MUTED,
                16,
                anchor_x="left",
                anchor_y="center",
            ).draw()
        self._draw_button(self.start_rect, "Start game", 24, primary=True)
        arcade.Text(
            "Enter or Space to start · Esc to quit",
            cx,
            h - 565,
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()

    def _draw_button(
        self,
        rect: Rect,
        label: str,
        font_size: int,
        *,
        selected: bool = False,
        primary: bool = False,
        border: tuple[int, int, int] | None = None,
    ) -> None:
        h = self.window.height
        left, bottom, w, bh = rect.left, h - rect.bottom, rect.width, rect.height
        if primary:
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
                h - rect.centery,
                text_color,
                font_size,
                anchor_x="center",
                anchor_y="center",
            ).draw()


class MessageView(_MenuView):
    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        accent: str = "",
        auto_advance_s: float | None = None,
        on_complete: Callable | None = None,
    ) -> None:
        super().__init__(on_complete=on_complete)
        self.title = title
        self.subtitle = subtitle
        self.accent = accent
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


def run_pre_game_menu(window: arcade.Window) -> SessionConfig | None:
    view = PreGameMenuView()
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
        accent="Go!",
        auto_advance_s=2.2,
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
