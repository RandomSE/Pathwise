"""Suite isolation: skip unused map bakes, reset game globals, cheap test hasher."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config):
    os.environ.setdefault("PATHWISE_SKIP_MAP_BAKE", "1")
    try:
        from argon2 import PasswordHasher

        from pathwise import recruiter_accounts

        recruiter_accounts._PASSWORD_HASHER = PasswordHasher(
            time_cost=1,
            memory_cost=8,
            parallelism=1,
        )
    except Exception:
        pass


def _reset_game_globals() -> None:
    try:
        import main as game
    except Exception:
        return
    game.round_active = False
    game.app_running = True
    game.session_modifiers = None
    game.session_audience = "candidate"
    game.ENABLE_PERF_PROFILE = False
    game.ENABLE_CAR_DIAGNOSTICS = False
    game.sim_elapsed = 0.0
    game._sim_clock_last = None
    try:
        from pathwise.modifiers.registry import ModifierContext
        from pathwise.modifiers import (
            hidden,
            highway,
            high_speed,
            lag,
            lawless,
            old,
            rainy_roads,
            time_pressure,
        )

        empty = ModifierContext(frozenset())
        rainy_roads.install_for_round(empty)
        highway.install_for_round(empty)
        hidden.install_for_round(empty)
        high_speed.install_for_round(empty)
        lag.install_for_round(empty)
        lawless.install_for_round(empty)
        old.install_for_round(empty)
        time_pressure.install_for_round(empty)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _pathwise_test_isolation(request):
    if request.node.get_closest_marker("needs_map_bake") is None:
        os.environ["PATHWISE_SKIP_MAP_BAKE"] = "1"
    else:
        os.environ.pop("PATHWISE_SKIP_MAP_BAKE", None)
    _reset_game_globals()
    yield
    _reset_game_globals()
    os.environ["PATHWISE_SKIP_MAP_BAKE"] = "1"
