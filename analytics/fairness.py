"""Researcher-export fairness scaffolding.

Group labels are optional and must never be collected by the game client.
This module does not authorize employment use.
"""

from __future__ import annotations

import statistics

NO_GROUP_STATUS = "no_group_labels"
OK_STATUS = "computed"
EMPLOYMENT_BANNER = (
    "This tool is not authorized for employment decisions until a fairness "
    "review on real applicants exists."
)


def adverse_impact_ratio(selected_rate_a: float, selected_rate_b: float) -> float | None:
    """Simple selection-rate ratio. None when the reference rate is 0."""
    try:
        left = float(selected_rate_a)
        right = float(selected_rate_b)
    except (TypeError, ValueError):
        return None
    if right == 0:
        return None
    return left / right


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _selected(value: float, cutoff: float, higher_is_selected: bool) -> bool:
    if higher_is_selected:
        return value >= cutoff
    return value <= cutoff


def fairness_report(
    rows: list[dict],
    *,
    group_key: str = "group",
    score_keys: tuple[str, ...] = (),
    selection_cutoffs: dict | None = None,
    higher_is_selected: dict | None = None,
) -> dict:
    """Group means and adverse-impact ratios when an optional label is present."""
    labeled = [row for row in rows if isinstance(row, dict) and row.get(group_key) not in (None, "")]
    score_keys = tuple(score_keys)
    empty_ratios = {key: None for key in score_keys}
    if not labeled:
        return {
            "status": NO_GROUP_STATUS,
            "employment_authorized": False,
            "banner": EMPLOYMENT_BANNER,
            "n": len(rows),
            "groups": [],
            "group_means": {},
            "group_mean_differences": {},
            "adverse_impact_ratio": empty_ratios,
            "selection_rates": {},
        }

    groups = sorted({str(row[group_key]) for row in labeled})
    group_means = {}
    differences = {}
    ratios = {}
    selection_rates = {}
    cutoffs = selection_cutoffs or {}
    higher_map = higher_is_selected or {}

    for key in score_keys:
        by_group = {}
        for group in groups:
            values = [
                number
                for row in labeled
                if str(row.get(group_key)) == group
                for number in [_as_float(row.get(key))]
                if number is not None
            ]
            by_group[group] = values
        group_means[key] = {
            group: None if not values else round(statistics.mean(values), 4)
            for group, values in by_group.items()
        }
        if len(groups) >= 2:
            first, second = groups[0], groups[1]
            left = group_means[key][first]
            right = group_means[key][second]
            differences[key] = None if left is None or right is None else round(left - right, 4)
        else:
            differences[key] = None

        if key in cutoffs and len(groups) >= 2:
            rates = {}
            for group, values in by_group.items():
                if not values:
                    rates[group] = None
                    continue
                picks = sum(
                    1
                    for value in values
                    if _selected(value, float(cutoffs[key]), bool(higher_map.get(key, True)))
                )
                rates[group] = picks / len(values)
            selection_rates[key] = rates
            usable = [rates[group] for group in groups if rates.get(group) is not None]
            if len(usable) < 2:
                ratios[key] = None
            else:
                high = max(usable)
                low = min(usable)
                ratios[key] = adverse_impact_ratio(low, high)
        else:
            ratios[key] = None

    return {
        "status": OK_STATUS,
        "employment_authorized": False,
        "banner": EMPLOYMENT_BANNER,
        "n": len(labeled),
        "groups": groups,
        "group_means": group_means,
        "group_mean_differences": differences,
        "adverse_impact_ratio": ratios,
        "selection_rates": selection_rates,
        "note": (
            "Group labels are researcher-export only. Pathwise does not collect "
            "demographic fields to play."
        ),
    }
