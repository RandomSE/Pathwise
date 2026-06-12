"""Coverage for pathwise.arcade_loop."""

import unittest
from unittest.mock import MagicMock

from pathwise.arcade_loop import pump_frame


class TestPumpFrame(unittest.TestCase):
    def test_pumps_events_and_frame(self):
        window = MagicMock()
        window.closed = False
        pump_frame(window, 1 / 30)
        window.dispatch_events.assert_called_once()
        window._dispatch_frame.assert_called_once_with(1 / 30)

    def test_skips_closed_window(self):
        window = MagicMock()
        window.closed = True
        pump_frame(window)
        window.dispatch_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
