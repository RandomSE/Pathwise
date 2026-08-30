# Pathwise scoring compliance framing

This is product and research framing. It is not legal advice.

## Employment use is not authorized

Once Pathwise scores influence a hiring outcome, jurisdiction-specific
obligations can apply. In the United States this can include the Uniform
Guidelines on Employee Selection Procedures (adverse-impact analysis,
disclosure, and related recordkeeping). Other jurisdictions have their own
testing, privacy, and automated-decision rules.

This tool is not authorized for employment decisions until a fairness review
on real applicants exists.

The game client does not collect demographic fields. Optional group labels
exist only on researcher exports for fairness scaffolding
(`analytics.fairness`).

## Validity payload lock

Product copy and the `validity` payload must keep all of the following false
until an external study says otherwise:

- construct_validity
- convergent_validity
- criterion_validity
- predicts_job_performance
- authorized_for_employment_decisions

Do not add fake study results. Internal reliability from multi-round Pathwise
logs is not construct, convergent, or criterion validity.

## Modifiers are experimental factors

`lag`, `old`, `time_pressure`, `highway`, `lawless`, `rainy_roads`, and
similar session modifiers are experimental conditions. They are not
demographic proxies. They must be recorded so trait scores are not silently
confounded with the condition.

## Convergent / criterion study protocol (research only)

This protocol is not implemented evidence. It is a one-page design for an
out-of-band study.

### Population

Adult volunteers who play Pathwise and separately complete external scales.
Do not collect protected-class data in the game client. If a fairness
analysis is planned, collect group labels only on a consented researcher
export.

### External measures (examples, not bundled)

- Risk: DOSPERT or a domain-specific risk inventory.
- Tempo / impulsivity: BIS-11 or a similar delay-discounting / impulsivity
  scale.
- Optional job outcomes: supervisor ratings or objective task metrics
  collected later, never inferred from Pathwise alone.

### Design

1. Each participant completes at least four Pathwise rounds with modifiers
   recorded.
2. Administer external scales in a separate sitting, counterbalanced.
3. Pre-register: Pathwise trait vector, flags, reliability report, modifier
   list, and the external scale totals.
4. Primary analysis: disattenuated correlations between matching in-game
   traits and external scales. Report confidence intervals. Do not treat a
   significant correlation as job-performance evidence.
5. Optional criterion arm: after a pre-registered delay, correlate Pathwise
   scores with job outcomes in a specific role. This arm is independent of
   shipping the game.
6. Fairness arm: if group labels exist on the export, compute group mean
   differences and adverse-impact ratios using `analytics.fairness`. Motor
   speed and game literacy are recorded confounds, not group membership.

### Decision rule for product claims

Only after the pre-registered study is complete and reviewed may any of
construct_validity, convergent_validity, criterion_validity, or
predicts_job_performance be set true. Until then the product must keep
those flags false and must keep the employment banner visible wherever
`role_fits` are shown.
