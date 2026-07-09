"""Arcade window hosting Pathwise menus and gameplay."""

from __future__ import annotations

import os
from collections.abc import Callable

import arcade

from . import commonUtils
from . import pre_game
from .input_keys import KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_UP, KeyState
from map_generation.difficulty import DifficultyProfile
from .session_seed import resolve_candidate_play_seed

WIDTH = commonUtils.WIDTH
HEIGHT = commonUtils.HEIGHT

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

        if not game.round_active or not game.app_running:
            if self._on_round_complete and not self._round_complete_fired:
                self._round_complete_fired = True
                self._on_round_complete()
            return
        self._draw_state = game.update_round_frame(self.keys)

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
        vsync = os.environ.get("PATHWISE_VSYNC", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        super().__init__(
            WIDTH,
            HEIGHT,
            "Pathwise MVP",
            update_rate=1 / 60,
            draw_rate=1 / 60,
            vsync=vsync,
            fullscreen=use_fullscreen,
        )
        self._auto_close_seconds = auto_close_seconds
        self._elapsed = 0.0
        self._smoke_mode = auto_close_seconds is not None
        self._config: pre_game.SessionConfig | None = None
        self._base_profile: DifficultyProfile | None = None
        self._round_index = 1
        self._outcomes: list[str] = []
        self._seed_text = ""

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

    def _on_open_recruiter(self, seed_text: str) -> None:
        self._seed_text = seed_text
        self.show_view(
            pre_game.RecruiterConfigView(
                generated_seed_text=self._seed_text,
                on_back=self._on_recruiter_back,
                on_start=self._on_recruiter_start,
            )
        )

    def _on_recruiter_back(self, seed_text: str) -> None:
        self._seed_text = seed_text
        self._show_candidate_home()

    def _on_recruiter_start(self, config: pre_game.SessionConfig) -> None:
        self._on_pre_game_done(config)

    def on_draw(self) -> None:
        # Do not clear when a View is active — its on_draw already clears and paints.
        # Clearing here was wiping the menu/game after the view drew (white screen).
        if self.current_view is None:
            self.clear()

    def on_update(self, delta_time: float) -> None:
        if self._auto_close_seconds is None:
            return
        self._elapsed += delta_time
        if self._elapsed >= self._auto_close_seconds:
            arcade.close_window()

    def _on_pre_game_done(self, config: pre_game.SessionConfig | None) -> None:
        if config is None:
            arcade.close_window()
            return

        import main as game

        self._config = config
        game.session_num_rounds = config.num_rounds
        (
            game.session_base_seed,
            game.session_seed_source,
            game.session_use_adaptive_map,
        ) = resolve_candidate_play_seed(config.seed)
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
            print(f"Perf profiling ON — log: {game.perf_profiler.jsonl_path}")
        self._begin_round()

    def _begin_round(self) -> None:
        import main as game

        profile = DifficultyProfile.for_round(
            self._base_profile, self._round_index - 1, game.session_num_rounds
        )
        game.start_round(self._round_index, profile, self._config.preset)
        hint = (
            f"~{profile.min_crossings}-{profile.max_crossings} roads · "
            f"{profile.target_play_time_s}s · denser traffic"
        )
        if self._round_index > 1:
            hint += f" (+{int(profile.round_escalation * 100)}% vs round 1)"
        self.show_view(
            pre_game.MessageView(
                title=f"Round {self._round_index} of {game.session_num_rounds}",
                subtitle=hint,
                accent=pre_game.ROUND_START_PROMPT,
                details=pre_game.ROUND_CONTROLS_HINT,
                on_complete=lambda _: self._start_round_play(),
            )
        )

    def _start_round_play(self) -> None:
        import main as game

        game.app_running = True
        self.show_view(GamePlayView(on_round_complete=self._on_round_done))

    def _on_round_done(self) -> None:
        import main as game

        if not game.app_running:
            arcade.close_window()
            return

        outcome = game.round_results[-1]["outcome"] if game.round_results else "timeout"
        self._outcomes.append(outcome)

        if self._round_index < game.session_num_rounds:
            labels = {
                "success": "Goal reached",
                "collision": "Collision",
                "timeout": "Time expired",
            }
            label = labels.get(outcome, outcome)
            self.show_view(
                pre_game.MessageView(
                    title=f"Round {self._round_index} complete — {label}",
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

        if game.round_results:
            dashboard = game.save_session_log()
            print("Session complete:", {"rounds": self._outcomes, "dashboard": dashboard})
            summary = " · ".join(f"R{i + 1}: {o}" for i, o in enumerate(self._outcomes))
            subtitle = summary
            if game.session_base_seed is not None:
                subtitle += f"\nSession seed: {game.session_base_seed}"
            self.show_view(
                pre_game.MessageView(
                    title=f"All {game.session_num_rounds} rounds complete",
                    subtitle=subtitle,
                    accent="Open logs_dashboard.html for per-round replays",
                    on_complete=lambda _: arcade.close_window(),
                )
            )
        else:
            arcade.close_window()


def run(*, auto_close_seconds: float | None = None) -> None:
    window = PathwiseWindow(auto_close_seconds=auto_close_seconds)
    window.run()


if __name__ == "__main__":
    smoke_seconds = float(os.environ.get("PATHWISE_WINDOW_SMOKE_SECONDS", "0"))
    run(auto_close_seconds=smoke_seconds if smoke_seconds > 0 else None)
