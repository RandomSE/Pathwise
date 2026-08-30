"""In-game behavioral profile: independent 0-100 dimensions.

These scores describe Pathwise session behavior. They are not construct-valid
or criterion-valid, and they do not predict on-the-job performance.
"""

from __future__ import annotations

import statistics

from analytics.session_risks import normalize_risk_counts
from analytics.validity_register import validity_payload

TRAIT_KEYS = (
    "risk_propensity",
    "decision_tempo",
    "deliberation_depth",
    "rule_adherence",
    "adaptive_planning",
    "composure",
)

NEUTRAL_TRAIT_SCORE = 50.0
MIN_OBSERVED_DURATION_S = 1.0
MIN_RULE_BONUS_DURATION_S = 8.0
MIN_RULE_BONUS_CROSSINGS = 1
RISK_RATE_GAIN = 400.0
REASONABLE_RATE_GAIN = 80.0
RED_RATE_GAIN = 220.0
HESITATION_SECONDS_GAIN = 12.0
HESITATION_COUNT_GAIN = 6.0
SUCCESS_PLANNING_BONUS = 12.0
REPLAN_QUALITY_GAIN = 18.0
FAILED_REPLAN_PENALTY = 14.0
COMPOSURE_FAST_RECOVERY_S = 0.4
COMPOSURE_SLOW_RECOVERY_S = 8.0
VARIANCE_TO_ZERO_SD = 28.0

LOGGER_QUICK_S = 1.2
LOGGER_SLOW_S = 4.0
QUICK_REPR_S = 0.8
MEDIUM_REPR_S = 2.6
SLOW_REPR_S = 5.5
TEMPO_FAST_ANCHOR_S = 0.4
TEMPO_SLOW_ANCHOR_S = 8.0
MAX_TEMPO_PATH_DELTA = 8.0
TYPICAL_WALK_PX_S = 90.0
MOTOR_TEMPO_KEY = "motor_tempo"

FLAG_OK = "ok"
FLAG_INSUFFICIENT = "insufficient_data"

VALIDITY = validity_payload()

TRAIT_LABELS = {
    "risk_propensity": "In-game risk propensity",
    "decision_tempo": "In-game decision tempo",
    "deliberation_depth": "In-game deliberation depth",
    "rule_adherence": "In-game rule adherence",
    "adaptive_planning": "In-game adaptive planning",
    "composure": "In-game composure",
}

TRAIT_DESCRIPTIONS = {
            "risk_propensity": (
                "Game-derived rate of risky and red-light exposure in this session. "
                "Not a risk-taking construct from psychometrics."
            ),
    "decision_tempo": (
        "In-game go/no-go speed after curb arrival (100 = fast commit_latency_s, "
        "0 = slow). Not raw approach-to-cross time. Not a personality construct."
    ),
    "deliberation_depth": (
        "Game-derived pause time and pause count at crossings. Freezing is not tempo."
    ),
    "rule_adherence": (
        "Game-derived green vs red crossing mix, with a zero-risky-events bonus "
        "when the session is long enough to interpret. Not conscientiousness."
    ),
            "adaptive_planning": (
                "Game-derived replanning quality after backtracks, plus a success bonus. "
                "Not a planning construct from psychometrics."
            ),
    "composure": (
        "Game-derived recovery speed after backtrack or risk marks in this "
        "round. Between-round variance of other traits is reliability, not "
        "composure."
    ),
}

_ADVANCE_ACTIONS = frozenset(
    {"advance", "commit", "quick_commit", "deliberate_commit"}
)
_RECOVERY_TRIGGERS = frozenset({"backtrack", "risk_event"})


def tempo_from_commit_s(seconds) -> float:
    """Map commit seconds to 0-100. Monotonic decreasing, no logger-bin steps."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return NEUTRAL_TRAIT_SCORE
    if value <= TEMPO_FAST_ANCHOR_S:
        return 100.0
    if value >= TEMPO_SLOW_ANCHOR_S:
        return 0.0
    span = TEMPO_SLOW_ANCHOR_S - TEMPO_FAST_ANCHOR_S
    return 100.0 * (1.0 - (value - TEMPO_FAST_ANCHOR_S) / span)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _as_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summary(session: dict) -> dict:
    return session.get("summary") or {}


def _count_actions(decisions: list, action: str) -> int:
    return sum(1 for item in decisions if item.get("action") == action)


def _finite_number(raw) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def _finite_commit_times(session: dict) -> list[float]:
    times = []
    for attempt in session.get("crossing_attempts") or []:
        value = _finite_number(attempt.get("commit_time_s"))
        if value is not None:
            times.append(value)
    return times


def _latency_from_attempt(attempt: dict) -> tuple[float, str] | None:
    latency = _finite_number(attempt.get("commit_latency_s"))
    if latency is not None:
        return latency, "commit_latency_s"
    commit = _finite_number(attempt.get("commit_time_s"))
    if commit is None:
        return None
    travel = _finite_number(attempt.get("approach_travel_s"))
    if travel is not None:
        return max(0.0, commit - travel), "commit_latency_residual"
    path_px = _finite_number(attempt.get("approach_path_px"))
    if path_px is not None:
        expected_motor = path_px / TYPICAL_WALK_PX_S
        return max(0.0, commit - expected_motor), "commit_latency_residual"
    return None


def _motor_seconds_from_attempt(attempt: dict) -> float | None:
    travel = _finite_number(attempt.get("approach_travel_s"))
    if travel is not None:
        return travel
    path_px = _finite_number(attempt.get("approach_path_px"))
    if path_px is not None:
        return path_px / TYPICAL_WALK_PX_S
    return None


def _event_t(item: dict):
    if "t" not in item or item.get("t") is None:
        return None
    try:
        return float(item["t"])
    except (TypeError, ValueError):
        return None


def score_risk_propensity(session: dict) -> tuple[float | None, str]:
    duration = max(_as_float(session.get("duration_s"), 0.0), 0.0)
    risky, reasonable, _legacy = normalize_risk_counts(session)
    red_crosses = _count_actions(session.get("decision_sequence") or [], "cross_on_red")
    has_time = duration >= MIN_OBSERVED_DURATION_S
    has_events = (risky + reasonable + red_crosses) > 0
    if not has_time and not has_events:
        return None, FLAG_INSUFFICIENT
    denom = max(duration, 0.1)
    score = NEUTRAL_TRAIT_SCORE
    score += RISK_RATE_GAIN * (risky / denom)
    score += REASONABLE_RATE_GAIN * (reasonable / denom)
    score += RED_RATE_GAIN * (red_crosses / denom)
    return round(_clamp(score), 1), FLAG_OK


def score_decision_tempo(session: dict) -> tuple[float | None, str, str | None]:
    latencies = []
    sources = []
    for attempt in session.get("crossing_attempts") or []:
        parsed = _latency_from_attempt(attempt)
        if parsed is None:
            continue
        value, source = parsed
        latencies.append(value)
        sources.append(source)
    if latencies:
        mean_s = sum(latencies) / len(latencies)
        source = (
            "commit_latency_s"
            if "commit_latency_s" in sources
            else "commit_latency_residual"
        )
        return round(_clamp(tempo_from_commit_s(mean_s)), 1), FLAG_OK, source
    return None, FLAG_INSUFFICIENT, None


def score_motor_tempo(session: dict) -> tuple[float | None, str, str | None]:
    travels = []
    used_path = False
    for attempt in session.get("crossing_attempts") or []:
        travel = _motor_seconds_from_attempt(attempt)
        if travel is None:
            continue
        if attempt.get("approach_travel_s") is None and attempt.get("approach_path_px") is not None:
            used_path = True
        travels.append(travel)
    if not travels:
        return None, FLAG_INSUFFICIENT, None
    mean_s = sum(travels) / len(travels)
    source = "approach_path_px" if used_path else "approach_travel_s"
    return round(_clamp(tempo_from_commit_s(mean_s)), 1), FLAG_OK, source


def score_deliberation_depth(session: dict) -> tuple[float | None, str]:
    summary = _summary(session)
    hesitation_s = _as_float(summary.get("total_hesitation_s"), 0.0)
    hesitation_count = int(summary.get("hesitation_count") or 0)
    crossings = int(session.get("crossings") or 0)
    duration = _as_float(session.get("duration_s"), 0.0)
    observed = crossings > 0 or duration >= MIN_OBSERVED_DURATION_S or hesitation_count > 0 or hesitation_s > 0
    if not observed:
        return None, FLAG_INSUFFICIENT
    per_road = hesitation_s / max(crossings, 1)
    score = NEUTRAL_TRAIT_SCORE
    score += HESITATION_SECONDS_GAIN * per_road
    score += HESITATION_COUNT_GAIN * hesitation_count
    return round(_clamp(score), 1), FLAG_OK


def score_rule_adherence(session: dict) -> tuple[float | None, str]:
    decisions = session.get("decision_sequence") or []
    green = _count_actions(decisions, "cross_on_green")
    red = _count_actions(decisions, "cross_on_red")
    if green + red <= 0:
        return None, FLAG_INSUFFICIENT
    ratio = green / (green + red)
    score = 100.0 * ratio
    duration = _as_float(session.get("duration_s"), 0.0)
    crossings = int(session.get("crossings") or 0)
    risky, _reasonable, _legacy = normalize_risk_counts(session)
    if (
        risky == 0
        and red == 0
        and duration >= MIN_RULE_BONUS_DURATION_S
        and crossings >= MIN_RULE_BONUS_CROSSINGS
    ):
        score = _clamp(score + 8.0)
    return round(_clamp(score), 1), FLAG_OK


def _replans(decisions: list) -> tuple[int, int]:
    recovered = 0
    failed = 0
    for index, item in enumerate(decisions):
        if item.get("action") != "backtrack":
            continue
        later = decisions[index + 1 :]
        if any(entry.get("action") in _ADVANCE_ACTIONS for entry in later):
            recovered += 1
        else:
            failed += 1
    return recovered, failed


def score_adaptive_planning(session: dict) -> tuple[float | None, str]:
    decisions = session.get("decision_sequence") or []
    recovered, failed = _replans(decisions)
    outcome = session.get("outcome")
    summary = _summary(session)
    backtracks = int(summary.get("total_backtracks") or 0)
    if recovered == 0 and failed == 0 and backtracks == 0 and outcome not in ("success", "collision"):
        return None, FLAG_INSUFFICIENT
    score = NEUTRAL_TRAIT_SCORE
    score += REPLAN_QUALITY_GAIN * recovered
    score -= FAILED_REPLAN_PENALTY * failed
    if outcome == "success":
        score += SUCCESS_PLANNING_BONUS
    elif outcome == "collision":
        score -= 10.0
    return round(_clamp(score), 1), FLAG_OK


def _recovery_seconds(decisions: list) -> list[float] | None:
    missing_t = False
    recoveries = []
    for index, item in enumerate(decisions):
        action = item.get("action")
        if action not in _RECOVERY_TRIGGERS:
            continue
        start = _event_t(item)
        if start is None:
            missing_t = True
            continue
        recovered_at = None
        for later in decisions[index + 1 :]:
            if later.get("action") in _ADVANCE_ACTIONS:
                later_t = _event_t(later)
                if later_t is None:
                    missing_t = True
                    break
                recovered_at = later_t
                break
        if recovered_at is not None:
            recoveries.append(max(0.0, recovered_at - start))
    if missing_t and not recoveries:
        return None
    return recoveries


def _composure_from_recovery(mean_s: float) -> float:
    if mean_s <= COMPOSURE_FAST_RECOVERY_S:
        return 100.0
    if mean_s >= COMPOSURE_SLOW_RECOVERY_S:
        return 0.0
    span = COMPOSURE_SLOW_RECOVERY_S - COMPOSURE_FAST_RECOVERY_S
    return 100.0 * (1.0 - (mean_s - COMPOSURE_FAST_RECOVERY_S) / span)


def score_composure(session: dict) -> tuple[float | None, str]:
    decisions = session.get("decision_sequence") or []
    recoveries = _recovery_seconds(decisions)
    if recoveries is None:
        return None, FLAG_INSUFFICIENT
    if not recoveries:
        return None, FLAG_INSUFFICIENT
    mean_s = sum(recoveries) / len(recoveries)
    return round(_clamp(_composure_from_recovery(mean_s)), 1), FLAG_OK


def _score_round_traits(session: dict) -> tuple[dict, dict, dict]:
    traits = {}
    flags = {}
    sources = {}
    traits["risk_propensity"], flags["risk_propensity"] = score_risk_propensity(session)
    tempo, tempo_flag, tempo_src = score_decision_tempo(session)
    traits["decision_tempo"] = tempo
    flags["decision_tempo"] = tempo_flag
    if tempo_src:
        sources["decision_tempo"] = tempo_src
    traits["deliberation_depth"], flags["deliberation_depth"] = score_deliberation_depth(
        session
    )
    traits["rule_adherence"], flags["rule_adherence"] = score_rule_adherence(session)
    traits["adaptive_planning"], flags["adaptive_planning"] = score_adaptive_planning(
        session
    )
    traits["composure"], flags["composure"] = score_composure(session)
    motor, motor_flag, motor_src = score_motor_tempo(session)
    sources["motor_tempo"] = motor
    sources["motor_tempo_flag"] = motor_flag
    if motor_src:
        sources["motor_tempo_source"] = motor_src
    sources["composure_between_round_variance"] = FLAG_INSUFFICIENT
    return traits, flags, sources


def _build_insights(traits: dict, flags: dict, role_fits: list, sources: dict) -> list[str]:
    insights = []
    for key in TRAIT_KEYS:
        if flags.get(key) != FLAG_OK or traits.get(key) is None:
            continue
        value = traits[key]
        if value >= 70:
            insights.append(
                f"{TRAIT_LABELS[key]} was {value} in this Pathwise session "
                f"(game-derived behavioral profile)."
            )
    tempo_src = sources.get("decision_tempo")
    if tempo_src == "commit_latency_s":
        insights.append("Decision tempo used crossing_attempts commit_latency_s after curb arrival.")
    elif tempo_src == "commit_latency_residual":
        insights.append(
            "Decision tempo used a motor-adjusted commit_latency residual, not raw approach time."
        )
    ranked = [row for row in role_fits if row.get("fit") is not None]
    ranked.sort(key=lambda row: -float(row["fit"]))
    if len(ranked) >= 2:
        top = ranked[0]
        second = ranked[1]
        insights.append(
            f"Closer to the {top['role_id']} target profile than to "
            f"{second['role_id']} (target similarity, not a job prediction)."
        )
    elif len(ranked) == 1:
        insights.append(
            f"Nearest designed target profile is {ranked[0]['role_id']} "
            f"(target similarity, not a job prediction)."
        )
    if not insights:
        insights.append(
            "Game-derived session profile recorded. Target similarity is not a job prediction."
        )
    return insights


def assemble_payload(traits: dict, flags: dict, sources: dict) -> dict:
    from analytics.archetype_labels import ARCHETYPE_CENTROIDS, cosmetic_archetype
    from analytics.role_fit import compute_role_fits, rank_role_fits

    role_fits = rank_role_fits(compute_role_fits(traits, flags))
    cosmetic = cosmetic_archetype(traits, flags)
    insights = _build_insights(traits, flags, role_fits, sources)
    descriptions = {
        key: ARCHETYPE_CENTROIDS[key]["label"] for key in ARCHETYPE_CENTROIDS
    }
    reliability = sources.pop("_reliability", None)
    contrasts = sources.pop("_within_person_contrasts", None)
    validity = validity_payload(
        internal_reliability=None if reliability is None else {
            "kind": reliability.get("kind"),
            "claim": reliability.get("claim"),
            "n_rounds": reliability.get("n_rounds"),
        }
    )
    diagnostics = {
        "motor_tempo": sources.get("motor_tempo"),
        "motor_tempo_flag": sources.get("motor_tempo_flag"),
        "motor_tempo_source": sources.get("motor_tempo_source"),
    }
    payload = {
        "validity": validity,
        "traits": traits,
        "trait_flags": flags,
        "trait_labels": dict(TRAIT_LABELS),
        "trait_descriptions": dict(TRAIT_DESCRIPTIONS),
        "signal_sources": sources,
        "diagnostics": diagnostics,
        "reliability": reliability,
        "within_person_contrasts": contrasts,
        "role_fits": role_fits,
        "archetype": {
            "primary_key": cosmetic["primary_key"],
            "primary_label": cosmetic["primary_label"],
            "secondary_key": cosmetic["secondary_key"],
            "secondary_label": cosmetic["secondary_label"],
            "cosmetic": True,
        },
        "insights": insights,
        "scores": cosmetic["scores"],
        "labels": cosmetic["labels"],
        "descriptions": {
            key: f"Session flavor: {label}." for key, label in descriptions.items()
        },
        "primary_archetype": cosmetic["primary_key"],
        "primary_label": cosmetic["primary_label"],
        "primary_score": cosmetic["primary_score"],
        "secondary_archetype": cosmetic["secondary_key"],
        "secondary_label": cosmetic["secondary_label"],
        "secondary_score": cosmetic["secondary_score"],
    }
    payload["hiring_output"] = {
        "kind": "role_target_similarity",
        "traits": payload["traits"],
        "role_fits": payload["role_fits"],
        "validity": payload["validity"],
        "reliability": payload["reliability"],
    }
    return payload


def score_session(session: dict | None) -> dict:
    session = session or {}
    traits, flags, sources = _score_round_traits(session)
    from analytics.reliability import session_reliability

    sources["_reliability"] = session_reliability([(traits, flags)])
    sources["_within_person_contrasts"] = _within_person_contrasts(
        [session], [(traits, flags, sources)]
    )
    return assemble_payload(traits, flags, sources)


def _sessions_from_log(payload: dict) -> list[dict]:
    rounds = payload.get("rounds") or []
    sessions = []
    for entry in rounds:
        if not isinstance(entry, dict):
            continue
        if entry.get("session"):
            sessions.append(entry["session"])
        else:
            sessions.append(entry)
    if sessions:
        return sessions
    session = payload.get("session")
    if isinstance(session, dict):
        return [session]
    if isinstance(payload, dict) and payload.get("duration_s") is not None:
        return [payload]
    return [{}]


def _weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    total_w = sum(weight for _value, weight in pairs)
    if total_w <= 0:
        return None
    return sum(value * weight for value, weight in pairs) / total_w


def _between_round_stdev(round_traits: list[dict], round_flags: list[dict]) -> float | None:
    if len(round_traits) < 2:
        return None
    dimension_sds = []
    for key in TRAIT_KEYS:
        if key == "composure":
            continue
        values = []
        for traits, flags in zip(round_traits, round_flags):
            if flags.get(key) == FLAG_OK and traits.get(key) is not None:
                values.append(float(traits[key]))
        if len(values) >= 2:
            dimension_sds.append(statistics.pstdev(values))
    if not dimension_sds:
        return None
    return sum(dimension_sds) / len(dimension_sds)


def _composure_from_variance(stdev: float) -> float:
    return _clamp(100.0 * (1.0 - stdev / VARIANCE_TO_ZERO_SD))


def score_session_log(payload: dict | None) -> dict:
    payload = payload or {}
    sessions = _sessions_from_log(payload)
    if len(sessions) == 1:
        return score_session(sessions[0])
    per_round = [_score_round_traits(session) for session in sessions]
    durations = [
        max(_as_float(session.get("duration_s"), 0.0), 0.0) for session in sessions
    ]
    if sum(durations) <= 0:
        durations = [1.0] * len(sessions)
    traits = {}
    flags = {}
    for key in TRAIT_KEYS:
        pairs = []
        for (round_traits, round_flags, _src), weight in zip(per_round, durations):
            if round_flags.get(key) == FLAG_OK and round_traits.get(key) is not None:
                pairs.append((float(round_traits[key]), weight))
        if not pairs:
            traits[key] = None
            flags[key] = FLAG_INSUFFICIENT
        else:
            traits[key] = round(_clamp(_weighted_mean(pairs)), 1)
            flags[key] = FLAG_OK
    sources = {}
    tempo_tags = [item[2].get("decision_tempo") for item in per_round]
    if "commit_latency_s" in tempo_tags:
        sources["decision_tempo"] = "commit_latency_s"
    elif "commit_latency_residual" in tempo_tags:
        sources["decision_tempo"] = "commit_latency_residual"
    sources["composure_between_round_variance"] = FLAG_INSUFFICIENT
    motor_pairs = []
    motor_src = None
    for (round_traits, round_flags, round_src), weight in zip(per_round, durations):
        motor = round_src.get("motor_tempo")
        if round_src.get("motor_tempo_flag") == FLAG_OK and motor is not None:
            motor_pairs.append((float(motor), weight))
            motor_src = round_src.get("motor_tempo_source") or motor_src
    if motor_pairs:
        sources["motor_tempo"] = round(_clamp(_weighted_mean(motor_pairs)), 1)
        sources["motor_tempo_flag"] = FLAG_OK
        if motor_src:
            sources["motor_tempo_source"] = motor_src
    else:
        sources["motor_tempo"] = None
        sources["motor_tempo_flag"] = FLAG_INSUFFICIENT
    from analytics.reliability import session_reliability

    sources["_reliability"] = session_reliability(
        [(item[0], item[1]) for item in per_round]
    )
    sources["_within_person_contrasts"] = _within_person_contrasts(sessions, per_round)
    return assemble_payload(traits, flags, sources)


def _within_person_contrasts(sessions: list[dict], per_round: list) -> dict:
    """Trait deltas vs that person's no-modifier baseline rounds when present."""
    pressure_ids = {"time_pressure", "highway", "lawless", "lag", "old"}
    baseline_vals = {key: [] for key in TRAIT_KEYS}
    pressure_vals = {key: [] for key in TRAIT_KEYS}
    baseline_n = 0
    pressure_n = 0
    recorded = []
    for session, (traits, flags, _src) in zip(sessions, per_round):
        mods = [str(item) for item in (session.get("modifiers") or [])]
        recorded.append(mods)
        bucket = pressure_vals if pressure_ids.intersection(mods) else baseline_vals
        if pressure_ids.intersection(mods):
            pressure_n += 1
        else:
            baseline_n += 1
        for key in TRAIT_KEYS:
            if flags.get(key) == FLAG_OK and traits.get(key) is not None:
                bucket[key].append(float(traits[key]))
    if baseline_n <= 0 or pressure_n <= 0:
        return {
            "status": FLAG_INSUFFICIENT,
            "note": (
                "Need both baseline and modifier rounds to score pressure/chaos "
                "sensitivity as a within-person delta."
            ),
            "modifiers_by_round": recorded,
            "deltas": {},
        }
    deltas = {}
    for key in TRAIT_KEYS:
        if baseline_vals[key] and pressure_vals[key]:
            deltas[key] = round(
                (sum(pressure_vals[key]) / len(pressure_vals[key]))
                - (sum(baseline_vals[key]) / len(baseline_vals[key])),
                2,
            )
    return {
        "status": FLAG_OK,
        "note": (
            "Experimental-factor deltas vs this person's baseline rounds. "
            "Modifiers are not demographic proxies."
        ),
        "modifiers_by_round": recorded,
        "deltas": deltas,
    }
