# Canonical Extraction Reliability Remediation

## Scope

This repair phase makes the extraction artifacts internally consistent and
explicitly blocks trusted-corpus use until engineering review is complete. It
does not implement retrieval, embeddings, generative AI, tooling selection, or
production approval.

## Defect and correction map

| Symptom | Root cause | Correction | Acceptance |
|---|---|---|---|
| Manifest mismatches | Generated report files were changed after manifest creation | Manifest is generated last; validator reports expected/actual SHA-256 and size | zero covered-file mismatches |
| 12 features for 19 passes | A manually derived Flower Analysis viewer was inserted into report data | Only canonical `CompositeFlowerRecord` values enter authoritative project/report/database data; rejected regions are separate evidence | accepted passes equal feature sets |
| Fake Composite Flower 02 | Presentation data was promoted to a domain flower | Composite eligibility is checked before persistence/export | no rejected region in accepted flower tables |
| First-match station alignment | Report code used `next(iter(...))` | Dedicated monotonic dynamic-programming alignment preserves all candidates and gaps | global monotonic result |
| FB8B/FB69 order risk | Inferred order was displayed as if aligned | Evidence packet records source handles, candidates, orders and required engineer decision | no “confirmed” label without review |
| Repeated stations | Fingerprint-like identity could collapse occurrences | Alignment operates on ordered station occurrences, not geometry fingerprints | S14/S15/S16 remain distinct |
| Length ambiguity | Closed outline and neutral path were both called developed length | Qualified outline and neutral fields are exported separately | labels and schemas distinguish them |
| Artificial zero error | Neutral generated length was assigned expected length | Generated length is measured from neutral points; expected is independent or null | perturbation changes error |
| Absolute comparison coordinates | BBox/centroid placement fields entered scalar vectors | Schema v2 replaces them with normalized invariant summaries; audit geometry retains placement | forbidden-field validator passes |
| Review-only patching | Review application edited report JSON/HTML directly | Review application validates then regenerates through an atomic temporary project | SQLite, exports, report and manifest agree |
| Corpus ambiguity | Structural validity was confused with engineering readiness | `dataset-readiness` requires units, order, deterministic regeneration and current schema | pilot remains BLOCKED until confirmed |

## Canonical eligibility

Only source regions with canonical detector profiles, stable source handles,
usable neutral geometry, complete features and no structural geometry failure
are accepted. Incomplete regions are persisted as
`RejectedCompositeRegion` audit evidence and never appear as accepted flowers,
features, transitions or frontend flower tabs.

## Review and order

Inferred order is retained separately from engineer-confirmed order. The
FB8B/FB69 mapping is not hard-coded; the generated evidence packet presents
the candidate station, station order, geometry evidence and recommended review
action. Until a signed decision exists, order remains
`ENGINEER_CONFIRMATION_REQUIRED`.

## Units and readiness

Drawing-unit values are preserved. Millimetre values and dimensional
eligibility remain null/false until a valid engineer-confirmed conversion is
present. Shape-only normalized descriptors are not trusted retrieval data.

## Compatibility

Pass feature schema is version 2. Schema-v1 records are not treated as
equivalent to v2 comparison vectors. Legacy structured audit fields may remain
for backward-compatible rendering, but forbidden placement fields cannot enter
comparison vectors.
