"""Normalize legacy and split risk counters for session analytics."""


def normalize_risk_counts(session: dict) -> tuple[int, int, bool]:
    """
    Return (risky, reasonable, legacy_mode).

    legacy_mode=True reproduces pre-split scoring: all risks live in the legacy
    ``risk_events`` counter with no reasonable tier.
    """
    legacy_total = int(session.get("risk_events") or 0)
    has_split = "risky_risk_events" in session or "reasonable_risk_events" in session

    if not has_split:
        return legacy_total, 0, True

    risky = int(session.get("risky_risk_events") or 0)
    reasonable = int(session.get("reasonable_risk_events") or 0)

    # Split keys present but empty while legacy total is set (older finalize callers).
    if risky == 0 and reasonable == 0 and legacy_total > 0:
        return legacy_total, 0, True

    # Prefer explicit split fields when both exist; keep legacy total as risky-only.
    if legacy_total > 0 and risky + reasonable == 0:
        return legacy_total, 0, True

    return risky, reasonable, False


def reconcile_finalize_risks(
    risk_events: int,
    *,
    reasonable_risk_events=None,
    risky_risk_events=None,
) -> tuple[int, int, int]:
    """
    Backfill split counters for finalize().

    Returns (risk_events_out, reasonable_out, risky_out).
    """
    risk_events_out = int(risk_events or 0)
    split_provided = (
        reasonable_risk_events is not None or risky_risk_events is not None
    )
    if not split_provided:
        return risk_events_out, 0, risk_events_out

    reasonable_out = int(reasonable_risk_events or 0)
    risky_out = int(risky_risk_events or 0)
    if risky_out == 0 and reasonable_out == 0 and risk_events_out > 0:
        risky_out = risk_events_out
    if risk_events_out == 0 and risky_out > 0:
        risk_events_out = risky_out
    return risk_events_out, reasonable_out, risky_out
