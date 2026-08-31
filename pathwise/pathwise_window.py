"""Arcade window hosting Pathwise menus and gameplay."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone

import arcade

from . import commonUtils
from . import pre_game
from .input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
from map_generation.difficulty import DifficultyProfile
from .modifiers.registry import ModifierContext
from .session_seed import resolve_candidate_play_seed

WIDTH = commonUtils.WIDTH
HEIGHT = commonUtils.HEIGHT
logger = logging.getLogger(__name__)


def vsync_enabled(*, smoke_mode: bool = False) -> bool:
    """Play defaults to vsync on. Tear bands otherwise race down the screen."""
    raw = os.environ.get("PATHWISE_VSYNC", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return not smoke_mode

SIM_ORIGIN = "top_left_y_down"

_ARCADE_KEY_MAP = {
    arcade.key.LEFT: KEY_LEFT,
    arcade.key.A: KEY_LEFT,
    arcade.key.RIGHT: KEY_RIGHT,
    arcade.key.D: KEY_RIGHT,
    arcade.key.UP: KEY_UP,
    arcade.key.W: KEY_UP,
    arcade.key.DOWN: KEY_DOWN,
    arcade.key.S: KEY_DOWN,
}

_ARCADE_SPRINT_KEYS = frozenset({arcade.key.LSHIFT, arcade.key.RSHIFT})


class GamePlayView(arcade.View):
    def __init__(self, *, on_round_complete: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.keys = KeyState()
        self._draw_state = None
        self._on_round_complete = on_round_complete
        self._round_complete_fired = False
        self._display_layout = None
        self._layout_size = (0, 0)
        self._game = None
        self._fps_tracker = None
        self._shift_held = False

    def _fps_tracker_instance(self):
        from pathwise.fps_tracker import FpsTracker

        if self._fps_tracker is None:
            self._fps_tracker = FpsTracker()
        return self._fps_tracker

    def _game_module(self):
        if self._game is None:
            import main as game

            self._game = game
        return self._game

    def _sync_display_layout(self) -> None:
        from pathwise.viewport import DisplayLayout

        w = int(self.window.width)
        h = int(self.window.height)
        size = (w, h)
        if size != self._layout_size or self._display_layout is None:
            self._layout_size = size
            self._display_layout = DisplayLayout.fit_window(w, h)

    def on_show_view(self) -> None:
        from pathwise import sprites
        from pathwise.gameplay_framebuffer import (
            fixed_sprite_bake_multiplier,
            prewarm_draw_gpu_assets,
        )

        arcade.set_background_color((236, 244, 252))
        self._sync_display_layout()
        sprites.set_render_bake_multiplier(
            fixed_sprite_bake_multiplier(self._display_layout)
        )
        prewarm_draw_gpu_assets(self._display_layout)
        self.keys.clear()
        self._shift_held = False
        self._round_complete_fired = False
        self._game = None
        game = self._game_module()
        if game.round_active:
            self._draw_state = game.update_round_frame(self.keys)
        else:
            self._draw_state = None

    def on_key_press(self, symbol: int, modifiers: int) -> bool | None:
        if symbol in _ARCADE_SPRINT_KEYS:
            if not self._shift_held:
                self._shift_held = True
                game = self._game_module()
                player = getattr(game, "player", None)
                if getattr(game, "round_active", False) and player is not None:
                    player.toggle_sprint()
            return True
        logical = _ARCADE_KEY_MAP.get(symbol)
        if logical:
            self.keys.press(logical)
        return True

    def on_key_release(self, symbol: int, modifiers: int) -> bool | None:
        if symbol in _ARCADE_SPRINT_KEYS:
            self._shift_held = False
            return True
        logical = _ARCADE_KEY_MAP.get(symbol)
        if logical:
            self.keys.release(logical)
        return True

    def on_update(self, delta_time: float) -> None:
        game = self._game_module()

        if not game.app_running:
            if self._on_round_complete and not self._round_complete_fired:
                self._round_complete_fired = True
                self._on_round_complete()
            return

        if game.round_active:
            self._draw_state = game.update_round_frame(self.keys)

        if not game.round_active and self._on_round_complete and not self._round_complete_fired:
            self._round_complete_fired = True
            self._on_round_complete()

    def on_resize(self, width: int, height: int) -> None:
        from pathwise import sprites
        from pathwise.gameplay_framebuffer import (
            fixed_sprite_bake_multiplier,
            prewarm_draw_gpu_assets,
        )
        from pathwise.viewport import DisplayLayout

        self._layout_size = (width, height)
        self._display_layout = DisplayLayout.fit_window(width, height)
        sprites.set_render_bake_multiplier(
            fixed_sprite_bake_multiplier(self._display_layout)
        )
        prewarm_draw_gpu_assets(self._display_layout)

    def on_draw(self) -> None:
        import time

        game = self._game_module()
        present_t = time.perf_counter()
        self._fps_tracker_instance().note_present(present_t)

        t0 = time.perf_counter()
        if not (
            self._display_layout is not None
            and self._display_layout.uses_gpu_viewport
        ):
            self.clear()
        self._sync_display_layout()
        if self._draw_state is None:
            return

        hud_lines = [
            self._fps_tracker_instance().hud_line(),
            *self._draw_state["hud_lines"],
        ]
        from pathwise.modifiers import hidden

        if hidden.suppress_hud():
            hud_lines = []
        draw_state = {**self._draw_state, "hud_lines": hud_lines}

        game.draw_round_frame(
            self.window.width,
            self.window.height,
            draw_state,
            display_layout=self._display_layout,
        )
        if game.ENABLE_PERF_PROFILE:
            game.perf_profiler.finish_draw(time.perf_counter() - t0)


class PathwiseWindow(arcade.Window):
    def __init__(
        self,
        *,
        auto_close_seconds: float | None = None,
        fullscreen: bool = True,
    ) -> None:
        use_fullscreen = fullscreen and auto_close_seconds is None
        smoke_mode = auto_close_seconds is not None
        super().__init__(
            WIDTH,
            HEIGHT,
            "Pathwise MVP",
            update_rate=1 / 60,
            draw_rate=1 / 60,
            vsync=vsync_enabled(smoke_mode=smoke_mode),
            fullscreen=use_fullscreen,
        )
        self._auto_close_seconds = auto_close_seconds
        self._elapsed = 0.0
        self._smoke_mode = auto_close_seconds is not None
        self._config: pre_game.SessionConfig | None = None
        self._pending_config: pre_game.SessionConfig | None = None
        self._modifiers_from_recruiter = False
        self._disclaimer_accepted = False
        self._disclaimer_return_to = "candidate"
        self._base_profile: DifficultyProfile | None = None
        self._round_index = 1
        self._outcomes: list[str] = []
        self._seed_text = ""
        self._recruiter_generated_text = ""
        self._recruiter_record = None
        self._recruiter_session_token = None
        self._recruiter_execute = None
        self._notify_recruiter = None
        self._notify_send = None

    def run(self) -> None:
        if self._smoke_mode:
            super().run()
            return
        self._show_candidate_home()
        super().run()

    def _show_candidate_home(self) -> None:
        self.show_view(
            pre_game.CandidateHomeView(
                seed_text=self._seed_text,
                on_complete=self._on_pre_game_done,
                on_configure=self._on_open_recruiter,
            )
        )

    def _show_modifiers_detail(self, config: pre_game.SessionConfig) -> None:
        self._pending_config = config
        self.show_view(
            pre_game.ModifiersDetailView(
                config=config,
                on_back=self._on_modifiers_back,
                on_start=self._on_pre_game_done,
            )
        )

    def recruiter_session_active(self) -> bool:
        record = getattr(self, "_recruiter_record", None)
        token = getattr(self, "_recruiter_session_token", None)
        return record is not None and bool(token)

    def recruiter_can_generate_codes(self) -> bool:
        from pathwise.recruiter_accounts import RecruiterRecord, can_generate_codes

        record = self._recruiter_record
        if not isinstance(record, RecruiterRecord):
            return False
        return can_generate_codes(record)

    def _show_recruiter_login(self) -> None:
        from pathwise.recruiter_auth_views import RecruiterLoginView

        self.show_view(
            RecruiterLoginView(
                on_success=self._on_recruiter_authenticated,
                on_register=self._show_recruiter_register,
                on_back=self._show_candidate_home,
                execute=self._recruiter_execute,
            )
        )

    def _show_recruiter_register(self) -> None:
        from pathwise.recruiter_auth_views import RecruiterRegisterView

        self.show_view(
            RecruiterRegisterView(
                on_success=self._on_recruiter_authenticated,
                on_back=self._show_recruiter_login,
                execute=self._recruiter_execute,
            )
        )

    def _on_recruiter_authenticated(self, record, token: str) -> None:
        self._recruiter_record = record
        self._recruiter_session_token = token
        self._show_recruiter_config(generated_seed_text=self._recruiter_generated_text)

    def _return_to_recruiter_flow(self) -> None:
        if self.recruiter_session_active():
            self._show_recruiter_config(
                generated_seed_text=self._recruiter_generated_text,
            )
            return
        self._show_recruiter_login()

    def _on_modifiers_back(self) -> None:
        if getattr(self, "_modifiers_from_recruiter", False):
            self._modifiers_from_recruiter = False
            self._return_to_recruiter_flow()
            return
        self._show_candidate_home()

    def _show_recruiter_config(self, *, generated_seed_text: str = "") -> None:
        self.show_view(
            pre_game.RecruiterConfigView(
                generated_seed_text=generated_seed_text,
                on_back=self._on_recruiter_back,
                on_start=self._on_recruiter_start,
            )
        )

    def _on_open_recruiter(self, seed_text: str) -> None:
        self._seed_text = seed_text
        if self.recruiter_session_active():
            self._show_recruiter_config(generated_seed_text="")
            return
        self._show_recruiter_login()

    def _show_modifiers_detail_from_recruiter(self, config: pre_game.SessionConfig) -> None:
        view = self.current_view
        if isinstance(view, pre_game.RecruiterConfigView):
            self._recruiter_generated_text = view.generated_seed_text
        self._modifiers_from_recruiter = True
        self._show_modifiers_detail(config)

    def _on_recruiter_back(self, seed_text: str) -> None:
        self._seed_text = seed_text
        self._show_candidate_home()

    def _on_recruiter_start(self, config: pre_game.SessionConfig) -> None:
        view = getattr(self, "_current_view", None)
        if isinstance(view, pre_game.RecruiterConfigView):
            self._recruiter_generated_text = view.generated_seed_text
        self._request_session_start(config, return_to="recruiter")

    def on_draw(self) -> None:
        # Do not clear when a View is active; its on_draw already clears and paints.
        # Clearing here was wiping the menu/game after the view drew (white screen).
        if self.current_view is None:
            self.clear()

    def on_update(self, delta_time: float) -> None:
        if self._auto_close_seconds is None:
            return
        self._elapsed += delta_time
        if self._elapsed >= self._auto_close_seconds:
            arcade.close_window()

    def _show_disclaimer(self) -> None:
        self.show_view(
            pre_game.DisclaimerView(
                on_agree=self._on_disclaimer_agreed,
                on_back=self._on_disclaimer_back,
            )
        )

    def _on_disclaimer_agreed(self) -> None:
        self._disclaimer_accepted = True
        config = self._pending_config
        self._pending_config = None
        if config is None:
            self._show_candidate_home()
            return
        self._commit_session_start(config)

    def _on_disclaimer_back(self) -> None:
        self._pending_config = None
        if self._disclaimer_return_to == "recruiter":
            self._return_to_recruiter_flow()
            return
        self._show_candidate_home()

    def _request_session_start(
        self,
        config: pre_game.SessionConfig,
        *,
        return_to: str = "candidate",
    ) -> None:
        self._disclaimer_return_to = (
            "recruiter" if return_to == "recruiter" else "candidate"
        )
        if self._disclaimer_accepted:
            self._commit_session_start(config)
            return
        self._pending_config = config
        self._show_disclaimer()

    def _on_pre_game_done(self, config: pre_game.SessionConfig | None) -> None:
        if config is None:
            arcade.close_window()
            return
        return_to = "recruiter" if self._modifiers_from_recruiter else "candidate"
        self._modifiers_from_recruiter = False
        if return_to == "recruiter":
            view = getattr(self, "_current_view", None)
            if isinstance(view, pre_game.RecruiterConfigView):
                self._recruiter_generated_text = view.generated_seed_text
        self._request_session_start(config, return_to=return_to)

    def _commit_session_start(self, config: pre_game.SessionConfig) -> None:
        import main as game

        self._config = config
        game.session_num_rounds = config.num_rounds
        (
            game.session_base_seed,
            game.session_seed_source,
            game.session_use_adaptive_map,
        ) = resolve_candidate_play_seed(config.seed)
        game.session_modifiers = ModifierContext.from_ids(
            config.modifiers,
            session_base_seed=game.session_base_seed,
            round_index=1,
        )
        game.session_audience = config.audience
        game.session_candidate_label = config.candidate_label
        game.session_recruiter_seed_code = config.recruiter_seed_code
        game.session_started_at_utc = datetime.now(timezone.utc).replace(
            microsecond=0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        game.base_preset_id = config.preset
        self._base_profile = DifficultyProfile.for_menu_preset(config.preset)
        game.round_results = []
        self._outcomes = []
        self._round_index = 1

        print(
            f"Session seed: {game.session_base_seed} ({game.session_num_rounds} round(s), "
            f"source={game.session_seed_source}, adaptive_map={game.session_use_adaptive_map})"
        )
        game.car_diagnostics.begin_session(
            session_seed=game.session_base_seed,
            seed_source=game.session_seed_source,
            num_rounds=game.session_num_rounds,
        )
        print(f"Car diagnostics log: {game.car_diagnostics.path}")
        if game.ENABLE_PERF_PROFILE:
            game.perf_profiler.begin_session(
                session_seed=game.session_base_seed,
                seed_source=game.session_seed_source,
                num_rounds=game.session_num_rounds,
                preset=config.preset,
            )
            print(f"Perf profiling ON: log: {game.perf_profiler.jsonl_path}")
        self._begin_round()

    def _begin_round(self) -> None:
        import main as game

        profile = DifficultyProfile.for_round(
            self._base_profile, self._round_index - 1, game.session_num_rounds
        )
        game.start_round(self._round_index, profile, self._config.preset)
        hint = pre_game.round_intro_hint(
            profile,
            time_limit_s=int(game.ROUND_TIME_LIMIT),
            round_index=self._round_index,
        )
        self.show_view(
            pre_game.MessageView(
                title=f"Round {self._round_index} of {game.session_num_rounds}",
                subtitle=hint,
                accent=pre_game.ROUND_START_PROMPT,
                details=pre_game.ROUND_CONTROLS_HINT,
                modifiers=self._config.modifiers,
                audience=self._config.audience,
                on_complete=lambda _: self._start_round_play(),
            )
        )

    def _apply_frame_rate_for_modifiers(self) -> None:
        from pathwise.modifiers import lag

        period = lag.update_period_s()
        self.set_update_rate(period)
        if hasattr(self, "set_draw_rate"):
            self.set_draw_rate(period)

    def _restore_default_frame_rate(self) -> None:
        self.set_update_rate(1 / 60)
        if hasattr(self, "set_draw_rate"):
            self.set_draw_rate(1 / 60)

    def _start_round_play(self) -> None:
        import time

        import main as game

        # Route timer / signal clocks start when gameplay begins, not on the intro screen.
        game.start_time = time.time()
        game.sim_elapsed = 0.0
        game._sim_clock_last = game.start_time
        game.app_running = True
        self._apply_frame_rate_for_modifiers()
        self.show_view(GamePlayView(on_round_complete=self._on_round_done))

    def _on_round_done(self) -> None:
        import main as game

        self._restore_default_frame_rate()

        if not game.app_running:
            arcade.close_window()
            return

        outcome = game.round_results[-1]["outcome"] if game.round_results else "timeout"
        self._outcomes.append(outcome)

        if outcome == "trip":
            from pathwise.modifiers.rainy_roads import SLIP_TRIP_MESSAGE

            self.show_view(
                pre_game.MessageView(
                    title=pre_game.TRIP_NOTICE_TITLE,
                    subtitle=SLIP_TRIP_MESSAGE.capitalize()
                    if SLIP_TRIP_MESSAGE
                    else pre_game.round_outcome_label("trip"),
                    accent=pre_game.TRIP_NOTICE_ACCENT,
                    on_complete=lambda _: self._continue_after_round_outcome(),
                )
            )
            return

        self._continue_after_round_outcome()

    def _continue_after_round_outcome(self) -> None:
        import main as game

        if self._round_index < game.session_num_rounds:
            outcome = self._outcomes[-1] if self._outcomes else "timeout"
            label = pre_game.round_outcome_label(outcome)
            game.finalize_round_result()
            self.show_view(
                pre_game.MessageView(
                    title=f"Round {self._round_index} complete: {label}",
                    subtitle="Next round will be harder",
                    accent="Click or press any key to continue",
                    on_complete=lambda _: self._next_round(),
                )
            )
            return

        self._finish_session()

    def _next_round(self) -> None:
        self._round_index += 1
        self._begin_round()

    def _finish_session(self) -> None:
        import main as game

        if not game.round_results:
            arcade.close_window()
            return

        summary = " · ".join(
            f"R{i + 1}: {pre_game.round_outcome_label(o)}"
            for i, o in enumerate(self._outcomes)
        )
        subtitle = summary
        if game.session_base_seed is not None:
            subtitle += f"\nSession seed: {game.session_base_seed}"

        dashboard = game.save_session_log()
        print("Session complete:", {"rounds": self._outcomes, "dashboard": dashboard})
        try:
            self._notify_after_save(dashboard)
        except Exception:
            logger.warning("Recruiter notify failed after session save")

        last_label = pre_game.round_outcome_label(self._outcomes[-1])
        if game.session_num_rounds == 1:
            title = f"Round complete: {last_label}"
        else:
            title = f"All {game.session_num_rounds} rounds complete"

        self.show_view(
            pre_game.MessageView(
                title=title,
                subtitle=subtitle,
                accent="Open logs_dashboard.html for per-round replays",
                on_complete=lambda _: arcade.close_window(),
            )
        )

    def _notify_after_save(self, dashboard) -> None:
        import main as game
        from pathwise.recruiter_accounts import RecruiterRecord
        from pathwise.recruiter_notify import notify_recruiter_of_seed_use

        config = getattr(self, "_config", None)
        code = None
        label = None
        if config is not None:
            code = getattr(config, "recruiter_seed_code", None)
            label = getattr(config, "candidate_label", None)
        if not code:
            code = getattr(game, "session_recruiter_seed_code", None)
        if not label:
            label = getattr(game, "session_candidate_label", None)
        used_at = getattr(game, "session_started_at_utc", None) or ""
        completed = datetime.now(timezone.utc).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        record = getattr(self, "_recruiter_record", None)
        player_id = record.id if isinstance(record, RecruiterRecord) else None
        kwargs = {
            "recruiter_seed_code": code,
            "candidate_label": label,
            "used_at_utc": used_at,
            "completed_at_utc": completed,
            "dashboard_path": dashboard,
            "player_recruiter_id": player_id,
            "execute": getattr(self, "_recruiter_execute", None),
            "send": getattr(self, "_notify_send", None),
        }
        notify_fn = getattr(self, "_notify_recruiter", None)
        if notify_fn is not None:
            notify_fn(**kwargs)
            return
        notify_recruiter_of_seed_use(**kwargs)


def run(*, auto_close_seconds: float | None = None) -> None:
    window = PathwiseWindow(auto_close_seconds=auto_close_seconds)
    window.run()


if __name__ == "__main__":
    smoke_seconds = float(os.environ.get("PATHWISE_WINDOW_SMOKE_SECONDS", "0"))
    run(auto_close_seconds=smoke_seconds if smoke_seconds > 0 else None)
