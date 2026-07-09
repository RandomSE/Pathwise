"""Rolling frame-time tracker for on-screen FPS display."""

from __future__ import annotations


class FpsTracker:
    """Smoothed FPS from wall-clock intervals between presented frames."""

    def __init__(self, *, max_samples: int = 45) -> None:
        self._max_samples = max(1, max_samples)
        self._intervals: list[float] = []
        self._smoothed_fps = 60.0
        self._last_tick: float | None = None

    def note_present(self, now: float) -> None:
        if self._last_tick is not None:
            interval = now - self._last_tick
            if interval > 0:
                self._intervals.append(interval)
                if len(self._intervals) > self._max_samples:
                    self._intervals.pop(0)
                avg = sum(self._intervals) / len(self._intervals)
                self._smoothed_fps = 1.0 / avg
        self._last_tick = now

    @property
    def smoothed_fps(self) -> float:
        return self._smoothed_fps

    def hud_line(self) -> str:
        return f"FPS: {self._smoothed_fps:.0f}"
