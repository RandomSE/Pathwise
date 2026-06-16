"""Simulation constants — re-exported from active GameTuning (see game_tuning.py)."""

from __future__ import annotations

from pathwise.game_tuning import DEFAULT_TUNING, install_tuning

# Bootstrap module namespace from default tuning.
install_tuning(DEFAULT_TUNING)

__all__ = list(DEFAULT_TUNING.export_scalars().keys())
