"""Versioned face-validity register for in-game Pathwise traits.

This is an operational-definition register, not a validation study.
Construct, convergent, and criterion validity remain unclaimed.
"""

from __future__ import annotations

VALIDITY_REGISTER_VERSION = "1"

_NOT_EXTERNAL = (
    "Not DOSPERT.",
    "Not Big Five.",
    "Not a clinical scale.",
    "Not a job-performance predictor.",
)


def _dimension(
    *,
    construct_label: str,
    operational_definition: str,
    inclusion: str,
    exclusion: str,
    known_confounds: tuple[str, ...],
    is_not: tuple[str, ...],
) -> dict:
    return {
        "construct_label": construct_label,
        "operational_definition": operational_definition,
        "inclusion": inclusion,
        "exclusion": exclusion,
        "known_confounds": list(known_confounds),
        "is_not": list(is_not),
    }


DIMENSIONS = {
    "risk_propensity": _dimension(
        construct_label="In-game risk propensity",
        operational_definition=(
            "Rate of logged risky_risk_events, reasonable_risk_events, and "
            "cross_on_red actions per observed second in this Pathwise session. "
            "Formula: 50 + 400*(risky/duration) + 80*(reasonable/duration) + "
            "220*(red_crosses/duration), clamped to 0-100."
        ),
        inclusion=(
            "Sessions with duration_s >= 1.0 or at least one risky, reasonable, "
            "or red-cross event."
        ),
        exclusion=(
            "Empty sessions with no duration and no risk or red-cross events "
            "are FLAG_INSUFFICIENT, not a fake 50."
        ),
        known_confounds=(
            "Game literacy (knowing which gaps are safe).",
            "Visual time-to-arrival reading of cars.",
            "Modifier effects (highway, lawless, time_pressure, lag, old).",
            "Frustration after a near miss.",
            "Map density and spawn luck.",
        ),
        is_not=_NOT_EXTERNAL,
    ),
    "decision_tempo": _dimension(
        construct_label="In-game decision tempo",
        operational_definition=(
            "Go/no-go speed after the player has already arrived at the curb. "
            "Primary item is crossing_attempts[].commit_latency_s (curb arrival "
            "to crossing). If commit_latency_s is missing, a residual "
            "commit_time_s minus motor/path travel may be used "
            "(source commit_latency_residual). Raw approach-to-cross "
            "commit_time_s is not scored as cognitive tempo. Mapping uses "
            "tempo_from_commit_s on the latency, 100 = fast go, 0 = slow go."
        ),
        inclusion=(
            "Crossing attempts with commit_latency_s, or with enough "
            "approach_travel_s / approach_path_px to form a residual."
        ),
        exclusion=(
            "Raw commit_time_s alone, and quick/slow bins derived only from "
            "approach-to-cross time, are excluded. No latency data is "
            "FLAG_INSUFFICIENT, not a fake 50."
        ),
        known_confounds=(
            "Motor speed if curb arrival was never logged.",
            "Visual TTA and light-change waiting (a legal wait is not tempo).",
            "Input lag modifier.",
            "old / rainy_roads movement penalties.",
            "Game literacy of when a gap is crossable.",
        ),
        is_not=_NOT_EXTERNAL + ("Not a personality 'decisiveness' construct.",),
    ),
    "deliberation_depth": _dimension(
        construct_label="In-game deliberation depth",
        operational_definition=(
            "Pause time and pause count at crossings from summary."
            "total_hesitation_s and hesitation_count. Formula: 50 + "
            "12*(hesitation_s/max(crossings,1)) + 6*hesitation_count, "
            "clamped to 0-100. Freezing is not tempo."
        ),
        inclusion=(
            "Sessions with at least one crossing, hesitation event, or "
            "duration_s >= 1.0."
        ),
        exclusion=(
            "Commit latency and risk events are not mixed into this score."
        ),
        known_confounds=(
            "Motor stun (old, rain slip).",
            "Waiting for a green light (rule-following, not deliberation).",
            "Frustration pauses.",
            "time_pressure shrinking available pause time.",
        ),
        is_not=_NOT_EXTERNAL + ("Not Need for Cognition.",),
    ),
    "rule_adherence": _dimension(
        construct_label="In-game rule adherence",
        operational_definition=(
            "Green vs red crossing mix from decision_sequence actions "
            "cross_on_green and cross_on_red. Score = 100 * green/(green+red), "
            "plus +8 when the session is long enough, has crossings, and has "
            "zero risky events and zero red crosses."
        ),
        inclusion="At least one cross_on_green or cross_on_red action.",
        exclusion=(
            "Sessions with no light-tagged crossings are FLAG_INSUFFICIENT. "
            "Lawless/unsignalized rounds remove the light contrast."
        ),
        known_confounds=(
            "lawless modifier (signals off).",
            "Visual TTA and map literacy.",
            "Frustration after being blocked.",
            "time_pressure bonus incentives.",
        ),
        is_not=_NOT_EXTERNAL + ("Not conscientiousness.",),
    ),
    "adaptive_planning": _dimension(
        construct_label="In-game adaptive planning",
        operational_definition=(
            "Replanning quality after backtrack actions: recovered if a later "
            "advance/commit occurs, else failed. Score starts at 50, +18 per "
            "recovered replan, -14 per failed replan, +12 on success, -10 on "
            "collision."
        ),
        inclusion=(
            "At least one backtrack (sequence or summary) or a success/collision "
            "outcome."
        ),
        exclusion=(
            "Unknown outcome with no backtracks is FLAG_INSUFFICIENT."
        ),
        known_confounds=(
            "Map topology forcing detours.",
            "Collision that ends the round before a replan.",
            "Modifier chaos (highway, lawless).",
            "Game literacy of legal paths.",
        ),
        is_not=_NOT_EXTERNAL + ("Not a planning construct from psychometrics.",),
    ),
    "composure": _dimension(
        construct_label="In-game composure",
        operational_definition=(
            "Within-round recovery speed after backtrack or risk_event to the "
            "next advance/commit, using decision_sequence timestamps. "
            "0.4s recovery maps to 100; 8.0s maps to 0. Between-round variance "
            "of other traits is reliability, not composure."
        ),
        inclusion=(
            "At least one backtrack or risk_event with usable timestamps and "
            "a later advance/commit."
        ),
        exclusion=(
            "Missing timestamps, no recovery follow-up, and between-round "
            "trait variance (task-impure) are excluded from this score."
        ),
        known_confounds=(
            "Motor stun and lag.",
            "Frustration after a hit.",
            "Round-ending collision cutting recovery short.",
            "Modifier effects on movement speed.",
        ),
        is_not=_NOT_EXTERNAL + ("Not a clinical affect scale.",),
    ),
}

VALIDITY_REGISTER = {
    "version": VALIDITY_REGISTER_VERSION,
    "claim_level": "face_validity_only",
    "construct_validity": False,
    "convergent_validity": False,
    "criterion_validity": False,
    "predicts_job_performance": False,
    "authorized_for_employment_decisions": False,
    "population": "in_game_pathwise_session",
    "dimensions": DIMENSIONS,
    "summary": (
        "Scores describe behavior in this Pathwise session using the versioned "
        "operational definitions in this register. They have not been shown to "
        "correlate with validated trait scales or to predict on-the-job "
        "performance. Internal reliability may be computed from multi-round "
        "session payloads; that is not construct validity."
    ),
}

EMPLOYMENT_BANNER = (
    "This tool is not authorized for employment decisions until a fairness "
    "review on real applicants exists."
)

MODIFIER_FACTOR_NOTE = (
    "Session modifiers (lag, old, time_pressure, highway, lawless, rainy_roads, "
    "and others) are experimental factors, not demographic proxies. They must "
    "be recorded on the session so they are not silently confounded with traits."
)


def validity_payload(*, internal_reliability: dict | None = None) -> dict:
    payload = {
        "claim_level": VALIDITY_REGISTER["claim_level"],
        "construct_validity": False,
        "convergent_validity": False,
        "criterion_validity": False,
        "predicts_job_performance": False,
        "authorized_for_employment_decisions": False,
        "population": VALIDITY_REGISTER["population"],
        "summary": VALIDITY_REGISTER["summary"],
        "register_version": VALIDITY_REGISTER_VERSION,
        "register_ref": "analytics/validity_register.py",
        "docs_ref": "docs/PSYCHOMETRICS.md",
        "employment_banner": EMPLOYMENT_BANNER,
        "modifier_factor_note": MODIFIER_FACTOR_NOTE,
        "internal_reliability": internal_reliability,
    }
    return payload
