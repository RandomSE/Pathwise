# Pathwise psychometrics (face validity and internal reliability)

This document is an operational-definition register, not a validation study.
Pathwise scores describe in-game behavior on this crossing task. They do not
claim construct, convergent, or criterion validity. They do not predict
job performance.

Register version: see `analytics/validity_register.py` (`VALIDITY_REGISTER_VERSION`).
Role catalog version: see `analytics/role_catalog.py` (`ROLE_CATALOG_VERSION`).

## Three-layer model

1. Continuous in-game traits (0-100, FLAG_INSUFFICIENT when data are missing).
2. Cosmetic archetypes for the game UI only.
3. Catalog target similarity (weighted distance to unvalidated directional
   priors). Similarity is omitted below 0.50 coverage.

Hiring views must read `traits` and `role_fits`, not `primary_archetype`.

## Dimension register

Each dimension is labeled as in-game behavior. Formulas and inclusion rules
live in `analytics/validity_register.py` and `analytics/trait_scoring.py`.

### In-game risk propensity

- Operational definition: rate of risky events, reasonable-risk events, and
  `cross_on_red` actions per observed second.
- Confounds: game literacy, visual time-to-arrival, modifier conditions,
  frustration, spawn luck.
- Not: DOSPERT, Big Five, a clinical scale, or job-risk prediction.

### In-game decision tempo

- Operational definition: go/no-go after curb arrival, using
  `commit_latency_s` (or a residual of `commit_time_s` minus motor/path
  travel). Raw approach-to-cross time is not cognitive tempo.
- Confounds: motor speed if curb arrival was not logged, legal light waits,
  lag, old/rain movement penalties, game literacy.
- Not: DOSPERT, Big Five, a clinical scale, or personality "decisiveness."

`motor_tempo` is a diagnostic split (approach travel / path length). It is
not a seventh hiring trait.

### In-game deliberation depth

- Operational definition: hesitation seconds and hesitation count at
  crossings. Freezing is not tempo.
- Confounds: motor stun, waiting for green, frustration, time pressure.
- Not: Need for Cognition, DOSPERT, Big Five, or a clinical scale.

### In-game rule adherence

- Operational definition: green vs red crossing mix, with a long-session
  zero-risky bonus.
- Confounds: lawless (signals off), visual TTA, frustration, time-pressure
  bonuses.
- Not: conscientiousness, DOSPERT, Big Five, or a clinical scale.

### In-game adaptive planning

- Operational definition: recovered vs failed replans after backtracks,
  plus a success/collision adjustment.
- Confounds: map topology, early collision, highway/lawless chaos, literacy.
- Not: a psychometric planning construct, DOSPERT, Big Five, or a clinical
  scale.

### In-game composure

- Operational definition: within-round recovery latency after backtrack or
  risk_event to the next advance/commit.
- Between-round variance of the other five traits is a reliability statistic,
  not composure.
- Confounds: motor stun, lag, frustration, round-ending collisions.
- Not: a clinical affect scale, DOSPERT, or Big Five.

## Internal reliability

With multiple rounds, Pathwise persists a reliability report:

- per-trait SD across rounds
- Spearman-Brown / ICC(1) / Cronbach alpha when a persons-by-rounds matrix
  exists (simulator battery or researcher export)
- FLAG_INSUFFICIENT when too few observations

These coefficients are computed from actual session payloads. They are not
1.0 by construction. They are not construct validity.

A checked-in recovery study lives in `tests/test_psychometric_reliability.py`.
It uses `analytics.session_simulator` policies (high/low risk, fast/slow
commit, rule-follower vs red-crosser, motor-slow vs motor-fast).

## Fairness scaffolding

No demographic fields are required to play. `analytics.fairness` can compute
group mean differences and an adverse-impact ratio only when a researcher
export supplies an optional group label.

This tool is not authorized for employment decisions until a fairness review
on real applicants exists.

## Experimental factors vs demographics

Modifiers such as `lag`, `old`, `time_pressure`, `highway`, and `lawless`
are experimental factors, not demographic proxies. They must be recorded on
the session so they are not silently confounded with traits. When a person
has both baseline and modifier rounds, `within_person_contrasts` stores
trait deltas. Those deltas are research fields, not a blended composure or
tempo score.

## What this product still denies

- construct_validity: false
- convergent_validity: false
- criterion_validity: false
- predicts_job_performance: false
- authorized_for_employment_decisions: false

External convergent/criterion work is a study protocol only. See
`docs/COMPLIANCE.md`. Do not treat that protocol as implemented evidence.
