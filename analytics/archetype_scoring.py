from analytics.session_risks import normalize_risk_counts


ARCHETYPES = {
    "risk_taker": {
        "label": "Risk-Taker",
        "description": "Comfortable acting under pressure; may cross against traffic or take tight gaps.",
    },
    "strategic_planner": {
        "label": "Strategic Planner",
        "description": "Pauses to read the situation, then commits with intent; balances safety and pace.",
    },
    "rule_follower": {
        "label": "Rule-Follower",
        "description": "Waits for clear signals and avoids unnecessary exposure to danger.",
    },
    "cautious_deliberator": {
        "label": "Cautious Deliberator",
        "description": "High hesitation and low impulsivity; prioritizes safety over speed.",
    },
    "impulsive_mover": {
        "label": "Impulsive Mover",
        "description": "Commits quickly with little pause; fast but may overlook hazards.",
    },
}


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _ratio(numerator, denominator, default=0.0):
    if denominator <= 0:
        return default
    return numerator / denominator


def score_session(session):
    summary = session.get("summary", {})
    decisions = session.get("decision_sequence", [])
    risky_risks, reasonable_risks, legacy_risks = normalize_risk_counts(session)
    risks = risky_risks
    duration = max(session.get("duration_s", 1), 0.1)
    red_crosses = sum(1 for d in decisions if d.get("action") == "cross_on_red")
    green_crosses = sum(1 for d in decisions if d.get("action") == "cross_on_green")
    backtracks = summary.get("total_backtracks", 0)
    hesitation_s = summary.get("total_hesitation_s", 0)
    hesitation_count = summary.get("hesitation_count", 0)
    quick_commits = summary.get("quick_commits", 0)
    slow_commits = summary.get("slow_commits", 0)
    outcome = session.get("outcome", "unknown")

    risk_rate = risks / duration
    reasonable_rate = 0.0 if legacy_risks else reasonable_risks / duration
    hesitation_per_road = hesitation_s / max(session.get("crossings", 1), 1)

    scores = {
        "risk_taker": _clamp(
            35
            + risk_rate * 120
            + reasonable_rate * 35
            + red_crosses * 14
            + quick_commits * 10
            - green_crosses * 4
            - hesitation_per_road * 8
        ),
        "strategic_planner": _clamp(
            30
            + slow_commits * 12
            + hesitation_count * 6
            + green_crosses * 5
            + (10 if outcome == "success" else 0)
            - red_crosses * 8
            - backtracks * 3
        ),
        "rule_follower": _clamp(
            25
            + green_crosses * 12
            - red_crosses * 18
            - risk_rate * 90
            - reasonable_rate * 25
            + (15 if risks == 0 else 0)
        ),
        "cautious_deliberator": _clamp(
            20
            + hesitation_per_road * 25
            + hesitation_count * 8
            + slow_commits * 8
            - quick_commits * 12
            - red_crosses * 6
        ),
        "impulsive_mover": _clamp(
            20
            + quick_commits * 18
            - hesitation_per_road * 20
            - hesitation_count * 5
            + red_crosses * 6
            + backtracks * 4
        ),
    }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary_key, primary_score = ranked[0]
    secondary_key, secondary_score = ranked[1] if len(ranked) > 1 else (None, 0)

    insights = _build_insights(
        session,
        primary_key,
        risky_risks,
        reasonable_risks,
        hesitation_s,
        backtracks,
        quick_commits,
        red_crosses,
        green_crosses,
    )

    return {
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "labels": {k: ARCHETYPES[k]["label"] for k in ARCHETYPES},
        "descriptions": {k: ARCHETYPES[k]["description"] for k in ARCHETYPES},
        "primary_archetype": primary_key,
        "primary_label": ARCHETYPES[primary_key]["label"],
        "primary_score": round(primary_score, 1),
        "secondary_archetype": secondary_key,
        "secondary_label": ARCHETYPES[secondary_key]["label"] if secondary_key else None,
        "secondary_score": round(secondary_score, 1),
        "insights": insights,
    }


def _build_insights(
    session, primary, risky_risks, reasonable_risks, hesitation_s, backtracks, quick_commits, red_crosses, green_crosses
):
    insights = []
    if hesitation_s > 2:
        insights.append(f"Paused for {hesitation_s:.1f}s total—shows deliberate evaluation before acting.")
    elif hesitation_s < 0.5 and session.get("crossings", 0) > 0:
        insights.append("Rarely hesitated at crossings; decisions came quickly.")

    if backtracks > 2:
        insights.append(f"Backtracked {backtracks} times—reconsidered path or retreated from danger.")
    elif backtracks == 0 and session.get("crossings", 0) > 1:
        insights.append("Moved forward consistently without reversing course.")

    if red_crosses > green_crosses and red_crosses > 0:
        insights.append("Often crossed while traffic had priority—higher risk tolerance.")
    elif green_crosses > 0 and red_crosses == 0:
        insights.append("Aligned crossings with favorable signals—strong rule awareness.")

    if quick_commits >= 2:
        insights.append("Multiple fast commits at roads—acts decisively once opportunity appears.")

    if risky_risks >= 3:
        insights.append(
            f"Logged {risky_risks} risky moves—comfort operating in tight traffic windows."
        )
    elif risky_risks == 0 and session.get("outcome") == "success":
        insights.append("Completed run with zero flagged risky moves.")
    if reasonable_risks >= 2 and risky_risks == 0:
        insights.append(
            f"Took {reasonable_risks} calculated risks without crossing into reckless territory."
        )

    if not insights:
        insights.append(f"Primary fit: {ARCHETYPES[primary]['label']}. Review timeline for nuance.")

    return insights
