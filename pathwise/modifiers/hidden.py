"""Hidden modifier: conceal run info from candidates.

When the audience is the candidate, the in-round HUD is suppressed and
pre-round modifier lists show only Hidden (other modifiers stay secret).
Recruiter playthroughs still see full HUD and modifier details.
"""

from __future__ import annotations

from typing import Iterable

from pathwise.modifiers.registry import ModifierContext

_ctx: ModifierContext | None = None
_active = False
_audience = "candidate"


def install_for_round(
    ctx: ModifierContext, *, audience: str = "candidate"
) -> None:
    global _ctx, _active, _audience
    _ctx = ctx
    _active = ctx.has("hidden")
    _audience = "recruiter" if audience == "recruiter" else "candidate"


def is_active() -> bool:
    return _active


def suppress_hud() -> bool:
    """True when candidate HUD chrome should be blanked."""
    return _active and _audience == "candidate"


def visible_modifiers(
    modifiers: Iterable[str], *, audience: str = "candidate"
) -> frozenset[str]:
    """Modifiers the given audience may see before the round."""
    ids = frozenset(modifiers)
    if "hidden" not in ids:
        return ids
    if audience == "recruiter":
        return ids
    return frozenset({"hidden"})


def hud_line() -> str | None:
    # Intentionally never shown in-round under Hidden for candidates.
    return None
