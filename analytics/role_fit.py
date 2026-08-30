"""Weighted distance from an in-game trait vector to role target priors.

Fit is target similarity, not a job-performance prediction.
"""

from __future__ import annotations

from analytics.role_catalog import ROLE_CATALOG

MIN_ROLE_FIT_COVERAGE = 0.50
INTERPRETATION = "target_similarity_only"


def compute_role_fits(traits: dict, flags: dict, catalog=ROLE_CATALOG) -> list[dict]:
    rows = []
    for role in catalog:
        rows.append(_fit_one_role(role, traits, flags))
    return rows


def rank_role_fits(rows: list[dict]) -> list[dict]:
    """Numeric fits descending, then nulls in original order."""
    numbered = [(index, row) for index, row in enumerate(rows)]

    def sort_key(item):
        index, row = item
        fit = row.get("fit")
        if fit is None:
            return (1, 0.0, index)
        return (0, -float(fit), index)

    return [row for _, row in sorted(numbered, key=sort_key)]


def _fit_one_role(role: dict, traits: dict, flags: dict) -> dict:
    weights = role["weights"]
    targets = role["targets"]
    polarity = role.get("polarity") or {}
    weight_total = sum(float(value) for value in weights.values())
    weight_ok = 0.0
    missing = []
    for key, weight in weights.items():
        measured = flags.get(key) == "ok" and traits.get(key) is not None
        if measured:
            weight_ok += float(weight)
        else:
            missing.append(key)
    coverage = (weight_ok / weight_total) if weight_total else 0.0
    if coverage < MIN_ROLE_FIT_COVERAGE:
        fit = None
        reason = "insufficient_coverage"
    else:
        numerator = 0.0
        denominator = 0.0
        for key, weight in weights.items():
            if flags.get(key) != "ok" or traits.get(key) is None:
                continue
            profile = float(traits[key])
            target = float(targets[key])
            if polarity.get(key, "target") == "floor":
                gap = (target - profile) / 100.0 if profile < target else 0.0
            else:
                gap = abs(profile - target) / 100.0
            numerator += float(weight) * gap
            denominator += float(weight)
        fit = round(100.0 * (1.0 - numerator / denominator), 1) if denominator else None
        reason = "ok" if fit is not None else "insufficient_coverage"
    return {
        "role_id": role["role_id"],
        "label": role["label"],
        "fit": fit,
        "reason": reason,
        "coverage": round(coverage, 4),
        "weights": dict(weights),
        "targets": dict(targets),
        "missing_dimensions": missing,
        "interpretation": INTERPRETATION,
    }
