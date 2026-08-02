# Phase 17: Explainable Roller Design Recognition

Status: implementation specification. This phase ranks candidate **roller
designs** for drawing occurrences. It does not identify physical assets,
recommend tooling, generate forming sequences, calculate reuse, or predict
manufacturability.

## Domain and input

The recognition input is a versioned immutable snapshot of one
`roller_occurrences` record: project and occurrence identity, station, role,
source handles/layers, original and normalized dimensions, geometry descriptor,
shape vector and missing mask, fingerprints, extraction confidence, quality
flags, and configuration hash. Missing dimensions remain `null` in structured
data; vector zero-fill is valid only with the corresponding missing mask.

The target identity is a `roller_design`, optionally qualified by one eligible
`roller_geometry_revision`. A physical `roller_asset` is never inferred by
similarity. An exact serial/production relationship may be stored as explicit
evidence, but it remains separate from design recognition.

Input quality is `COMPLETE`, `DIMENSIONS_ONLY`, `SHAPE_ONLY`, `PARTIAL`,
`INSUFFICIENT`, `UNKNOWN_UNITS`, or `INVALID`. Unknown units block dimensional
matching; shape-only matching is allowed only when explicitly configured.

## Eligibility and retrieval

Inventory revisions are classified as `VERIFIED_ELIGIBLE`,
`UNVERIFIED_CANDIDATE`, `UNKNOWN_UNITS_BLOCKED`, `SUPERSEDED`, `INVALID`, or
`REVIEW_REQUIRED`. Dimensional scoring requires known units, millimetre values,
verification, valid geometry, sufficient evidence, and a non-superseded
revision. Unknown-unit revisions can enter shape-only candidate retrieval only
when `allow_unknown_unit_shape_matching` is true.

Retrieval is deterministic: exact design ID, explicit verified alias, exact
verified physical fingerprint, and exact verified shape fingerprint are
reported as separate evidence. Then role/design-type/machine and verified
dimensional contradictions are applied as hard filters. A Python/SQLite scan is
sufficient for the expected inventory of about 500 designs; the initial pool
and final result limit are configurable.

## Scoring and abstention

For available components, the score is:

```text
sum(component_score * component_weight) / sum(available_component_weights)
```

Missing evidence is excluded from the denominator and reduces evidence
coverage; it is never treated as a mismatch. Components include exact
fingerprints, normalized shape distance, diameter, bore, width, groove and
curvature descriptors, role, and design type. Each score component records its
score, weight, availability, and reason. Scores and confidence are clamped to
`[0, 1]` and are reproducible from algorithm version, feature schema version,
configuration hash, inventory snapshot hash, and input hash.

The result status is one of `EXACT_IDENTIFIER_MATCH`,
`EXACT_VERIFIED_FINGERPRINT`, `HIGH_SIMILARITY_CANDIDATE`,
`MEDIUM_SIMILARITY_CANDIDATE`, `LOW_SIMILARITY_CANDIDATE`, `AMBIGUOUS`,
`NO_MATCH`, `INSUFFICIENT_EVIDENCE`, `UNKNOWN_UNITS`, or `INVALID_INPUT`.
The system abstains below the minimum score or evidence coverage, for invalid
geometry, unknown-unit dimensional requirements, role contradiction, no
eligible revision, or when the top-two margin is below the ambiguity margin.
Confidence combines score, evidence coverage, top-two margin, extraction
confidence, inventory confidence, and independent evidence-source count. A
high raw similarity with weak evidence cannot be high confidence.

## Review and provenance

Original rankings are immutable. Engineer actions are append-only review rows
with reviewer, timestamp, decision, selected design/revision, reason, notes,
and superseded review. `ACCEPT_CANDIDATE` confirms a design relationship only;
it does not assign a physical asset. Approved labels for evaluation are stored
in a separate explicit promotion path and never change weights automatically.

## Versioning and evaluation

Recognition feature schema and algorithm versions are explicit. Configuration
changes to weights, tolerances, or thresholds invalidate recognition runs;
report styling does not. Evaluation separates `SYNTHETIC`,
`ENGINEER_LABELLED`, and `PRODUCTION_CONFIRMED` datasets. Metrics include
top-k accuracy/recall, MRR, abstention, coverage, non-abstained accuracy,
false-high-confidence rate, margin, calibration where meaningful, and
breakdowns by role, units, quality, verification, and missing dimensions.

## Safety boundary and Phase 18 handoff

The UI and API must say “Candidate design recognition only. Physical asset
identity is not automatically determined.” There is no “use this roller”
action. Production recognition remains `NOT APPROVED` until an engineer-
labelled evaluation set and manufacturing thresholds are reviewed. Phase 18
may address engineer-approved historical relationship learning and operational
search, but only after that approval.
