"""Session seed parsing and resolution (menu, PATHWISE_SEED env, random)."""

import os
import random

SEED_SOURCE_MENU = "menu"
SEED_SOURCE_ENV = "PATHWISE_SEED"
SEED_SOURCE_RANDOM = "random"


def parse_seed_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return int(cleaned) % (2**31)


def pathwise_seed_from_env() -> int | None:
    return parse_seed_value(os.environ.get("PATHWISE_SEED"))


def resolve_session_seed(
    menu_seed: int | None,
    rng: random.Random | None = None,
) -> tuple[int, str, bool]:
    """
    Return (session_seed, seed_source, use_adaptive_map).

    Menu seed wins over PATHWISE_SEED; env wins over random. Adaptive map tuning
    runs only when neither menu nor env fixed the seed.
    """
    env_seed = pathwise_seed_from_env()
    if menu_seed is not None:
        return menu_seed, SEED_SOURCE_MENU, False
    if env_seed is not None:
        return env_seed, SEED_SOURCE_ENV, False
    roll = rng.randint if rng is not None else random.randint
    return roll(0, 2**31 - 1), SEED_SOURCE_RANDOM, True
