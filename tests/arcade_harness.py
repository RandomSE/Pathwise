"""Shared Arcade window mocks for headless unit tests."""

from unittest.mock import MagicMock


def fake_arcade_window(*, width: int = 800, height: int = 600, closed: bool = False) -> MagicMock:
    window = MagicMock()
    window.width = width
    window.height = height
    window.closed = closed
    window.ctx = MagicMock()
    window.ctx.scissor = None
    return window
