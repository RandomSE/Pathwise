"""Cosmetic session-flavor labels from the in-game trait vector.

Narrative only. Not a hiring engine and not a psychological diagnosis.
"""

from __future__ import annotations

ARCHETYPE_CENTROIDS = {
    "cautious_deliberator": {
        "label": "Cautious Deliberator",
        "traits": {
            "risk_propensity": 25.0,
            "decision_tempo": 25.0,
            "deliberation_depth": 85.0,
            "rule_adherence": 70.0,
            "adaptive_planning": 55.0,
            "composure": 70.0,
        },
    },
    "impulsive_mover": {
        "label": "Impulsive Mover",
        "traits": {
            "risk_propensity": 55.0,
            "decision_tempo": 85.0,
            "deliberation_depth": 20.0,
            "rule_adherence": 40.0,
            "adaptive_planning": 35.0,
            "composure": 40.0,
        },
    },
    "risk_taker": {
        "label": "Risk-Taker",
        "traits": {
            "risk_propensity": 80.0,
            "decision_tempo": 70.0,
            "deliberation_depth": 30.0,
            "rule_adherence": 30.0,
            "adaptive_planning": 40.0,
            "composure": 45.0,
        },
    },
    "rule_follower": {
        "label": "Rule-Follower",
        "traits": {
            "risk_propensity": 25.0,
            "decision_tempo": 45.0,
            "deliberation_depth": 55.0,
            "rule_adherence": 85.0,
            "adaptive_planning": 50.0,
            "composure": 70.0,
        },
    },
    "strategic_planner": {
        "label": "Strategic Planner",
        "traits": {
            "risk_propensity": 45.0,
            "decision_tempo": 45.0,
            "deliberation_depth": 65.0,
            "rule_adherence": 60.0,
            "adaptive_planning": 80.0,
            "composure": 65.0,
        },
    },
}


def cosmetic_archetype(traits: dict, flags: dict) -> dict:
    ranked = []
    for key in sorted(ARCHETYPE_CENTROIDS):
        spec = ARCHETYPE_CENTROIDS[key]
        distance = _centroid_distance(traits, flags, spec["traits"])
        similarity = max(0.0, min(100.0, 100.0 - distance))
        ranked.append((key, spec["label"], similarity, distance))
    ranked.sort(key=lambda item: (-item[2], item[0]))
    primary_key, primary_label, primary_score, _ = ranked[0]
    secondary_key = secondary_label = None
    secondary_score = 0.0
    if len(ranked) > 1:
        secondary_key, secondary_label, secondary_score, _ = ranked[1]
    scores = {key: round(score, 1) for key, _label, score, _dist in ranked}
    labels = {key: ARCHETYPE_CENTROIDS[key]["label"] for key in ARCHETYPE_CENTROIDS}
    return {
        "primary_key": primary_key,
        "primary_label": primary_label,
        "secondary_key": secondary_key,
        "secondary_label": secondary_label,
        "cosmetic": True,
        "scores": scores,
        "labels": labels,
        "primary_score": round(primary_score, 1),
        "secondary_score": round(secondary_score, 1),
    }


def _centroid_distance(traits: dict, flags: dict, centroid: dict) -> float:
    total = 0.0
    count = 0
    for key, target in centroid.items():
        if flags.get(key) != "ok" or traits.get(key) is None:
            continue
        delta = float(traits[key]) - float(target)
        total += delta * delta
        count += 1
    if count == 0:
        return 100.0
    return (total / count) ** 0.5
