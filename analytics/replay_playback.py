"""Replay playback timing helpers shared by dashboard JS and tests."""

from analytics.frame_recorder import (
    FIXED_SAMPLE_INTERVAL_FAST_S,
    FIXED_SAMPLE_INTERVAL_SLOW_S,
)

REPLAY_STEP_S = FIXED_SAMPLE_INTERVAL_FAST_S
MIN_PLAYBACK_GAP_S = min(
    FIXED_SAMPLE_INTERVAL_FAST_S, FIXED_SAMPLE_INTERVAL_SLOW_S
) / 4.0
MAX_PLAYBACK_GAP_S = 1.5


def replay_step_for_session(session: dict | None) -> float:
    """Pick a playback step that matches recorded frame spacing when available."""
    if not session:
        return REPLAY_STEP_S
    meta = session.get("replay_capture") or {}
    for key in ("median_frame_gap_s", "sample_interval_final_s"):
        value = meta.get(key)
        if value is not None and float(value) > 0:
            return float(value)
    return REPLAY_STEP_S


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
