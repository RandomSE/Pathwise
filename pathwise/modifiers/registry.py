"""Modifier registry: IDs, metadata, bitmask helpers, session context."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

MODIFIER_BIT_RAINY_ROADS = 1
MODIFIER_BIT_IGNORED = 2
MODIFIER_BIT_UNTRUSTWORTHY = 4
MODIFIER_BIT_LAWLESS = 8
MODIFIER_BIT_TIME_PRESSURE = 16
MODIFIER_BIT_HIGHWAY = 32
MODIFIER_BIT_VARIABLE_SPEED_ZONES = 64
MODIFIER_BIT_EXPOSURE = 128
MODIFIER_BIT_HIGH_SPEED = 256
MODIFIER_BIT_LAG = 512
MODIFIER_BIT_OLD = 1024
MODIFIER_BIT_HIDDEN = 2048

_MODIFIER_BITS: dict[str, int] = {
    "rainy_roads": MODIFIER_BIT_RAINY_ROADS,
    "ignored": MODIFIER_BIT_IGNORED,
    "untrustworthy": MODIFIER_BIT_UNTRUSTWORTHY,
    "lawless": MODIFIER_BIT_LAWLESS,
    "time_pressure": MODIFIER_BIT_TIME_PRESSURE,
    "highway": MODIFIER_BIT_HIGHWAY,
    "variable_speed_zones": MODIFIER_BIT_VARIABLE_SPEED_ZONES,
    "exposure": MODIFIER_BIT_EXPOSURE,
    "high_speed": MODIFIER_BIT_HIGH_SPEED,
    "lag": MODIFIER_BIT_LAG,
    "old": MODIFIER_BIT_OLD,
    "hidden": MODIFIER_BIT_HIDDEN,
}

_MODIFIER_BY_BIT: dict[int, str] = {bit: mid for mid, bit in _MODIFIER_BITS.items()}

# Selecting one disables the other in the recruiter UI.
MODIFIER_CONFLICTS: dict[str, frozenset[str]] = {
    "highway": frozenset({"time_pressure", "exposure"}),
    "time_pressure": frozenset({"highway"}),
    "exposure": frozenset({"highway"}),
}

MODIFIER_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "rainy_roads",
        "title": "Rainy roads",
        "description": (
            "Wet pavement: cars brake more slowly, some stop past crosswalk lines, "
            "sprinting can make you slip (5% chance per second of sprinting, "
            "rising by 0.1% each second up to 15%), "
            "and route time is extended to 1.5x. "
            "Combined with Time pressure: timer starts at 20 seconds and crossing "
            "bonuses are 75% larger."
        ),
    },
    {
        "id": "ignored",
        "title": "Ignored",
        "description": (
            "Cars ignore your presence entirely: they never slow, stop, \nor honk for you, "
            "only for red lights and normal traffic rules. They can still collide with you."
        ),
    },
    {
        "id": "untrustworthy",
        "title": "Untrustworthy",
        "description": (
            "Some cars do not follow the rules: they may run red lights, and those "
            "same cars will not try to avoid you. Collisions still count."
        ),
    },
    {
        "id": "lawless",
        "title": "Lawless",
        "description": (
            "Crosswalks still exist, but traffic lights do not. The first painted "
            "crossing you enter counts as your crossing commitment; cars may still "
            "yield while you are committed unless other modifiers say otherwise. "
            "Collisions still count."
        ),
    },
    {
        "id": "time_pressure",
        "title": "Time pressure",
        "description": (
            "The route timer starts at 10 seconds. Crossing a road adds time: "
            "least for an unsafe road crossing, more for an unsafe crosswalk, "
            "most for a safe crosswalk (gains are 25% larger than the base "
            "table). Remaining time cannot exceed twice the largest one-crossing "
            "bonus, so you cannot stack an endless bank. Harder difficulty "
            "grants larger bonuses so denser routes stay finishable. "
            "Combined with Rainy roads: timer starts at 20 seconds and crossing "
            "bonuses are 75% larger on top of the 25% gain. Cannot be combined "
            "with Highway."
        ),
    },
    {
        "id": "highway",
        "title": "Highway",
        "description": (
            "One wide, busy multi-lane road with no painted crosswalks and no "
            "traffic lights. Crossing is always unprotected. Traffic is heavy "
            "(dozens of cars) at normal city speed; cars do not brake for you "
            "but still honk. With Rainy roads, highway traffic is an extra "
            "third slower. Width and density scale with difficulty. "
            "Cannot be combined with Time pressure or Exposure."
        ),
    },
    {
        "id": "variable_speed_zones",
        "title": "Variable speed zones",
        "description": (
            "Traffic speed changes by zone. Different stretches of road "
            "(including Highway sections) run slower or faster. Zones are "
            "fixed for the session seed."
        ),
    },
    {
        "id": "exposure",
        "title": "Exposure",
        "description": (
            "You have a limited cumulative time on asphalt: half of the "
            "route timer. Hesitating mid-crossing or retreating burns the "
            "budget and can end the round like a timeout. With Time "
            "pressure, each crossing bonus also adds half of that gain "
            "to your exposure budget. Cannot be combined with Highway."
        ),
    },
    {
        "id": "high_speed",
        "title": "High speed",
        "description": (
            "Everything runs twice as fast versus wall clock: player and "
            "cars, the route timer, traffic lights, traffic spawns, and "
            "other timed effects. On Highway, car cruise is 1.5x instead "
            "of 2x so gaps stay human-readable. Stacks multiplicatively "
            "with other speed modifiers."
        ),
    },
    {
        "id": "lag",
        "title": "Lag",
        "description": (
            "Presentation is capped at 10 FPS. Physics and the route timer "
            "still follow wall clock, so a 60 second round stays 60 seconds "
            "of real time (not a 10 second sprint)."
        ),
    },
    {
        "id": "old",
        "title": "Old",
        "description": (
            "You move at half speed. Route time and time gains (including "
            "Time pressure crossing bonuses) are doubled; with Rainy roads "
            "the route clock is 3x base (1.5x rain * 2x old). Combined with "
            "Rainy roads, tripping while sprinting ends the round."
        ),
    },
    {
        "id": "hidden",
        "title": "Hidden",
        "description": (
            "For candidates, the in-round HUD (time remaining and status "
            "lines) is hidden, and the pre-round modifier list only reveals "
            "Hidden itself. Recruiters still see full details when they play."
        ),
    },
)


def available_modifier_ids() -> tuple[str, ...]:
    return tuple(entry["id"] for entry in MODIFIER_CATALOG)


def modifier_conflicts_with(modifier_id: str, selected: Iterable[str]) -> frozenset[str]:
    """Return selected modifier IDs that conflict with modifier_id."""
    blocked = MODIFIER_CONFLICTS.get(modifier_id, frozenset())
    return frozenset(selected) & blocked


def modifier_is_blocked(modifier_id: str, selected: Iterable[str]) -> bool:
    """True when modifier_id cannot be added because a conflict is already selected."""
    selected_set = frozenset(selected)
    if modifier_id in selected_set:
        return False
    return bool(modifier_conflicts_with(modifier_id, selected_set))


def modifier_metadata(modifier_id: str) -> dict[str, str] | None:
    for entry in MODIFIER_CATALOG:
        if entry["id"] == modifier_id:
            return dict(entry)
    return None


def modifier_mask_from_ids(modifier_ids: Iterable[str]) -> int:
    mask = 0
    for modifier_id in modifier_ids:
        bit = _MODIFIER_BITS.get(modifier_id)
        if bit is None:
            raise ValueError(f"unknown modifier: {modifier_id}")
        mask |= bit
    return mask


def modifier_ids_from_mask(mask: int) -> frozenset[str]:
    active: set[str] = set()
    for bit, modifier_id in _MODIFIER_BY_BIT.items():
        if mask & bit:
            active.add(modifier_id)
    return frozenset(active)


def is_valid_modifier_mask(mask: int) -> bool:
    if mask < 0 or mask > 9999:
        return False
    known = sum(_MODIFIER_BITS.values())
    if (mask & ~known) != 0:
        return False
    ids = modifier_ids_from_mask(mask)
    for modifier_id in ids:
        if modifier_conflicts_with(modifier_id, ids):
            return False
    return True


@dataclass(frozen=True)
class ModifierContext:
    active: frozenset[str]
    session_base_seed: int = 0
    round_index: int = 1

    @classmethod
    def from_ids(
        cls,
        modifier_ids: Iterable[str],
        *,
        session_base_seed: int = 0,
        round_index: int = 1,
    ) -> ModifierContext:
        return cls(
            active=frozenset(modifier_ids),
            session_base_seed=int(session_base_seed),
            round_index=int(round_index),
        )

    def has(self, modifier_id: str) -> bool:
        return modifier_id in self.active

    def rng(self, salt: int, *parts: int) -> random.Random:
        mix = int(self.session_base_seed) & 0x7FFFFFFF
        mix ^= int(self.round_index) * 9973
        mix ^= int(salt) * 2654435761
        for part in parts:
            mix ^= int(part) * 1315423911
            mix &= 0x7FFFFFFF
        return random.Random(mix)
