"""Session scoring facade. Hiring fields come from traits and role target similarity."""

from analytics.trait_scoring import score_session, score_session_log

__all__ = ["score_session", "score_session_log"]
