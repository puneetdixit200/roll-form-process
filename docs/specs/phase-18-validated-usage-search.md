# Phase 18: Engineer-Validated Historical Roller Usage Search

## Purpose

Phase 18 creates a trusted evidence layer around Phase 17 roller-design
recognition. It supports independent engineer labels, explicit adjudication,
immutable evaluation datasets, transparent threshold evaluation, and promotion
of adjudicated design matches into a historical design-usage ledger.

The system identifies reusable roller designs in historical evidence. It never
identifies or assigns a physical roller asset automatically.

## Terms and boundary

- A **roller design** is a reusable engineering identity.
- A **physical roller asset** is a manufactured item with serial, condition,
  location, wear, or regrind history.
- A **drawing occurrence** is a roller-like object extracted from CAD.
- A **candidate recognition** is a Phase 17 model relationship.
- A **confirmed historical usage** is an engineer-approved relationship between
  an occurrence and a roller design.

Phase 18 does not recommend tooling, assign assets, establish current
availability or safety, generate sequences, or make manufacturability claims.
Every operational result is labelled as historical design evidence only.

## Label and review model

Each evaluation case is project-scoped and stores the immutable Phase 17 input
hash and inventory snapshot hash. Assertions have one of:

`MATCH_DESIGN`, `NO_CATALOG_MATCH`, `NOT_A_ROLLER`,
`INSUFFICIENT_DRAWING_EVIDENCE`, or `UNRESOLVED`.

`MATCH_DESIGN` requires a design ID, reviewer, reason, and evidence. A
`NO_CATALOG_MATCH` does not take a design ID and means that no design in the
recorded inventory snapshot matched. `NOT_A_ROLLER` and
`INSUFFICIENT_DRAWING_EVIDENCE` are evaluated separately from recognition
accuracy. Existing Phase 17 positive labels remain historical model-review
records; they are not silently promoted to ground truth.

Two independent assertions are required for a resolved case. Agreement is
recorded explicitly. Conflicts go to adjudication, where an adjudicator may
confirm either reviewer, select another design, confirm a negative outcome, or
exclude/defer the case. Assertions and adjudications are append-only and
superseding records preserve the prior decision.

## Dataset governance

Datasets are versioned, content-hashed, project-scoped, and classified as
`SYNTHETIC`, `ENGINEER_LABELLED`, or `PRODUCTION_CONFIRMED`. Lifecycle states
are `DRAFT`, `IN_REVIEW`, `LOCKED`, `APPROVED_FOR_CALIBRATION`,
`APPROVED_FOR_VALIDATION`, and `RETIRED`.

Calibration, validation, and holdout splits are deterministic and grouped to
prevent the same project or drawing family from leaking across splits. A
locked version cannot be edited; corrections create a new version. Unresolved
and excluded cases do not enter final accuracy metrics.

## Threshold evaluation

Threshold evaluation is a transparent, deterministic calculation over a named
dataset and configuration. It reports top-k retrieval, reciprocal rank,
appropriate abstention, coverage, selective risk, false-high-confidence cases,
no-match behavior, subgroup breakdowns, and sample-size warnings. Evaluation
never activates or approves a profile. An engineer must explicitly approve a
profile with its configuration hash, dataset hashes, metrics, notes, and
limitations. Recognition runs continue using their recorded profile or raw
configuration until explicitly selected.

## Confirmed historical usage

Only an adjudicated `MATCH_DESIGN` in a locked or approved dataset may be
promoted. Promotion verifies project and occurrence identity, exact input hash,
design/revision ownership, and absence of unresolved conflict. The resulting
record contains no automatic `roller_asset_id`. Supersession and revocation
are explicit audited actions.

Re-extraction preserves confirmed records. An unchanged input hash preserves
the relationship; a changed or removed occurrence marks it `STALE_SOURCE` and
places it back into review without transferring the confirmation silently.

## Historical relationships and search

Snapshots derive descriptive relationships such as design usage by role,
station, profile context, assembly, project, co-occurrence, and reliable
station order. Support is based on distinct projects by default, duplicate
occurrences do not inflate project support, and low-support relationships are
marked. Synthetic and unresolved evidence are excluded from operational search
by default. Search results are classified as confirmed fact, engineer-labelled
evidence, synthetic fixture, model candidate, unresolved review, or stale
confirmation.

Association is not compatibility, recommendation, tooling reuse, or physical
asset availability.

## Provenance, privacy, and determinism

The lineage is preserved as:

`CAD handle → occurrence → recognition input hash → candidate revision → label
assertions → adjudication → dataset hash → confirmed usage → relationship
snapshot/search result`.

All writes create audit/provenance information. Exports include schema and
algorithm versions, configuration and dataset hashes, inventory snapshot hash,
and deterministic ordering. Synthetic fixtures contain no customer CAD,
factory inventory, serial numbers, credentials, or private paths.

## Phase 19 handoff

Only after sufficient engineer-labelled data, approved thresholds, reliable
station/assembly context, and minimum support rules exist may Phase 19 add
evidence-backed historical tooling-set candidate analysis. Phase 19 must also
begin as explainable retrieval and must not automatically approve tooling use.
