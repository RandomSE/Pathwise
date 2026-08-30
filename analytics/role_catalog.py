"""Versioned in-repo role targets.

Targets and weights are design priors, not criterion-fitted.
They are unvalidated priors for face-valid in-game target similarity only.
"""

from __future__ import annotations

ROLE_CATALOG_VERSION = "1"

# Starter roles. Adding a fifth role must not require touching trait math.
# Targets and weights are unvalidated priors, not empirically fitted criteria.
ROLE_CATALOG = (
    {
        "role_id": "field_construction",
        "label": "Field construction",
        "targets": {
            "risk_propensity": 70,
            "adaptive_planning": 75,
            "composure": 55,
            "rule_adherence": 45,
            "decision_tempo": 60,
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
        "targets": {
            "rule_adherence": 85,
            "composure": 80,
            "risk_propensity": 25,
            "decision_tempo": 40,
            "deliberation_depth": 70,
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
        "targets": {
            "rule_adherence": 75,
            "decision_tempo": 75,
            "composure": 70,
            "adaptive_planning": 60,
            "risk_propensity": 35,
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
        "targets": {
            "decision_tempo": 70,
            "composure": 65,
            "rule_adherence": 60,
            "adaptive_planning": 55,
            "risk_propensity": 40,
            "deliberation_depth": 45,
        },
        "weights": {
            "decision_tempo": 0.22,
            "composure": 0.20,
            "rule_adherence": 0.20,
            "adaptive_planning": 0.14,
            "risk_propensity": 0.12,
            "deliberation_depth": 0.12,
        },
        "polarity": {},
    },
)


def roles_by_id() -> dict:
    return {role["role_id"]: role for role in ROLE_CATALOG}
