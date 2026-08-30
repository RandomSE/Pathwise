"""Arcade recruiter login and registration screens.

Calls pathwise.recruiter_accounts from the game this slice. Never log
TURSO_AUTH_TOKEN, raw passwords, or password_hash.
"""

from __future__ import annotations

from collections.abc import Callable

import arcade

from pathwise.geom import Rect
from pathwise.menu_layout import (
    RecruiterAuthLayout,
    RecruiterRegisterLayout,
    layout_recruiter_auth,
    layout_recruiter_register,
)
from pathwise.pre_game import (
    MENU_BG,
    MENU_ERROR,
    MENU_MUTED,
    MENU_TEXT,
    _MenuView,
    _arcade_y,
    _mouse_screen_pos,
)
from pathwise.recruiter_accounts import (
    RecruiterAuthError,
    RecruiterDuplicateEmailError,
    RecruiterRecord,
    RecruiterValidationError,
    authenticate_recruiter,
    create_recruiter,
)
from pathwise.turso_http import TursoConfigError, TursoHttpError

OFFLINE_MESSAGE = "Could not reach the account service. Try again later."
CONFIRM_MISMATCH_MESSAGE = "Passwords do not match"
MAX_EMAIL_CHARS = 254
MAX_PASSWORD_CHARS = 128
PASSWORD_BULLET = "*"


def user_safe_account_error(exc: BaseException) -> str:
    if isinstance(exc, RecruiterAuthError):
        return str(exc) or "Invalid credentials"
    if isinstance(exc, RecruiterDuplicateEmailError):
        return "That email is already registered"
    if isinstance(exc, RecruiterValidationError):
        return str(exc)
    if isinstance(exc, (TursoHttpError, TursoConfigError)):
        return OFFLINE_MESSAGE
    return OFFLINE_MESSAGE


class _AuthFormView(_MenuView):
    _fields: tuple[str, ...] = ("email", "password")

    def __init__(
        self,
        *,
        on_success: Callable[[RecruiterRecord, str], None] | None = None,
        on_back: Callable[[], None] | None = None,
        execute=None,
    ) -> None:
        super().__init__()
        self._on_success = on_success
        self._on_back = on_back
        self._execute = execute
        self.email_text = ""
        self.password_text = ""
        self.confirm_text = ""
        self.error_text = ""
        self._focus = "email"

    def _append_focus(self, text: str) -> None:
        if self._focus == "email" and len(self.email_text) < MAX_EMAIL_CHARS:
            self.email_text += text
        elif self._focus == "password" and len(self.password_text) < MAX_PASSWORD_CHARS:
            self.password_text += text
        elif self._focus == "confirm" and len(self.confirm_text) < MAX_PASSWORD_CHARS:
            self.confirm_text += text

    def _backspace_focus(self) -> None:
        if self._focus == "email":
            self.email_text = self.email_text[:-1]
        elif self._focus == "password":
            self.password_text = self.password_text[:-1]
        elif self._focus == "confirm":
            self.confirm_text = self.confirm_text[:-1]

    def _cycle_focus(self) -> None:
        if not self._fields:
            return
        if self._focus not in self._fields:
            self._focus = self._fields[0]
            return
        index = self._fields.index(self._focus)
        self._focus = self._fields[(index + 1) % len(self._fields)]

    def _masked_password(self, text: str | None = None) -> str:
        value = self.password_text if text is None else text
        return PASSWORD_BULLET * len(value)

    def _paste_into_focus(self, raw: str) -> None:
        text = str(raw or "")
        if not text:
            return
        if self._focus == "email":
            cleaned = "".join(text.split())[:MAX_EMAIL_CHARS]
            if not cleaned:
                return
            self.email_text = cleaned
        elif self._focus == "password":
            cleaned = text.replace("\r", "").strip("\n").strip()[:MAX_PASSWORD_CHARS]
            if not cleaned:
                return
            self.password_text = cleaned
        elif self._focus == "confirm":
            cleaned = text.replace("\r", "").strip("\n").strip()[:MAX_PASSWORD_CHARS]
            if not cleaned:
                return
            self.confirm_text = cleaned
        self._layout()

    def _paste_from_clipboard(self) -> None:
        try:
            pasted = self.window.get_clipboard_text() or ""
        except Exception:
            pasted = ""
        self._paste_into_focus(pasted)

    def _go_back(self) -> None:
        if self._on_back is not None:
            self._on_back()

    def _submit(self) -> None:
        raise NotImplementedError

    def on_text(self, text: str) -> bool | None:
        if not self._focus or not text or text == "\r":
            return True
        if len(text) > 1:
            self._paste_into_focus(text)
            return True
        if text.isspace():
            return True
        self._append_focus(text)
        self._layout()
        return True

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol == arcade.key.ESCAPE:
            self._go_back()
            return True
        if symbol == arcade.key.TAB:
            self._cycle_focus()
            return True
        if symbol == arcade.key.BACKSPACE:
            self._backspace_focus()
            self._layout()
            return True
        if symbol in (arcade.key.ENTER, arcade.key.RETURN):
            self._submit()
            return True
        if symbol == arcade.key.V and modifiers & arcade.key.MOD_CTRL:
            self._paste_from_clipboard()
            return True
        if symbol == arcade.key.C and modifiers & arcade.key.MOD_CTRL:
            return True
        return True

    def _focus_field_at(self, x: float, y: float) -> None:
        pos = _mouse_screen_pos(self.window, x, y)
        mapping = self._focus_rects()
        for name, rect in mapping.items():
            if rect.collidepoint(pos):
                self._focus = name
                return

    def _focus_rects(self) -> dict[str, Rect]:
        return {}

    def _layout(self) -> None:
        raise NotImplementedError

    def on_show_view(self) -> None:
        arcade.set_background_color(MENU_BG)
        self._layout()

    def on_resize(self, width: int, height: int) -> None:
        self._layout()

    def _emit_success(self, record: RecruiterRecord, token: str) -> None:
        if self._on_success is not None:
            self._on_success(record, token)

    def _draw_error(self, cx: int, top: int) -> None:
        if not self.error_text:
            return
        arcade.Text(
            self.error_text,
            cx,
            _arcade_y(self.window, top),
            MENU_ERROR,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()


class RecruiterLoginView(_AuthFormView):
    _fields = ("email", "password")

    def __init__(
        self,
        *,
        on_success: Callable[[RecruiterRecord, str], None] | None = None,
        on_register: Callable[[], None] | None = None,
        on_back: Callable[[], None] | None = None,
        execute=None,
    ) -> None:
        super().__init__(on_success=on_success, on_back=on_back, execute=execute)
        self._on_register = on_register
        self._layout_state: RecruiterAuthLayout | None = None
        self.email_field_rect = Rect(0, 0, 0, 0)
        self.password_field_rect = Rect(0, 0, 0, 0)
        self.login_rect = Rect(0, 0, 0, 0)
        self.register_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)

    def _layout(self) -> None:
        layout = layout_recruiter_auth(self.window.width, self.window.height)
        self._layout_state = layout
        self.email_field_rect = layout.email_field_rect
        self.password_field_rect = layout.password_field_rect
        self.login_rect = layout.login_rect
        self.register_rect = layout.register_rect
        self.back_rect = layout.back_rect

    def _focus_rects(self) -> dict[str, Rect]:
        return {
            "email": self.email_field_rect,
            "password": self.password_field_rect,
        }

    def _submit(self) -> None:
        try:
            record, token = authenticate_recruiter(
                self.email_text,
                self.password_text,
                execute=self._execute,
            )
        except (
            RecruiterAuthError,
            RecruiterValidationError,
            TursoHttpError,
            TursoConfigError,
        ) as exc:
            self.error_text = user_safe_account_error(exc)
            self._layout()
            return
        self.error_text = ""
        self._emit_success(record, token)

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        self._focus_field_at(x, y)
        pos = _mouse_screen_pos(self.window, x, y)
        if self.login_rect.collidepoint(pos):
            self._submit()
        elif self.register_rect.collidepoint(pos) and self._on_register is not None:
            self._on_register()
        elif self.back_rect.collidepoint(pos):
            self._go_back()
        return True

    def on_draw(self) -> None:
        self.clear()
        layout = self._layout_state or layout_recruiter_auth(
            self.window.width, self.window.height
        )
        cx = self.window.width // 2
        arcade.Text(
            "Pathwise",
            cx,
            _arcade_y(self.window, layout.title_top),
            MENU_TEXT,
            40,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Recruiter sign in",
            cx,
            _arcade_y(self.window, layout.subtitle_top),
            MENU_MUTED,
            20,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_error(cx, layout.error_label_top)
        arcade.Text(
            "Email",
            cx,
            _arcade_y(self.window, layout.email_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(
            self.email_field_rect,
            self.email_text,
            editing=self._focus == "email",
            placeholder="email",
        )
        arcade.Text(
            "Password",
            cx,
            _arcade_y(self.window, layout.password_label_top),
            MENU_MUTED,
            16,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(
            self.password_field_rect,
            self._masked_password(),
            editing=self._focus == "password",
            placeholder="password",
        )
        self._draw_button(self.login_rect, "Log in", 20, primary=True)
        self._draw_button(self.register_rect, "Create account", 18)
        self._draw_button(self.back_rect, "Back", 16)
        arcade.Text(
            "Esc to go back",
            cx,
            18,
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()


class RecruiterRegisterView(_AuthFormView):
    _fields = ("email", "password", "confirm")

    def __init__(
        self,
        *,
        on_success: Callable[[RecruiterRecord, str], None] | None = None,
        on_back: Callable[[], None] | None = None,
        execute=None,
    ) -> None:
        super().__init__(on_success=on_success, on_back=on_back, execute=execute)
        self._layout_state: RecruiterRegisterLayout | None = None
        self.email_field_rect = Rect(0, 0, 0, 0)
        self.password_field_rect = Rect(0, 0, 0, 0)
        self.confirm_field_rect = Rect(0, 0, 0, 0)
        self.create_rect = Rect(0, 0, 0, 0)
        self.back_rect = Rect(0, 0, 0, 0)

    def _layout(self) -> None:
        layout = layout_recruiter_register(self.window.width, self.window.height)
        self._layout_state = layout
        self.email_field_rect = layout.email_field_rect
        self.password_field_rect = layout.password_field_rect
        self.confirm_field_rect = layout.confirm_field_rect
        self.create_rect = layout.create_rect
        self.back_rect = layout.back_rect

    def _focus_rects(self) -> dict[str, Rect]:
        return {
            "email": self.email_field_rect,
            "password": self.password_field_rect,
            "confirm": self.confirm_field_rect,
        }

    def _submit(self) -> None:
        if self.password_text != self.confirm_text:
            self.error_text = CONFIRM_MISMATCH_MESSAGE
            self._layout()
            return
        try:
            create_recruiter(
                self.email_text,
                self.password_text,
                execute=self._execute,
            )
            record, token = authenticate_recruiter(
                self.email_text,
                self.password_text,
                execute=self._execute,
            )
        except (
            RecruiterValidationError,
            RecruiterDuplicateEmailError,
            RecruiterAuthError,
            TursoHttpError,
            TursoConfigError,
        ) as exc:
            self.error_text = user_safe_account_error(exc)
            self._layout()
            return
        self.error_text = ""
        self._emit_success(record, token)

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int) -> bool | None:
        if button != arcade.MOUSE_BUTTON_LEFT:
            return True
        self._focus_field_at(x, y)
        pos = _mouse_screen_pos(self.window, x, y)
        if self.create_rect.collidepoint(pos):
            self._submit()
        elif self.back_rect.collidepoint(pos):
            self._go_back()
        return True

    def on_draw(self) -> None:
        self.clear()
        layout = self._layout_state or layout_recruiter_register(
            self.window.width, self.window.height
        )
        cx = self.window.width // 2
        arcade.Text(
            "Pathwise",
            cx,
            _arcade_y(self.window, layout.title_top),
            MENU_TEXT,
            36,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        arcade.Text(
            "Create a recruiter account",
            cx,
            _arcade_y(self.window, layout.subtitle_top),
            MENU_MUTED,
            18,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_error(cx, layout.error_label_top)
        arcade.Text(
            "Email",
            cx,
            _arcade_y(self.window, layout.email_label_top),
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(
            self.email_field_rect,
            self.email_text,
            editing=self._focus == "email",
            placeholder="email",
        )
        arcade.Text(
            "Password",
            cx,
            _arcade_y(self.window, layout.password_label_top),
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(
            self.password_field_rect,
            self._masked_password(),
            editing=self._focus == "password",
            placeholder="password",
        )
        arcade.Text(
            "Confirm password",
            cx,
            _arcade_y(self.window, layout.confirm_label_top),
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()
        self._draw_seed_field(
            self.confirm_field_rect,
            self._masked_password(self.confirm_text),
            editing=self._focus == "confirm",
            placeholder="confirm",
        )
        self._draw_button(self.create_rect, "Create account", 20, primary=True)
        self._draw_button(self.back_rect, "Back to login", 16)
        arcade.Text(
            "Esc to go back",
            cx,
            18,
            MENU_MUTED,
            14,
            anchor_x="center",
            anchor_y="center",
        ).draw()
