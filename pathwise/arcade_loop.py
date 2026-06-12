"""Arcade 3.3+ manual frame pump for blocking menu loops."""

from __future__ import annotations

import arcade


def pump_frame(window: arcade.Window, delta_time: float = 1 / 60) -> None:
    """Process one frame: input events, on_update, and on_draw for the active view."""
    if window.closed:
        return
    window.dispatch_events()
    window._dispatch_frame(delta_time)
