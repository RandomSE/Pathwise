"""Session seed parsing and resolution (menu, PATHWISE_SEED env, random)."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Literal

from pathwise.modifiers.registry import (
    is_valid_modifier_mask,
    modifier_ids_from_mask,
    modifier_mask_from_ids,
)

SEED_SOURCE_MENU = "menu"
SEED_SOURCE_ENV = "PATHWISE_SEED"
SEED_SOURCE_RANDOM = "random"

SeedInputState = Literal["empty", "valid", "invalid"]

RECRUITER_SEED_VERSION = 9
RECRUITER_SEED_VERSION_LEGACY = 8
ENCODED_SEED_LEN = 10
# v9 legacy: 3-digit modifier mask (0-999). New encodes use 4-digit masks.
ENCODED_SEED_LEN_V9 = 12
ENCODED_SEED_LEN_V9_WIDE = 13
MAP_SEED_MOD = 10_000_000
MAP_SEED_MOD_V9 = 1_000_000

_PRESET_ENCODE = {"easy": 0, "normal": 1, "hard": 2}
_PRESET_DECODE = {0: "easy", 1: "normal", 2: "hard"}
_RECRUITER_MIN_ROUNDS = 1
_RECRUITER_MAX_ROUNDS = 5


@dataclass(frozen=True)
class RecruiterSeedPayload:
    map_seed: int
    preset: str
    num_rounds: int
    modifiers: frozenset[str] = frozenset()


def parse_seed_value(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = str(raw).strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return int(cleaned) % (2**31)


def classify_seed_input(text: str) -> SeedInputState:
    cleaned = "".join(str(text).split())
    if not cleaned:
        return "empty"
    if not cleaned.isdigit():
        return "invalid"
    if len(cleaned) in (ENCODED_SEED_LEN, ENCODED_SEED_LEN_V9, ENCODED_SEED_LEN_V9_WIDE):
        return "valid" if decode_recruiter_seed(cleaned) is not None else "invalid"
    return "valid"


def encode_recruiter_seed(
    map_seed: int,
    preset: str,
    num_rounds: int,
    *,
    modifiers: frozenset[str] | tuple[str, ...] | list[str] = (),
    version: int = RECRUITER_SEED_VERSION,
) -> str:
    """Pack map seed, preset, rounds, and optional modifiers into a recruiter code."""
    if preset not in _PRESET_ENCODE:
        raise ValueError(f"unknown preset: {preset}")
    if not (_RECRUITER_MIN_ROUNDS <= num_rounds <= _RECRUITER_MAX_ROUNDS):
        raise ValueError(f"num_rounds must be {_RECRUITER_MIN_ROUNDS}-{_RECRUITER_MAX_ROUNDS}")
    if version == RECRUITER_SEED_VERSION_LEGACY:
        body = int(map_seed) % MAP_SEED_MOD
        preset_id = _PRESET_ENCODE[preset]
        return f"{RECRUITER_SEED_VERSION_LEGACY}{num_rounds}{preset_id}{body:07d}"
    if version != RECRUITER_SEED_VERSION:
        raise ValueError(f"unsupported seed version: {version}")
    body = int(map_seed) % MAP_SEED_MOD_V9
    preset_id = _PRESET_ENCODE[preset]
    mask = modifier_mask_from_ids(modifiers)
    # 4-digit mask so bits such as Old (1024) and full stacks above 999 fit.
    return f"{RECRUITER_SEED_VERSION}{num_rounds}{preset_id}{mask:04d}{body:06d}"


def _decode_v8(cleaned: str) -> RecruiterSeedPayload | None:
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
        modifiers=frozenset(),
    )


def _decode_v9_mask(cleaned: str, *, mask_digits: int) -> RecruiterSeedPayload | None:
    num_rounds = int(cleaned[1])
    preset_id = int(cleaned[2])
    mask_end = 3 + mask_digits
    mask = int(cleaned[3:mask_end])
    if preset_id not in _PRESET_DECODE:
        return None
    if not (_RECRUITER_MIN_ROUNDS <= num_rounds <= _RECRUITER_MAX_ROUNDS):
        return None
    if not is_valid_modifier_mask(mask):
        return None
    map_seed = int(cleaned[mask_end:])
    return RecruiterSeedPayload(
        map_seed=map_seed,
        preset=_PRESET_DECODE[preset_id],
        num_rounds=num_rounds,
        modifiers=modifier_ids_from_mask(mask),
    )


def decode_recruiter_seed(text: str) -> RecruiterSeedPayload | None:
    cleaned = str(text).strip()
    if not cleaned.isdigit():
        return None
    if len(cleaned) == ENCODED_SEED_LEN and cleaned[0] == str(RECRUITER_SEED_VERSION_LEGACY):
        return _decode_v8(cleaned)
    if cleaned[0] != str(RECRUITER_SEED_VERSION):
        return None
    if len(cleaned) == ENCODED_SEED_LEN_V9:
        return _decode_v9_mask(cleaned, mask_digits=3)
    if len(cleaned) == ENCODED_SEED_LEN_V9_WIDE:
        return _decode_v9_mask(cleaned, mask_digits=4)
    return None


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
