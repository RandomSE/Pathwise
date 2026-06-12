"""Replay playback timing helpers shared by dashboard JS and tests."""

REPLAY_STEP_S = 1.0 / 12.0
MIN_PLAYBACK_GAP_S = REPLAY_STEP_S / 4
MAX_PLAYBACK_GAP_S = 1.5


def replay_frame_delay_seconds(
    current: dict,
    next_frame: dict,
    *,
    step_s: float = REPLAY_STEP_S,
) -> float:
    """
    Seconds to wait before showing the next stored replay frame.

    Uses sim-time delta between frames so wall-clock playback tracks round time.
    Gaps are capped so sparse decision-only captures do not freeze the UI for many
    seconds (densify_frames should keep gaps small; this is a safety net).
    """
    if current.get("t") is not None and next_frame.get("t") is not None:
        dt = float(next_frame["t"]) - float(current["t"])
        if dt > 0:
            return max(MIN_PLAYBACK_GAP_S, min(MAX_PLAYBACK_GAP_S, dt))
    return step_s
