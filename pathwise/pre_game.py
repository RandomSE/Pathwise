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
from pathwise.modifiers.registry import (
    MODIFIER_CATALOG,
    available_modifier_ids,
    modifier_is_blocked,
)
from .session_seed import (
    MAP_SEED_MOD,
    MAP_SEED_MOD_V9,
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
MAX_SEED_DIGITS = 12

ROUND_CONTROLS_HINT = (
    "Move: Arrow keys or WASD\n"
    "Sprint: Shift - toggle 2× speed (risky on roads & crosswalks; \n stops when you enter road)"
)
ROUND_START_PROMPT = "Click or press any key to go"

ROUND_OUTCOME_LABELS = {
    "success": "Goal reached",
    "collision": "Collision",
    "timeout": "Time expired",
    "trip": "Tripped",
}


def round_outcome_label(outcome: str) -> str:
    return ROUND_OUTCOME_LABELS.get(outcome, outcome.replace("_", " ").title())

DIFFICULTY_PRESETS = [
    ("easy", "Easy", "Relaxed traffic · forgiving timing"),
    ("normal", "Normal", "Balanced challenge"),
    ("hard", "Hard", "Dense traffic · tight lights"),
]

INVALID_SEED_MESSAGE = "That is an invalid seed"
NAME_REQUIRED_MESSAGE = "Enter your name to play a set seed."
NAME_PLACEHOLDER = "your name"
MAX_NAME_LENGTH = 80
GENERATE_SEED_REGISTER_ATTEMPTS = 8
STALE_SEED_MESSAGE = "Settings changed; regenerate seed"
COPY_FEEDBACK_SECONDS = 1.5
COPY_FEEDBACK_MESSAGE = "Copied!"
CANDIDATE_HOME_SUBTITLE = (
    "No setup needed. Paste a seed if you have one, or play a random map."
)
CANDIDATE_HOME_FOOTER = "Candidates play here. Recruiters sign in separately."
RECRUITER_DOOR_LABEL = "Recruiter login"
RECRUITER_SEED_SHARE_HINT = (
    "Send this code to the candidate. They paste it on the play screen. "
    "A dashboard zip is emailed when SMTP is configured."
)
SMTP_OFF_HINT = (
    "Email is off until PATHWISE_SMTP_HOST, PATHWISE_SMTP_PASSWORD, and "
    "PATHWISE_SMTP_FROM are included in this build."
)

DISCLAIMER_TITLE = "Safety disclaimer"
DISCLAIMER_AGREE_LABEL = "I understand and agree"
DISCLAIMER_BODY = (
    "Pathwise is a fictional educational and assessment simulation only. "
    "It is not training for real traffic, and it is not advice about "
    "crossing roads or highways in the real world.\n\n"
    "Do not copy anything you see here in real life. Never walk into "
    "traffic, cross against signals, or enter highways or roadway lanes "
    "outside a controlled, lawful setting. Real roads and vehicles can "
    "cause serious injury or death.\n\n"
    "By continuing you confirm you understand this is a simulation and "
    "you will not treat Pathwise as guidance for real-world road "
    "behavior."
)
TRIP_NOTICE_TITLE = "You tripped"
TRIP_NOTICE_ACCENT = "Click or press any key to continue"


@dataclass
class SessionConfig:
    preset: str
    num_rounds: int = DEFAULT_ROUNDS
    seed: int | None = None
    modifiers: frozenset[str] = frozenset()
    # "candidate" conceals HUD / other modifiers under Hidden; "recruiter" sees all.
    audience: str = "candidate"
    candidate_label: str | None = None
    recruiter_seed_code: str | None = None


def _parse_seed_text(text: str) -> int | None:
    return parse_seed_value(text)


def candidate_play_button_label(seed_state: SeedInputState) -> str:
    if seed_state == "valid":
        return "Play set seed"
    return "Play random seed"


def candidate_name_field_visible(seed_text: str) -> bool:
    """Name is only asked once the seed field has content (typed or pasted)."""
    return classify_seed_input(seed_text) != "empty"


def candidate_play_disabled(
    seed_state: SeedInputState,
    *,
    name_text: str = "",
    recruiter_logged_in: bool = False,
) -> bool:
    if seed_state == "invalid":
        return True
    if seed_state == "valid" and not recruiter_logged_in and not str(name_text).strip():
        return True
    return False


def build_candidate_session_config(
    seed_text: str,
    *,
    candidate_label: str | None = None,
) -> SessionConfig:
    cleaned = "".join(str(seed_text).split())
    decoded = decode_recruiter_seed(cleaned)
    label = str(candidate_label).strip() if candidate_label is not None else None
    if label == "":
        label = None
    if decoded is not None:
        return SessionConfig(
            preset=decoded.preset,
            num_rounds=decoded.num_rounds,
            seed=decoded.map_seed,
            modifiers=decoded.modifiers,
            audience="candidate",
            candidate_label=label,
            recruiter_seed_code=cleaned,
        )
    state = classify_seed_input(seed_text)
    seed = parse_seed_value(seed_text) if state == "valid" else None
    return SessionConfig(
        preset="normal",
        num_rounds=1,
        seed=seed,
        audience="candidate",
        candidate_label=label,
        recruiter_seed_code=None,
    )


def build_recruiter_session_config(
    generated_seed_text: str,
    *,
    preset: str,
    num_rounds: int,
    candidate_label: str | None = None,
) -> SessionConfig:
    decoded = decode_recruiter_seed(generated_seed_text)
    if decoded is None:
        raise ValueError("generate a recruiter seed before starting a session")
    label = str(candidate_label).strip() if candidate_label is not None else None
    if label == "":
        label = None
    return SessionConfig(
        preset=decoded.preset,
        num_rounds=decoded.num_rounds,
        seed=decoded.map_seed,
        modifiers=decoded.modifiers,
        audience="recruiter",
        candidate_label=label,
        recruiter_seed_code=str(generated_seed_text).strip(),
    )


def modifier_detail_lines(
    modifiers: frozenset[str], *, audience: str = "candidate"
) -> list[tuple[str, str]]:
    from pathwise.modifiers import hidden

    visible = hidden.visible_modifiers(modifiers, audience=audience)
    lines: list[tuple[str, str]] = []
    if {"rainy_roads", "time_pressure"} <= visible:
        lines.append(
            (
                "Rain + Time pressure",
                (
                    "Together these start the timer at 20 seconds and make crossing "
                    "bonuses 75% larger."
                ),
            )
        )
    for entry in MODIFIER_CATALOG:
        if entry["id"] in visible:
            lines.append((entry["title"], entry["description"]))
    return lines


def modifier_explain_body(modifier_id: str, active_modifiers: frozenset[str]) -> str | None:
    """Body text for the recruiter modifier info panel."""
    meta = next((entry for entry in MODIFIER_CATALOG if entry["id"] == modifier_id), None)
    if meta is None:
        return None
    body = f"{meta['title']}\n\n{meta['description'].replace(chr(10), ' ')}"
    if (
        modifier_id in ("rainy_roads", "time_pressure")
        and {"rainy_roads", "time_pressure"} <= active_modifiers
    ):
        body += (
            "\n\nActive together now: timer starts at 20 seconds; crossing bonuses "
            "are 75% larger."
        )
    return body


POPUP_MODIFIER_TEXT_INSET = 48
POPUP_HEADER_TOP = 36
POPUP_HEADER_HEIGHT = 32
POPUP_HEADER_GAP = 20
POPUP_TITLE_DESC_GAP = 12
POPUP_ENTRY_GAP = 20
POPUP_TITLE_FONT = 20
POPUP_DESC_FONT = 14
POPUP_SCROLL_STEP = 28
POPUP_CARD_BOTTOM_PAD = 16


def _modifier_popup_text_width(card_width: int) -> int:
    return max(200, card_width - POPUP_MODIFIER_TEXT_INSET)


def wrap_text_words(
    text: str,
    *,
    width_px: int,
    font_size: int,
    char_width_factor: float = 0.62,
) -> str:
    """Wrap text on word boundaries. Never splits a word across lines.

    Pair with arcade.Text(multiline=True, width=multiline_text_width(...)).
    Arcade requires a non-zero width for multiline; use multiline_text_width so
    Arcade will not re-flow (and mid-word split) the pre-wrapped lines.
    """
    max_chars = max(8, int(width_px / max(0.1, font_size * char_width_factor)))
    paragraphs = str(text).split("\n")
    wrapped_paragraphs: list[str] = []
    for paragraph in paragraphs:
        raw = paragraph.strip()
        if not raw:
            wrapped_paragraphs.append("")
            continue
        words = raw.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if not current or len(candidate) <= max_chars:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        wrapped_paragraphs.append("\n".join(lines))
    return "\n".join(wrapped_paragraphs)


def multiline_text_width(content_width_px: int) -> int:
    """Non-zero Arcade multiline width that will not re-wrap pre-broken lines."""
    # Arcade forbids width=None when multiline=True. A huge width keeps our
    # explicit newlines as the only breaks (avoids mid-word reflow).
    return max(10_000, int(content_width_px) * 4, 1)


def modifier_desc_draw_x(card_left: int, card_width: int, *, text_width: int | None = None) -> int:
    """Left x for left-aligned popup descriptions.

    Arcade multiline Text left-aligns glyphs inside its width box. A huge
    ``multiline_text_width`` plus ``anchor_x='center'`` places that box far left
    of the card scissor, which hid descriptions while titles (no width) stayed
    visible. Draw left-aligned at the centered content block instead.
    """
    tw = (
        int(text_width)
        if text_width is not None
        else _modifier_popup_text_width(card_width)
    )
    return int(card_left) + max(0, (int(card_width) - tw) // 2)


def _estimated_wrapped_text_height(text: str, *, font_size: int, width_px: int) -> int:
    wrapped = wrap_text_words(text, width_px=width_px, font_size=font_size)
    total_lines = max(1, len(wrapped.split("\n")))
    # Arcade multiline line spacing is taller than font_size alone.
    return int(total_lines * font_size * 1.9)


def _safe_text_content_height(text: arcade.Text, *, fallback: int) -> int:
    try:
        height = int(text.content_height)
    except (RuntimeError, TypeError, ValueError):
        return fallback
    return height if height > 0 else fallback


def measure_modifier_popup_body_height(
    card_width: int,
    modifiers: frozenset[str],
    *,
    audience: str = "candidate",
) -> int:
    """Height of modifier entries only (below the fixed popup header)."""
    text_width = _modifier_popup_text_width(card_width)
    cursor = 0
    entries = modifier_detail_lines(modifiers, audience=audience)
    for index, (title, description) in enumerate(entries):
        cursor += _estimated_wrapped_text_height(title, font_size=POPUP_TITLE_FONT, width_px=text_width)
        cursor += POPUP_TITLE_DESC_GAP
        cursor += _estimated_wrapped_text_height(
            description,
            font_size=POPUP_DESC_FONT,
            width_px=text_width,
        )
        if index < len(entries) - 1:
            cursor += POPUP_ENTRY_GAP
    # Extra slack until the live draw pass syncs scroll from real Text metrics.
    return int(cursor * 1.2) + 96


def measure_modifier_popup_height(
    card_width: int,
    modifiers: frozenset[str],
    *,
    audience: str = "candidate",
) -> int:
    header = POPUP_HEADER_TOP + POPUP_HEADER_HEIGHT + POPUP_HEADER_GAP
    return (
        header
        + measure_modifier_popup_body_height(card_width, modifiers, audience=audience)
        + POPUP_CARD_BOTTOM_PAD
    )


def normalize_pasted_seed(text: str) -> str:
    return "".join(str(text).split())


def recruiter_copy_enabled(generated_seed_text: str) -> bool:
    return bool(str(generated_seed_text).strip())


def recruiter_settings_fingerprint(
    preset: str,
    num_rounds: int,
    modifiers: frozenset[str] | None = None,
) -> str:
    mods = ",".join(sorted(modifiers or ()))
    return f"{preset}:{num_rounds}:{mods}"


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
        normalized = normalize_pasted_seed(pasted)
        if not normalized:
            return
        if classify_seed_input(normalized) == "invalid":
            self.seed_text = normalized
            self.seed_editing = False
            self._layout()
            return
        self.seed_text = normalized
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
        name_text: str = "",
        on_complete: Callable[[SessionConfig | None], None] | None = None,
        on_configure: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(on_complete=on_complete)
        self.seed_text = seed_text
        self.name_text = name_text
        self._on_configure = on_configure
        self.seed_editing = False
        self.name_editing = False
        self._layout_state: CandidateLayout | None = None
        self.seed_field_rect = Rect(0, 0, 0, 0)
        self.name_field_rect = Rect(0, 0, 0, 0)
        self.paste_rect = Rect(0, 0, 0, 0)
        self.play_rect = Rect(0, 0, 0, 0)
        self.configure_rect = Rect(0, 0, 0, 0)

    @property
    def seed_state(self) -> SeedInputState:
        return classify_seed_input(self.seed_text)

    def _recruiter_logged_in(self) -> bool:
        from pathwise.recruiter_accounts import RecruiterRecord

        record = getattr(self.window, "_recruiter_record", None)
        if not isinstance(record, RecruiterRecord):
            return False
        method = getattr(self.window, "recruiter_session_active", None)
        if callable(method):
            try:
                return bool(method())
            except Exception:
                return False
        token = getattr(self.window, "_recruiter_session_token", None)
        return isinstance(token, str) and bool(token)

    def _candidate_label(self) -> str | None:
        from pathwise.recruiter_accounts import RecruiterRecord

        if self._recruiter_logged_in():
            record = getattr(self.window, "_recruiter_record", None)
            if isinstance(record, RecruiterRecord):
                return record.email
            return None
        stripped = str(self.name_text).strip()
        return stripped or None

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _layout(self) -> None:
        show_name = candidate_name_field_visible(self.seed_text)
        if not show_name:
            self.name_editing = False
        layout = layout_candidate(
            self.window.width,
            self.window.height,
            show_name=show_name,
        )
        self._layout_state = layout
        self.seed_field_rect = layout.seed_field_rect
        self.name_field_rect = layout.name_field_rect
        self.paste_rect = layout.paste_rect
        self.play_rect = layout.play_rect
        self.configure_rect = layout.configure_rect

    def _try_play(self) -> None:
        logged_in = self._recruiter_logged_in()
        if candidate_play_disabled(
            self.seed_state,
            name_text=self.name_text,
            recruiter_logged_in=logged_in,
        ):
            return
        self.finish(
            build_candidate_session_config(
                self.seed_text,
                candidate_label=self._candidate_label(),
            )
        )

    def _apply_seed_paste(self, pasted: str) -> None:
        normalized = normalize_pasted_seed(pasted)
        if not normalized:
            return
        if classify_seed_input(normalized) == "invalid":
            self.seed_text = normalized
            self.seed_editing = False
            self._layout()
            return
        self.seed_text = normalized
        self.seed_editing = True
        self._layout()

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            if self.seed_editing or self.name_editing:
                self.seed_editing = False
                self.name_editing = False
            else:
                self.finish(None)
            return True
        if self.name_editing:
            if symbol == arcade.key.BACKSPACE:
                self.name_text = self.name_text[:-1]
                self._layout()
            elif symbol in (arcade.key.ENTER, arcade.key.RETURN):
                self.name_editing = False
            return True
        if self.seed_editing:
            if symbol == arcade.key.BACKSPACE:
                self.seed_text = self.seed_text[:-1]
                self._layout()
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

    def _apply_name_paste(self, pasted: str) -> None:
        cleaned = " ".join(str(pasted).split())
        if not cleaned:
            return
        self.name_text = cleaned[:MAX_NAME_LENGTH]
        self.name_editing = True
        self._layout()

    def on_text(self, text: str) -> bool | None:
        if self.name_editing and text:
            if len(text) > 1:
                self._apply_name_paste(text)
            elif text != "\n":
                self.name_text = (self.name_text + text)[:MAX_NAME_LENGTH]
                self._layout()
            return True
        if not self.seed_editing or not text:
            return True
        if len(text) > 1:
            self._apply_seed_paste(text)
        elif not text.isspace():
            self.seed_text += text
            self._layout()
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        self.seed_editing = self._seed_field_hit(x, y, self.seed_field_rect)
        self.name_editing = (
            candidate_name_field_visible(self.seed_text)
            and not self._recruiter_logged_in()
            and self._seed_field_hit(x, y, self.name_field_rect)
        )
        if self.paste_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            self.name_editing = False
            self._paste_seed_from_clipboard()
        if self.play_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            self.name_editing = False
            self._try_play()
        if self.configure_rect.collidepoint(_mouse_screen_pos(self.window, x, y)):
            self.seed_editing = False
            self.name_editing = False
            if self._on_configure is not None:
                self._on_configure(self.seed_text)
        return True

    def on_draw(self) -> None:
        self.clear()
        layout = self._layout_state or layout_candidate(
            self.window.width,
            self.window.height,
            show_name=candidate_name_field_visible(self.seed_text),
        )
        cx = self.window.width // 2
        logged_in = self._recruiter_logged_in()
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
            CANDIDATE_HOME_SUBTITLE,
            cx,
            _arcade_y(self.window, layout.subtitle_top),
            MENU_MUTED,
            18,
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
        elif (
            self.seed_state == "valid"
            and not logged_in
            and not str(self.name_text).strip()
        ):
            arcade.Text(
                NAME_REQUIRED_MESSAGE,
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
        if candidate_name_field_visible(self.seed_text):
            arcade.Text(
                "Your name" if not logged_in else "Playing as",
                cx,
                _arcade_y(self.window, layout.name_label_top),
                MENU_MUTED,
                16,
                anchor_x="center",
                anchor_y="center",
            ).draw()
            name_display = self._candidate_label() or self.name_text
            self._draw_seed_field(
                self.name_field_rect,
                name_display or "",
                editing=self.name_editing and not logged_in,
                placeholder=NAME_PLACEHOLDER,
            )
        play_disabled = candidate_play_disabled(
            self.seed_state,
            name_text=self.name_text,
            recruiter_logged_in=logged_in,
        )
        self._draw_button(
            self.play_rect,
            candidate_play_button_label(self.seed_state),
            22,
            primary=not play_disabled,
            disabled=play_disabled,
        )
        self._draw_button(self.configure_rect, RECRUITER_DOOR_LABEL, 20)
        arcade.Text(
            CANDIDATE_HOME_FOOTER,
            cx,
            18,
            MENU_MUTED,
            14,
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
        on_needs_setup: Callable[[], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__()
        self.selected_preset = "normal"
        self.num_rounds = DEFAULT_ROUNDS
        self.selected_modifiers: set[str] = set()
        self.generated_seed_text = generated_seed_text
        self._generated_settings_fingerprint = ""
        decoded = decode_recruiter_seed(generated_seed_text)
        if decoded is not None:
            self.selected_preset = decoded.preset
            self.num_rounds = decoded.num_rounds
            self.selected_modifiers = set(decoded.modifiers)
            self._generated_settings_fingerprint = recruiter_settings_fingerprint(
                decoded.preset,
                decoded.num_rounds,
                decoded.modifiers,
            )
        self._copy_feedback_until = 0.0
        self._generate_error = ""
        self._rng = rng or random.Random()
        self._on_back = on_back
        self._on_start = on_start
        self._on_needs_setup = on_needs_setup
        self._layout_state: RecruiterLayout | None = None
        self.minus_rect = Rect(0, 0, 0, 0)
        self.plus_rect = Rect(0, 0, 0, 0)
        self.seed_display_rect = Rect(0, 0, 0, 0)
        self.copy_rect = Rect(0, 0, 0, 0)
        self.generate_rect = Rect(0, 0, 0, 0)
        self.start_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)
        self.preset_rects: dict[str, Rect] = {}
        self.modifier_toggle_rects: dict[str, Rect] = {}
        self.modifier_action_rects: dict[str, Rect] = {}
        self.modifier_explain_rect = Rect(0, 0, 0, 0)
        self._explained_modifier_id: str | None = None

    @property
    def active_modifiers(self) -> frozenset[str]:
        return frozenset(self.selected_modifiers)

    @property
    def seed_stale(self) -> bool:
        return recruiter_seed_stale(
            self.generated_seed_text,
            current_fingerprint=recruiter_settings_fingerprint(
                self.selected_preset,
                self.num_rounds,
                self.active_modifiers,
            ),
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
            modifier_ids=available_modifier_ids(),
        )
        self._layout_state = layout
        self.minus_rect = layout.minus_rect
        self.plus_rect = layout.plus_rect
        self.preset_rects = layout.preset_rects
        self.modifier_toggle_rects = layout.modifier_toggle_rects
        self.modifier_action_rects = layout.modifier_action_rects
        self.modifier_explain_rect = layout.modifier_explain_rect
        self.seed_display_rect = layout.seed_display_rect
        self.copy_rect = layout.copy_rect
        self.generate_rect = layout.generate_rect
        self.start_rect = layout.start_rect
        self.back_rect = layout.back_rect

    def _generate_seed(self) -> None:
        from pathwise.recruiter_accounts import RecruiterRecord, can_generate_codes
        from pathwise.recruiter_auth_views import user_safe_account_error
        from pathwise.recruiter_seeds import RecruiterSeedConflictError, register_recruiter_seed
        from pathwise.turso_http import TursoConfigError

        record = getattr(self.window, "_recruiter_record", None)
        if not isinstance(record, RecruiterRecord) or not can_generate_codes(record):
            self._generate_error = "This account cannot generate seeds."
            self._layout()
            return
        execute = getattr(self.window, "_recruiter_execute", None)
        if execute is not None and not callable(execute):
            execute = None
        last_conflict = False
        for _attempt in range(GENERATE_SEED_REGISTER_ATTEMPTS):
            map_seed = self._rng.randint(0, MAP_SEED_MOD_V9 - 1)
            encoded = encode_recruiter_seed(
                map_seed,
                self.selected_preset,
                self.num_rounds,
                modifiers=self.active_modifiers,
            )
            try:
                register_recruiter_seed(encoded, record.id, execute=execute)
            except RecruiterSeedConflictError:
                last_conflict = True
                continue
            except TursoConfigError as exc:
                if self._on_needs_setup is not None:
                    self._on_needs_setup()
                    return
                self._generate_error = user_safe_account_error(exc)
                self._layout()
                return
            except Exception as exc:
                self._generate_error = user_safe_account_error(exc)
                self._layout()
                return
            self._generate_error = ""
            self.generated_seed_text = encoded
            self._generated_settings_fingerprint = recruiter_settings_fingerprint(
                self.selected_preset,
                self.num_rounds,
                self.active_modifiers,
            )
            self._layout()
            return
        if last_conflict:
            self._generate_error = "Could not generate a unique seed. Try again."
        self._layout()

    def _share_hint(self) -> str:
        hint = RECRUITER_SEED_SHARE_HINT
        try:
            from pathwise.recruiter_notify import smtp_is_configured

            if smtp_is_configured():
                return hint
        except Exception:
            pass
        return f"{hint} {SMTP_OFF_HINT}"

    def _session_config(self) -> SessionConfig:
        from pathwise.recruiter_accounts import RecruiterRecord

        record = getattr(self.window, "_recruiter_record", None)
        label = record.email if isinstance(record, RecruiterRecord) else None
        return build_recruiter_session_config(
            self.generated_seed_text,
            preset=self.selected_preset,
            num_rounds=self.num_rounds,
            candidate_label=label,
        )

    def _try_start(self) -> None:
        if self._on_start is None:
            return
        if not recruiter_copy_enabled(self.generated_seed_text):
            return
        self._on_start(self._session_config())

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

    def _toggle_modifier_selection(self, modifier_id: str) -> None:
        """Add/remove a modifier (respecting conflicts) and show its info panel."""
        if modifier_id in self.selected_modifiers:
            self.selected_modifiers.discard(modifier_id)
        elif modifier_is_blocked(modifier_id, self.selected_modifiers):
            pass
        else:
            self.selected_modifiers.add(modifier_id)
        self._explained_modifier_id = modifier_id
        self._layout()

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        pos = _mouse_screen_pos(self.window, x, y)
        for preset_id, rect in self.preset_rects.items():
            if rect.collidepoint(pos):
                self.selected_preset = preset_id
                self._layout()
        for modifier_id, rect in self.modifier_action_rects.items():
            if rect.collidepoint(pos):
                self._toggle_modifier_selection(modifier_id)
                return True
        for modifier_id, rect in self.modifier_toggle_rects.items():
            if rect.collidepoint(pos):
                self._toggle_modifier_selection(modifier_id)
                return True
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
            modifier_ids=available_modifier_ids(),
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
                "One seed: each round uses a derived map from that seed",
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
        for entry in MODIFIER_CATALOG:
            modifier_id = entry["id"]
            rect = layout.modifier_toggle_rects.get(modifier_id)
            action = layout.modifier_action_rects.get(modifier_id)
            if rect is None or action is None:
                continue
            selected = modifier_id in self.selected_modifiers
            blocked = modifier_is_blocked(modifier_id, self.selected_modifiers)
            self._draw_button(rect, "", 18, selected=selected, disabled=blocked)
            center_y = _screen_y(self.window, rect)
            title_color = MENU_MUTED if blocked else (MENU_ACCENT if selected else MENU_TEXT)
            arcade.Text(
                entry["title"],
                rect.centerx,
                center_y,
                title_color,
                18,
                anchor_x="center",
                anchor_y="center",
            ).draw()
            self._draw_button(
                action,
                "-" if selected else "+",
                22,
                selected=selected,
                disabled=blocked,
            )
        explain = layout.modifier_explain_rect
        arcade.Text(
            "modifier info",
            explain.centerx,
            _arcade_y(self.window, layout.modifier_info_label_top + 12),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(explain, "", 14)
        if self._explained_modifier_id:
            body = modifier_explain_body(
                self._explained_modifier_id, self.active_modifiers
            )
            if body is not None:
                color = MENU_TEXT
            else:
                body = "no modifier is selected"
                color = MENU_MUTED
        else:
            body = "no modifier is selected"
            color = MENU_MUTED
        pad = 16
        text_width = max(120, explain.width - pad * 2)
        body = wrap_text_words(body, width_px=text_width, font_size=14)
        arcade.Text(
            body,
            explain.left + pad,
            _arcade_y(self.window, explain.top + pad),
            color,
            14,
            anchor_x="left",
            anchor_y="top",
            multiline=True,
            width=multiline_text_width(text_width),
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
        if getattr(self, "_generate_error", ""):
            arcade.Text(
                self._generate_error,
                cx,
                _arcade_y(self.window, layout.generate_error_top),
                MENU_ERROR,
                14,
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
                placeholder="(generate to create)",
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
        if self.generated_seed_text and not getattr(self, "_generate_error", ""):
            arcade.Text(
                self._share_hint(),
                cx,
                _arcade_y(self.window, layout.generate_error_top),
                MENU_MUTED,
                12,
                anchor_x="center",
                anchor_y="center",
            ).draw()


# Backward-compatible alias for tests and external callers.
PreGameMenuView = RecruiterConfigView


class DisclaimerView(_MenuView):
    """Mandatory safety disclaimer before any playable session starts."""

    def __init__(
        self,
        *,
        on_agree: Callable[[], None] | None = None,
        on_back: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_agree = on_agree
        self._on_back = on_back
        self.agreed = False
        self.checkbox_rect = Rect(0, 0, 0, 0)
        self.agree_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)
        self._title_ay = 0
        self._body_top_ay = 0
        self._body_floor_ay = 0

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _layout(self) -> None:
        cx = self.window.width // 2
        h = self.window.height
        # y-down Rect tops (larger = lower on screen) for hit testing.
        self.checkbox_rect = Rect(cx - 220, int(h * 0.58), 440, 40)
        self.agree_rect = Rect(cx - 120, int(h * 0.70), 240, 42)
        self.back_rect = Rect(cx - 120, int(h * 0.80), 240, 36)
        # Arcade Y (larger = higher on screen) for title/body.
        self._title_ay = int(h * 0.92)
        self._body_top_ay = int(h * 0.86)
        checkbox_arcade_top = h - self.checkbox_rect.top
        # Body ends above the checkbox with clear padding (no overlap).
        self._body_floor_ay = checkbox_arcade_top + 32

    def _toggle_agree(self) -> None:
        self.agreed = not self.agreed

    def _try_agree(self) -> None:
        if not self.agreed:
            return
        if self._on_agree is not None:
            self._on_agree()

    def _go_back(self) -> None:
        if self._on_back is not None:
            self._on_back()

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            self._go_back()
            return True
        if symbol == arcade.key.SPACE:
            self._toggle_agree()
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN):
            self._try_agree()
            return True
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        pos = _mouse_screen_pos(self.window, x, y)
        if self.checkbox_rect.collidepoint(pos):
            self._toggle_agree()
        elif self.agree_rect.collidepoint(pos):
            self._try_agree()
        elif self.back_rect.collidepoint(pos):
            self._go_back()
        return True

    def on_draw(self) -> None:
        self.clear()
        cx = self.window.width // 2
        h = self.window.height
        arcade.Text(
            DISCLAIMER_TITLE,
            cx,
            self._title_ay,
            MENU_TEXT,
            36,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        body_width = min(620, self.window.width - 80)
        wrapped = wrap_text_words(DISCLAIMER_BODY, width_px=body_width, font_size=16)
        body_h = max(1, self._body_top_ay - self._body_floor_ay)
        left = cx - body_width // 2
        prev_scissor = self.window.ctx.scissor
        self.window.ctx.scissor = (
            max(0, left - 4),
            max(0, self._body_floor_ay),
            body_width + 8,
            body_h,
        )
        try:
            arcade.Text(
                wrapped,
                modifier_desc_draw_x(left, body_width, text_width=body_width),
                self._body_top_ay,
                MENU_MUTED,
                16,
                anchor_x="left",
                anchor_y="top",
                multiline=True,
                width=multiline_text_width(body_width),
            ).draw()
        finally:
            self.window.ctx.scissor = prev_scissor
        box = self.checkbox_rect
        mark = "[x]" if self.agreed else "[ ]"
        arcade.Text(
            f"{mark}  {DISCLAIMER_AGREE_LABEL}",
            box.centerx,
            _screen_y(self.window, box),
            MENU_ACCENT if self.agreed else MENU_TEXT,
            18,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_button(
            self.agree_rect,
            "Agree and continue",
            20,
            primary=self.agreed,
            disabled=not self.agreed,
        )
        self._draw_button(self.back_rect, "Back", 18)


class ModifiersDetailView(_MenuView):
    def __init__(
        self,
        *,
        config: SessionConfig,
        on_back: Callable[[], None] | None = None,
        on_start: Callable[[SessionConfig], None] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._on_back = on_back
        self._on_start = on_start
        self.start_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _layout(self) -> None:
        cx = self.window.width // 2
        h = self.window.height
        self.start_rect = Rect(cx - 120, int(h * 0.28), 240, 42)
        self.back_rect = Rect(cx - 120, int(h * 0.20), 240, 36)

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            self._go_back()
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN, arcade.key.SPACE):
            self._try_start()
        return True

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        pos = _mouse_screen_pos(self.window, x, y)
        if self.start_rect.collidepoint(pos):
            self._try_start()
        if self.back_rect.collidepoint(pos):
            self._go_back()
        return True

    def _try_start(self) -> None:
        if self._on_start is not None:
            self._on_start(self.config)

    def _go_back(self) -> None:
        if self._on_back is not None:
            self._on_back()

    def on_draw(self) -> None:
        self.clear()
        cx = self.window.width // 2
        h = self.window.height
        arcade.Text(
            "Session modifiers",
            cx,
            h * 0.78,
            MENU_TEXT,
            40,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Active rules for this seed",
            cx,
            h * 0.70,
            MENU_MUTED,
            20,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        y = h * 0.58
        detail_width = min(560, self.window.width - 80)
        for title, description in modifier_detail_lines(
            self.config.modifiers, audience=self.config.audience
        ):
            arcade.Text(
                title,
                cx,
                y,
                MENU_ACCENT,
                22,
                anchor_x="center",
                anchor_y="center",
            ).draw()
            y -= 28
            wrapped = wrap_text_words(
                description, width_px=detail_width, font_size=15
            )
            arcade.Text(
                wrapped,
                modifier_desc_draw_x(
                    cx - detail_width // 2, detail_width, text_width=detail_width
                ),
                y,
                MENU_MUTED,
                15,
                anchor_x="left",
                anchor_y="center",
                multiline=True,
                width=multiline_text_width(detail_width),
            ).draw()
            y -= 56
        self._draw_button(self.start_rect, "Start session", 22, primary=True)
        self._draw_button(self.back_rect, "Back", 20)


class MessageView(_MenuView):
    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        accent: str = "",
        details: str = "",
        modifiers: frozenset[str] = frozenset(),
        audience: str = "candidate",
        auto_advance_s: float | None = None,
        on_complete: Callable | None = None,
        action_label: str = "",
        on_action: Callable[[], None] | None = None,
        dashboard_path: str = "",
    ) -> None:
        super().__init__(on_complete=on_complete)
        from pathwise.modifiers import hidden

        self.title = title
        self.subtitle = subtitle
        self.accent = accent
        self.details = details
        self.audience = "recruiter" if audience == "recruiter" else "candidate"
        self.modifiers = hidden.visible_modifiers(modifiers, audience=self.audience)
        self.auto_advance_s = auto_advance_s
        self.action_label = action_label
        self._on_action = on_action
        self.dashboard_path = dashboard_path
        self.action_rect: Rect | None = None
        self._elapsed = 0.0
        self._modifiers_popup_open = False
        self.modifiers_btn_rect: Rect | None = None
        self._popup_card_rect = Rect(0, 0, 0, 0)
        self._popup_scroll = 0
        self._popup_content_h = 0
        self._popup_max_scroll = 0

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout_message()

    def on_resize(self, width: int, height: int) -> None:
        self._layout_message()

    def _layout_message(self) -> None:
        self.action_rect = None
        if self.action_label:
            cx = self.window.width // 2
            h = self.window.height
            btn_h = max(34, int(h * 0.045))
            self.action_rect = Rect(cx - 140, int(h * 0.16), 280, btn_h)
        if not self.modifiers:
            self.modifiers_btn_rect = None
            self._popup_card_rect = Rect(0, 0, 0, 0)
            self._popup_content_h = 0
            self._popup_max_scroll = 0
            self._popup_scroll = 0
            return
        cx = self.window.width // 2
        h = self.window.height
        btn_h = max(34, int(h * 0.045))
        btn_top = int(h * 0.31)
        self.modifiers_btn_rect = Rect(cx - 120, btn_top, 240, btn_h)
        card_w = min(520, max(280, self.window.width - 80))
        body_content_h = measure_modifier_popup_body_height(
            card_w, self.modifiers, audience=self.audience
        )
        header_budget = POPUP_HEADER_TOP + POPUP_HEADER_HEIGHT + POPUP_HEADER_GAP
        self._popup_content_h = header_budget + body_content_h + POPUP_CARD_BOTTOM_PAD
        # Tall enough to read several entries, still short enough to require scroll.
        max_card_h = min(h - 80, max(240, int(h * 0.72)))
        card_h = max_card_h
        card_top = (h - card_h) // 2
        self._popup_card_rect = Rect(cx - card_w // 2, card_top, card_w, card_h)
        body_h = max(1, card_h - header_budget - POPUP_CARD_BOTTOM_PAD)
        self._popup_max_scroll = max(0, body_content_h - body_h)
        self._clamp_popup_scroll()

    def _clamp_popup_scroll(self) -> None:
        self._popup_scroll = max(0, min(int(self._popup_scroll), int(self._popup_max_scroll)))

    def _open_modifiers_popup(self) -> None:
        self._modifiers_popup_open = True
        self._popup_scroll = 0
        self._layout_message()

    def _close_modifiers_popup(self) -> None:
        self._modifiers_popup_open = False
        self._popup_scroll = 0

    def _scroll_modifiers_popup(self, delta: float) -> None:
        if not self._modifiers_popup_open or self._popup_max_scroll <= 0:
            return
        # Trackpads / Windows can emit fractional scroll units; never truncate to 0.
        raw = float(delta) * POPUP_SCROLL_STEP
        step = int(raw)
        if delta != 0 and step == 0:
            step = 1 if delta > 0 else -1
        self._popup_scroll -= step
        self._clamp_popup_scroll()

    def on_update(self, delta_time: float) -> None:
        if self.auto_advance_s is None:
            return
        self._elapsed += delta_time
        if self._elapsed >= self.auto_advance_s:
            self.finish(True)

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if self._modifiers_popup_open:
            if symbol == arcade.key.ESCAPE:
                self._close_modifiers_popup()
            elif symbol in (arcade.key.DOWN, arcade.key.S):
                self._scroll_modifiers_popup(-1)
            elif symbol in (arcade.key.UP, arcade.key.W):
                self._scroll_modifiers_popup(1)
            elif symbol == arcade.key.PAGEDOWN:
                self._scroll_modifiers_popup(-3)
            elif symbol == arcade.key.PAGEUP:
                self._scroll_modifiers_popup(3)
            return True
        self.finish(True)
        return True

    def on_mouse_scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> bool | None:
        if self._modifiers_popup_open:
            self._scroll_modifiers_popup(scroll_y)
            return True
        return None

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        pos = _mouse_screen_pos(self.window, x, y)
        if self._modifiers_popup_open:
            if self._popup_card_rect.collidepoint(pos):
                return True
            self._close_modifiers_popup()
            return True
        if self.modifiers_btn_rect and self.modifiers_btn_rect.collidepoint(pos):
            self._open_modifiers_popup()
            return True
        if self.action_rect is not None and self.action_rect.collidepoint(pos):
            if self._on_action is not None:
                self._on_action()
            return True
        self.finish(True)
        return True

    def _draw_modifiers_popup(self) -> None:
        w = self.window.width
        h = self.window.height
        arcade.draw_lbwh_rectangle_filled(0, 0, w, h, (20, 28, 36, 160))
        card = self._popup_card_rect
        left = card.left
        bottom = h - card.bottom
        arcade.draw_lbwh_rectangle_filled(left, bottom, card.width, card.height, MENU_CARD)
        arcade.draw_lbwh_rectangle_outline(left, bottom, card.width, card.height, MENU_BORDER, 2)
        cx = card.centerx
        text_width = _modifier_popup_text_width(card.width)
        header_y = card.top + POPUP_HEADER_TOP
        arcade.Text(
            "Session modifiers",
            cx,
            _arcade_y(self.window, header_y),
            MENU_TEXT,
            26,
            anchor_x="center",
            anchor_y="top",
        ).draw()
        body_top = header_y + POPUP_HEADER_HEIGHT + POPUP_HEADER_GAP
        body_bottom = card.bottom - POPUP_CARD_BOTTOM_PAD
        body_h = max(1, body_bottom - body_top)
        scissor_bottom = h - body_bottom
        prev_scissor = self.window.ctx.scissor
        self.window.ctx.scissor = (left + 4, scissor_bottom, max(1, card.width - 8), body_h)
        try:
            cursor = body_top - self._popup_scroll
            entries = modifier_detail_lines(self.modifiers, audience=self.audience)
            for index, (title, description) in enumerate(entries):
                title_text = arcade.Text(
                    title,
                    cx,
                    _arcade_y(self.window, cursor),
                    MENU_ACCENT,
                    POPUP_TITLE_FONT,
                    anchor_x="center",
                    anchor_y="top",
                )
                title_text.draw()
                title_height = _safe_text_content_height(
                    title_text,
                    fallback=_estimated_wrapped_text_height(
                        title,
                        font_size=POPUP_TITLE_FONT,
                        width_px=text_width,
                    ),
                )
                cursor += title_height + POPUP_TITLE_DESC_GAP
                wrapped_desc = wrap_text_words(
                    description, width_px=text_width, font_size=POPUP_DESC_FONT
                )
                desc_x = modifier_desc_draw_x(left, card.width, text_width=text_width)
                desc_text = arcade.Text(
                    wrapped_desc,
                    desc_x,
                    _arcade_y(self.window, cursor),
                    MENU_MUTED,
                    POPUP_DESC_FONT,
                    anchor_x="left",
                    anchor_y="top",
                    multiline=True,
                    width=multiline_text_width(text_width),
                )
                desc_text.draw()
                desc_height = _safe_text_content_height(
                    desc_text,
                    fallback=_estimated_wrapped_text_height(
                        wrapped_desc,
                        font_size=POPUP_DESC_FONT,
                        width_px=text_width,
                    ),
                )
                cursor += desc_height
                if index < len(entries) - 1:
                    cursor += POPUP_ENTRY_GAP
            # Sync scroll range to measured text so long catalogs stay reachable.
            measured_body = max(0, int(cursor - body_top + self._popup_scroll))
            synced_max = max(0, measured_body - body_h)
            if synced_max > self._popup_max_scroll:
                self._popup_max_scroll = synced_max
            self._clamp_popup_scroll()
        finally:
            self.window.ctx.scissor = prev_scissor
        if self._popup_max_scroll > 0:
            hint = "Scroll for more"
            if self._popup_scroll >= self._popup_max_scroll:
                hint = "Scroll up"
            arcade.Text(
                hint,
                cx,
                _arcade_y(self.window, card.bottom - 8),
                MENU_MUTED,
                12,
                anchor_x="center",
                anchor_y="bottom",
            ).draw()

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
                18 if len(self.accent) > 48 else 24,
                anchor_x="center",
                anchor_y="center",
            ).draw()
        if self.action_rect is not None and self.action_label:
            self._draw_button(self.action_rect, self.action_label, 18, primary=True)
        if self.modifiers_btn_rect is not None:
            self._draw_button(self.modifiers_btn_rect, "See modifiers", 18, primary=True)
        if self.details:
            arcade.Text(
                self.details,
                cx,
                h * 0.22,
                MENU_MUTED,
                16,
                anchor_x="center",
                anchor_y="center",
                multiline=True,
                width=min(560, self.window.width - 80),
            ).draw()
        if self._modifiers_popup_open:
            self._draw_modifiers_popup()


def run_pre_game_menu(window: arcade.Window) -> SessionConfig | None:
    view = CandidateHomeView()
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
    return view._result


def round_intro_hint(
    profile: DifficultyProfile,
    *,
    time_limit_s: int,
    round_index: int = 1,
) -> str:
    """Subtitle for round intro: uses the map's actual route timer."""
    hint = (
        f"~{profile.min_crossings}-{profile.max_crossings} roads · "
        f"{int(time_limit_s)}s route timer · denser traffic"
    )
    if round_index > 1:
        hint += f" (+{int(profile.round_escalation * 100)}% vs round 1)"
    return hint


def run_round_intro(
    window: arcade.Window,
    round_index: int,
    total_rounds: int,
    profile: DifficultyProfile,
    *,
    time_limit_s: int,
    modifiers: frozenset[str] = frozenset(),
) -> bool:
    view = MessageView(
        title=f"Round {round_index} of {total_rounds}",
        subtitle=round_intro_hint(profile, time_limit_s=time_limit_s, round_index=round_index),
        accent=ROUND_START_PROMPT,
        details=ROUND_CONTROLS_HINT,
        modifiers=modifiers,
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
    label = round_outcome_label(outcome)
    sub = "Next round will be harder" if round_index < total_rounds else "Session finishing…"
    view = MessageView(
        title=f"Round {round_index} complete: {label}",
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
    summary = " · ".join(
        f"R{i + 1}: {round_outcome_label(o)}" for i, o in enumerate(outcomes)
    )
    subtitle = summary
    if session_seed is not None:
        subtitle += f"\nSession seed: {session_seed}"
    last_label = round_outcome_label(outcomes[-1]) if outcomes else "Done"
    title = (
        f"Round complete: {last_label}"
        if total_rounds == 1
        else f"All {total_rounds} rounds complete"
    )
    view = MessageView(
        title=title,
        subtitle=subtitle,
        accent="Open logs_dashboard.html for per-round replays",
    )
    window.show_view(view)
    while not view._done and not window.closed:
        pump_frame(window)
