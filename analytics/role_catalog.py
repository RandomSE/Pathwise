"""Versioned in-repo role targets.

Targets are directional band midpoints (unvalidated priors), not
criterion-fitted job profiles. They are not a claim of job fit.
"""

from __future__ import annotations

ROLE_CATALOG_VERSION = "2"

# Starter roles. Adding a fifth role must not require touching trait math.
# Targets are unvalidated priors: band midpoints, not empirically fitted criteria.
ROLE_CATALOG = (
    {
        "role_id": "field_construction",
        "label": "Field construction",
        "rationale": (
            "Higher in-game risk exposure and adaptive replans than the "
            "compliance auditor prior. This is a task-profile contrast, not a "
            "claim that construction workers are reckless."
        ),
        "target_bands": {
            "risk_propensity": (56, 72),
            "adaptive_planning": (58, 74),
            "composure": (46, 62),
            "rule_adherence": (38, 52),
            "decision_tempo": (48, 62),
            "deliberation_depth": (32, 48),
        },
        "targets": {
            "risk_propensity": 64,
            "adaptive_planning": 66,
            "composure": 54,
            "rule_adherence": 45,
            "decision_tempo": 55,
            "deliberation_depth": 40,
        },
        "weights": {
            "risk_propensity": 0.28,
            "adaptive_planning": 0.24,
            "composure": 0.12,
            "rule_adherence": 0.12,
            "decision_tempo": 0.14,
            "deliberation_depth": 0.10,
        },
        "polarity": {},
    },
    {
        "role_id": "compliance_auditor",
        "label": "Compliance auditor",
        "rationale": (
            "Highest in-game rule_adherence and lowest risk_propensity among "
            "the four priors. Unvalidated design contrast only."
        ),
        "target_bands": {
            "rule_adherence": (74, 90),
            "composure": (64, 78),
            "risk_propensity": (16, 32),
            "decision_tempo": (32, 48),
            "deliberation_depth": (58, 74),
            "adaptive_planning": (42, 58),
        },
        "targets": {
            "rule_adherence": 82,
            "composure": 71,
            "risk_propensity": 24,
            "decision_tempo": 40,
            "deliberation_depth": 66,
            "adaptive_planning": 50,
        },
        "weights": {
            "rule_adherence": 0.30,
            "composure": 0.24,
            "risk_propensity": 0.16,
            "deliberation_depth": 0.14,
            "decision_tempo": 0.08,
            "adaptive_planning": 0.08,
        },
        "polarity": {},
    },
    {
        "role_id": "logistics_dispatcher",
        "label": "Logistics dispatcher",
        "rationale": (
            "High in-game decision_tempo with high rule_adherence (speed with "
            "procedure). Risk stays low-to-mid; this is not a high-risk prior."
        ),
        "target_bands": {
            "rule_adherence": (66, 82),
            "decision_tempo": (64, 80),
            "composure": (56, 70),
            "adaptive_planning": (50, 64),
            "risk_propensity": (22, 38),
            "deliberation_depth": (32, 48),
        },
        "targets": {
            "rule_adherence": 74,
            "decision_tempo": 72,
            "composure": 63,
            "adaptive_planning": 57,
            "risk_propensity": 30,
            "deliberation_depth": 40,
        },
        "weights": {
            "rule_adherence": 0.26,
            "decision_tempo": 0.26,
            "composure": 0.18,
            "adaptive_planning": 0.12,
            "risk_propensity": 0.10,
            "deliberation_depth": 0.08,
        },
        "polarity": {},
    },
    {
        "role_id": "warehouse_operator",
        "label": "Warehouse operator",
        "rationale": (
            "Nearer the middle of each in-game band. Not a five-point offset "
            "of the dispatcher prior."
        ),
        "target_bands": {
            "decision_tempo": (44, 60),
            "composure": (44, 60),
            "rule_adherence": (46, 62),
            "adaptive_planning": (44, 60),
            "risk_propensity": (38, 54),
            "deliberation_depth": (40, 56),
        },
        "targets": {
            "decision_tempo": 52,
            "composure": 52,
            "rule_adherence": 54,
            "adaptive_planning": 52,
            "risk_propensity": 46,
            "deliberation_depth": 48,
        },
        "weights": {
            "decision_tempo": 0.18,
            "composure": 0.18,
            "rule_adherence": 0.18,
            "adaptive_planning": 0.16,
            "risk_propensity": 0.16,
            "deliberation_depth": 0.14,
        },
        "polarity": {},
    },
)


def roles_by_id() -> dict:
    return {role["role_id"]: role for role in ROLE_CATALOG}
