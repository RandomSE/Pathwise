"""Fixed render-quality policy (no adaptive downscaling in production)."""

from __future__ import annotations


class RenderBudget:
    """No-op stub — quality stays locked; env override remains in gameplay_framebuffer."""

    multiplier: float = 1.0

    def reset(self) -> None:
        self.multiplier = 1.0

    def note_frame_seconds(self, _seconds: float) -> None:
        return


_budget: RenderBudget | None = None


def shared_render_budget() -> RenderBudget:
    global _budget
    if _budget is None:
        _budget = RenderBudget()
    return _budget
