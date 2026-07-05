"""Session seed parsing and resolution (menu, PATHWISE_SEED env, random)."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Literal

SEED_SOURCE_MENU = "menu"
SEED_SOURCE_ENV = "PATHWISE_SEED"
SEED_SOURCE_RANDOM = "random"

SeedInputState = Literal["empty", "valid", "invalid"]

RECRUITER_SEED_VERSION = 8
ENCODED_SEED_LEN = 10
MAP_SEED_MOD = 10_000_000

_PRESET_ENCODE = {"easy": 0, "normal": 1, "hard": 2}
_PRESET_DECODE = {0: "easy", 1: "normal", 2: "hard"}
_RECRUITER_MIN_ROUNDS = 1
_RECRUITER_MAX_ROUNDS = 5


@dataclass(frozen=True)
class RecruiterSeedPayload:
    map_seed: int
    preset: str
    num_rounds: int


def parse_seed_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return int(cleaned) % (2**31)


def classify_seed_input(text: str) -> SeedInputState:
    cleaned = str(text).strip()
    if not cleaned:
        return "empty"
    if cleaned.isdigit():
        return "valid"
    return "invalid"


def encode_recruiter_seed(map_seed: int, preset: str, num_rounds: int) -> str:
    """Pack map seed, difficulty preset, and round count into a 10-digit candidate code."""
    if preset not in _PRESET_ENCODE:
        raise ValueError(f"unknown preset: {preset}")
    if not (_RECRUITER_MIN_ROUNDS <= num_rounds <= _RECRUITER_MAX_ROUNDS):
        raise ValueError(f"num_rounds must be {_RECRUITER_MIN_ROUNDS}-{_RECRUITER_MAX_ROUNDS}")
    body = int(map_seed) % MAP_SEED_MOD
    preset_id = _PRESET_ENCODE[preset]
    return f"{RECRUITER_SEED_VERSION}{num_rounds}{preset_id}{body:07d}"


def decode_recruiter_seed(text: str) -> RecruiterSeedPayload | None:
    cleaned = str(text).strip()
    if len(cleaned) != ENCODED_SEED_LEN or not cleaned.isdigit():
        return None
    if cleaned[0] != str(RECRUITER_SEED_VERSION):
        return None
    num_rounds = int(cleaned[1])
    preset_id = int(cleaned[2])
    if preset_id not in _PRESET_DECODE:
        return None
    if not (_RECRUITER_MIN_ROUNDS <= num_rounds <= _RECRUITER_MAX_ROUNDS):
        return None
    map_seed = int(cleaned[3:])
    return RecruiterSeedPayload(
        map_seed=map_seed,
        preset=_PRESET_DECODE[preset_id],
        num_rounds=num_rounds,
    )


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


def resolve_candidate_play_seed(
    menu_seed: int | None,
    rng: random.Random | None = None,
) -> tuple[int, str, bool]:
    """
    Candidate quick-play seed resolution.

    Uses the menu seed when set; otherwise rolls random. Does not fall back to
    PATHWISE_SEED so recruiter env pinning does not affect candidate random play.
    """
    if menu_seed is not None:
        return menu_seed, SEED_SOURCE_MENU, False
    roll = rng.randint if rng is not None else random.randint
    return roll(0, 2**31 - 1), SEED_SOURCE_RANDOM, True
