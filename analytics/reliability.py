"""Internal reliability from actual multi-round session payloads.

Coefficients describe score stability in Pathwise logs. They are not
construct, convergent, or criterion validity.
"""

from __future__ import annotations

import statistics

TRAIT_KEYS = (
    "risk_propensity",
    "decision_tempo",
    "deliberation_depth",
    "rule_adherence",
    "adaptive_planning",
    "composure",
)
FLAG_OK = "ok"
FLAG_INSUFFICIENT = "insufficient_data"
MIN_ROUNDS_FOR_COEFFICIENT = 2
MIN_PERSONS_FOR_GROUP_COEFFICIENT = 3


def spearman_brown(r: float, n_fold: int = 2) -> float:
    if r is None or n_fold <= 0:
        raise ValueError("spearman_brown requires a correlation and n_fold > 0")
    return (n_fold * r) / (1.0 + (n_fold - 1.0) * r)


def _column_variance(matrix: list[list[float]], col: int) -> float:
    values = [row[col] for row in matrix]
    if len(values) < 2:
        return 0.0
    return statistics.pvariance(values)


def cronbach_alpha(items: list[list[float]]) -> float | None:
    """Cronbach alpha for persons x items. None if variance is degenerate."""
    if not items or len(items) < 2:
        return None
    k = len(items[0])
    if k < 2 or any(len(row) != k for row in items):
        return None
    item_vars = [_column_variance(items, col) for col in range(k)]
    totals = [sum(row) for row in items]
    if len(set(round(v, 8) for v in totals)) < 2:
        return None
    total_var = statistics.pvariance(totals)
    if total_var <= 0:
        return None
    alpha = (k / (k - 1.0)) * (1.0 - (sum(item_vars) / total_var))
    if alpha != alpha:  # NaN
        return None
    return max(0.0, min(1.0, alpha))


def icc1(items: list[list[float]]) -> float | None:
    """ICC(1) one-way random, persons x ratings. None if degenerate."""
    if not items or len(items) < 2:
        return None
    k = len(items[0])
    if k < 2 or any(len(row) != k for row in items):
        return None
    n = len(items)
    grand = sum(sum(row) for row in items) / (n * k)
    person_means = [sum(row) / k for row in items]
    ss_b = k * sum((mean - grand) ** 2 for mean in person_means)
    ss_w = 0.0
    for row, mean in zip(items, person_means):
        ss_w += sum((value - mean) ** 2 for value in row)
    df_b = n - 1
    df_w = n * (k - 1)
    if df_b <= 0 or df_w <= 0:
        return None
    msb = ss_b / df_b
    msw = ss_w / df_w
    denom = msb + (k - 1.0) * msw
    if denom <= 0:
        return None
    icc = (msb - msw) / denom
    if icc != icc:
        return None
    return max(0.0, min(1.0, icc))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs)
    den_y = sum((y - mean_y) ** 2 for y in ys)
    if den_x <= 0 or den_y <= 0:
        return None
    return num / (den_x * den_y) ** 0.5


def split_half_spearman_brown(items: list[list[float]]) -> float | None:
    if not items:
        return None
    k = len(items[0])
    if k < 2:
        return None
    odd = [statistics.mean(row[0::2]) for row in items]
    even = [statistics.mean(row[1::2]) for row in items]
    r = _pearson(odd, even)
    if r is None:
        return None
    r = max(-0.999, min(0.999, r))
    return max(0.0, min(0.999, spearman_brown(r, n_fold=2)))


def _round_values(per_round: list[tuple[dict, dict]], key: str) -> list[float]:
    values = []
    for traits, flags in per_round:
        if flags.get(key) == FLAG_OK and traits.get(key) is not None:
            values.append(float(traits[key]))
    return values


def session_reliability(per_round: list[tuple[dict, dict]]) -> dict:
    """Stability for one candidate across rounds. Flags sparse traits."""
    n_rounds = len(per_round)
    traits = {}
    for key in TRAIT_KEYS:
        values = _round_values(per_round, key)
        n_ok = len(values)
        if n_ok < MIN_ROUNDS_FOR_COEFFICIENT:
            traits[key] = {
                "n_ok": n_ok,
                "n_rounds": n_rounds,
                "sd_across_rounds": None,
                "spearman_brown": None,
                "cronbach_alpha": None,
                "icc1": None,
                "flag": FLAG_INSUFFICIENT,
            }
            continue
        sd = statistics.pstdev(values) if len(values) >= 2 else 0.0
        traits[key] = {
            "n_ok": n_ok,
            "n_rounds": n_rounds,
            "sd_across_rounds": round(sd, 4),
            "spearman_brown": None,
            "cronbach_alpha": None,
            "icc1": None,
            "flag": FLAG_OK,
        }
    return {
        "n_rounds": n_rounds,
        "kind": "within_person_round_stability",
        "claim": "internal_consistency_only",
        "traits": traits,
    }


def _sessions_from_person_log(payload: dict) -> list[dict]:
    from analytics.trait_scoring import _sessions_from_log

    return _sessions_from_log(payload)


def reliability_report(person_logs: list[dict], score_fn=None) -> dict:
    """Multi-person reliability from actual session payloads."""
    from analytics.trait_scoring import _score_round_traits

    def _round_pair(session: dict) -> tuple[dict, dict]:
        if score_fn is not None:
            scored = score_fn(session)
            return scored.get("traits") or {}, scored.get("trait_flags") or {}
        return _score_round_traits(session)[:2]

    people_rows: dict[str, list[list[float]]] = {key: [] for key in TRAIT_KEYS}
    sd_means = {key: [] for key in TRAIT_KEYS}
    n_ok_means = {key: [] for key in TRAIT_KEYS}

    for payload in person_logs:
        sessions = _sessions_from_person_log(payload)
        per_round = [_round_pair(session) for session in sessions]
        for key in TRAIT_KEYS:
            values = _round_values(per_round, key)
            n_ok_means[key].append(len(values))
            if len(values) >= 2:
                sd_means[key].append(statistics.pstdev(values))
            if values:
                people_rows[key].append(values)

    min_len = {}
    matrices = {}
    for key, rows in people_rows.items():
        if len(rows) < MIN_PERSONS_FOR_GROUP_COEFFICIENT:
            matrices[key] = []
            continue
        width = min(len(row) for row in rows)
        if width < MIN_ROUNDS_FOR_COEFFICIENT:
            matrices[key] = []
            continue
        matrices[key] = [row[:width] for row in rows]
        min_len[key] = width

    traits = {}
    for key in TRAIT_KEYS:
        matrix = matrices.get(key) or []
        alpha = cronbach_alpha(matrix) if matrix else None
        icc = icc1(matrix) if matrix else None
        sb = split_half_spearman_brown(matrix) if matrix else None
        if sb is None and icc is not None and matrix:
            sb = max(0.0, min(0.999, spearman_brown(icc, n_fold=len(matrix[0]))))
        n_ok_mean = (
            sum(n_ok_means[key]) / len(n_ok_means[key]) if n_ok_means[key] else 0.0
        )
        sd_mean = sum(sd_means[key]) / len(sd_means[key]) if sd_means[key] else None
        enough = (
            len(matrix) >= MIN_PERSONS_FOR_GROUP_COEFFICIENT
            and n_ok_mean >= MIN_ROUNDS_FOR_COEFFICIENT
            and (sb is not None or icc is not None or alpha is not None)
        )
        traits[key] = {
            "n_persons": len(people_rows[key]),
            "n_ok_rounds_mean": round(n_ok_mean, 3),
            "sd_across_rounds_mean": None if sd_mean is None else round(sd_mean, 4),
            "cronbach_alpha": None if alpha is None else round(alpha, 4),
            "icc1": None if icc is None else round(icc, 4),
            "spearman_brown": None if sb is None else round(sb, 4),
            "n_aligned_rounds": min_len.get(key),
            "flag": FLAG_OK if enough else FLAG_INSUFFICIENT,
        }

    return {
        "kind": "multi_person_round_stability",
        "claim": "internal_consistency_only",
        "construct_validity": False,
        "n_persons": len(person_logs),
        "traits": traits,
    }
