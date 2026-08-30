"""Headless logs.json-shaped sessions from scripted behavioral policies.

Policies have known latent tendencies. Per-round noise keeps reliability
below 1.0 by construction. Event shapes match production decision_logger
payloads (decision_sequence, crossing_attempts, summary).
"""

from __future__ import annotations

import random

POLICIES = {
    "high_risk": {
        "p_red": 0.30,
        "risky_per_crossing": 0.24,
        "reasonable_per_crossing": 0.15,
        "commit_latency_s": 0.9,
        "approach_travel_s": 1.4,
        "walk_px_s": 90.0,
        "hesitation_s": 0.2,
        "hesitation_count": 0,
        "p_backtrack": 0.15,
        "recovery_s": 1.2,
        "outcome": "success",
    },
    "low_risk": {
        "p_red": 0.04,
        "risky_per_crossing": 0.02,
        "reasonable_per_crossing": 0.08,
        "commit_latency_s": 1.1,
        "approach_travel_s": 1.5,
        "walk_px_s": 90.0,
        "hesitation_s": 0.4,
        "hesitation_count": 1,
        "p_backtrack": 0.08,
        "recovery_s": 1.0,
        "outcome": "success",
    },
    "fast_commit": {
        "p_red": 0.08,
        "risky_per_crossing": 0.05,
        "reasonable_per_crossing": 0.1,
        "commit_latency_s": 0.28,
        "approach_travel_s": 1.3,
        "walk_px_s": 95.0,
        "hesitation_s": 0.1,
        "hesitation_count": 0,
        "p_backtrack": 0.05,
        "recovery_s": 0.8,
        "outcome": "success",
    },
    "slow_commit": {
        "p_red": 0.08,
        "risky_per_crossing": 0.05,
        "reasonable_per_crossing": 0.1,
        "commit_latency_s": 5.8,
        "approach_travel_s": 1.3,
        "walk_px_s": 95.0,
        "hesitation_s": 0.2,
        "hesitation_count": 0,
        "p_backtrack": 0.05,
        "recovery_s": 0.8,
        "outcome": "success",
    },
    "rule_follower": {
        "p_red": 0.02,
        "risky_per_crossing": 0.0,
        "reasonable_per_crossing": 0.05,
        "commit_latency_s": 1.0,
        "approach_travel_s": 1.4,
        "walk_px_s": 90.0,
        "hesitation_s": 0.5,
        "hesitation_count": 1,
        "p_backtrack": 0.05,
        "recovery_s": 0.9,
        "outcome": "success",
    },
    "red_crosser": {
        "p_red": 0.82,
        "risky_per_crossing": 0.2,
        "reasonable_per_crossing": 0.1,
        "commit_latency_s": 0.8,
        "approach_travel_s": 1.3,
        "walk_px_s": 90.0,
        "hesitation_s": 0.15,
        "hesitation_count": 0,
        "p_backtrack": 0.08,
        "recovery_s": 1.1,
        "outcome": "success",
    },
    "motor_slow": {
        "p_red": 0.1,
        "risky_per_crossing": 0.05,
        "reasonable_per_crossing": 0.1,
        "commit_latency_s": 0.55,
        "approach_travel_s": 5.4,
        "walk_px_s": 28.0,
        "hesitation_s": 0.2,
        "hesitation_count": 0,
        "p_backtrack": 0.05,
        "recovery_s": 1.0,
        "outcome": "success",
    },
    "motor_fast": {
        "p_red": 0.1,
        "risky_per_crossing": 0.05,
        "reasonable_per_crossing": 0.1,
        "commit_latency_s": 0.55,
        "approach_travel_s": 0.55,
        "walk_px_s": 160.0,
        "hesitation_s": 0.2,
        "hesitation_count": 0,
        "p_backtrack": 0.05,
        "recovery_s": 1.0,
        "outcome": "success",
    },
}


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _noise(rng: random.Random, scale: float) -> float:
    return rng.gauss(0.0, scale)


def _person_latent(policy_name: str, seed: int) -> dict:
    rng = random.Random(seed ^ 0x9E3779B9)
    spec = POLICIES[policy_name]
    return {
        "p_red": _clip(spec["p_red"] + rng.gauss(0.0, 0.10), 0.0, 0.95),
        "risky_per_crossing": _clip(
            spec["risky_per_crossing"] + rng.gauss(0.0, 0.10), 0.0, 0.95
        ),
        "commit_latency_s": _clip(
            spec["commit_latency_s"] + rng.gauss(0.0, 0.28), 0.12, 8.0
        ),
        "approach_travel_s": _clip(
            spec["approach_travel_s"] + rng.gauss(0.0, 0.18), 0.2, 10.0
        ),
        "recovery_s": _clip(spec["recovery_s"] + rng.gauss(0.0, 0.2), 0.2, 6.0),
        "hesitation_s": spec["hesitation_s"],
        "hesitation_count": spec["hesitation_count"],
        "reasonable_per_crossing": spec["reasonable_per_crossing"],
        "walk_px_s": spec["walk_px_s"],
        "p_backtrack": spec["p_backtrack"],
        "outcome": spec["outcome"],
    }


def simulate_round(
    policy_name: str,
    *,
    seed: int,
    crossings: int = 4,
    latent: dict | None = None,
) -> dict:
    if policy_name not in POLICIES:
        raise KeyError(f"unknown policy {policy_name}")
    spec = latent or _person_latent(policy_name, seed)
    rng = random.Random(seed)
    decisions = []
    attempts = []
    t = 0.4
    risky = 0
    reasonable = 0
    red = 0
    green = 0
    backtracks = 0
    target_red = int(round(_clip(spec["p_red"] * crossings + rng.gauss(0.0, 0.35), 0, crossings)))
    target_risky = int(
        round(_clip(spec["risky_per_crossing"] * crossings + rng.gauss(0.0, 0.35), 0, crossings))
    )
    red_roads = set(rng.sample(range(crossings), target_red)) if target_red else set()
    risky_roads = set(rng.sample(range(crossings), target_risky)) if target_risky else set()
    for road in range(crossings):
        t += 1.2 + abs(_noise(rng, 0.25))
        if rng.random() < spec["p_backtrack"]:
            backtracks += 1
            decisions.append({"t": round(t, 3), "action": "backtrack"})
            recovery = _clip(spec["recovery_s"] + _noise(rng, 0.25), 0.2, 6.0)
            t += recovery
            decisions.append({"t": round(t, 3), "action": "advance"})
        latency = _clip(spec["commit_latency_s"] + _noise(rng, 0.12), 0.12, 8.0)
        travel = _clip(spec["approach_travel_s"] + _noise(rng, 0.16), 0.2, 10.0)
        path_px = _clip(travel * spec["walk_px_s"] + _noise(rng, 8.0), 12.0, 800.0)
        commit_time = travel + latency
        is_red = road in red_roads
        if is_red:
            red += 1
            decisions.append({"t": round(t, 3), "action": "cross_on_red"})
        else:
            green += 1
            decisions.append({"t": round(t, 3), "action": "cross_on_green"})
        if road in risky_roads:
            risky += 1
            decisions.append(
                {"t": round(t + 0.05, 3), "action": "risk_event", "risk_tier": "risky"}
            )
        elif rng.random() < spec["reasonable_per_crossing"]:
            reasonable += 1
            decisions.append(
                {
                    "t": round(t + 0.05, 3),
                    "action": "risk_event",
                    "risk_tier": "reasonable",
                }
            )
        t += latency
        attempts.append(
            {
                "road_index": road,
                "commit_time_s": round(commit_time, 2),
                "commit_latency_s": round(latency, 2),
                "approach_travel_s": round(travel, 2),
                "approach_path_px": round(path_px, 1),
                "light_at_cross": "red" if is_red else "green",
                "t": round(t, 3),
            }
        )
    duration = max(t + 6.0, 22.0)
    hesitation_s = _clip(spec["hesitation_s"] + abs(_noise(rng, 0.08)), 0.0, 6.0)
    hesitation_count = max(0, int(round(spec["hesitation_count"] + _noise(rng, 0.3))))
    return {
        "outcome": spec["outcome"],
        "duration_s": round(duration, 2),
        "crossings": crossings,
        "collisions": 0,
        "risk_events": risky,
        "risky_risk_events": risky,
        "reasonable_risk_events": reasonable,
        "failure_reason": None,
        "modifiers": [],
        "decision_sequence": decisions,
        "crossing_attempts": attempts,
        "hesitation_events": [],
        "summary": {
            "total_backtracks": backtracks,
            "total_hesitation_s": round(hesitation_s, 2),
            "hesitation_count": hesitation_count,
            "quick_commits": sum(1 for item in attempts if item["commit_time_s"] < 1.2),
            "slow_commits": sum(1 for item in attempts if item["commit_time_s"] > 4.0),
            "decision_count": len(decisions),
        },
    }


def simulate_session_log(
    policy_name: str,
    *,
    seed: int,
    n_rounds: int = 6,
    crossings: int = 6,
) -> dict:
    latent = _person_latent(policy_name, seed)
    rounds = []
    for index in range(n_rounds):
        session = simulate_round(
            policy_name,
            seed=seed * 1009 + index * 17 + 3,
            crossings=crossings,
            latent=latent,
        )
        rounds.append(
            {
                "round": index + 1,
                "outcome": session["outcome"],
                "session": session,
            }
        )
    last = rounds[-1]["session"] if rounds else {}
    return {
        "outcome": last.get("outcome"),
        "session": last,
        "rounds": rounds,
        "num_rounds": n_rounds,
        "simulator_policy": policy_name,
        "simulator_seed": seed,
    }
