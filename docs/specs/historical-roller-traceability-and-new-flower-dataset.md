# Historical roller traceability and new flower dataset

## Contract

This additive feature preserves historical source provenance from a generated
visual pass to every matching historical flower/pass and roller design origin.
The unit of identity is `(dataset_hash, flower_id, pass_id, role, design_id,
geometry_revision_id)`, represented by a deterministic `hsr-*` reference ID.
No physical roller asset is inferred or assigned.

## Evidence model

Roller evidence is grouped only for ranking. Each grouped design candidate keeps
all distinct `supporting_origins`, `supporting_match_ranks`, and a
`best_support_origin`. “Top 3 support” is a count of independent matched
historical origins, not a probability or compatibility claim. Direct project
evidence and historical evidence remain separate in the explanation payload.

## Safe historical source navigation

The historical source API returns redacted IDs, dimensions, derived points and
quality metadata. It never returns source filenames, filesystem paths, raw CAD,
or asset assignments. Pass order is deterministic by inferred order and pass
ID. The PNG preview remains a derived same-origin convenience.

## Dataset compatibility and governance

Existing dataset JSON remains readable. New station-level evidence may be
stored under additive `roller_station_evidence` data and is optional for old
datasets. Dataset hashes include schema and algorithm versions. Private source
files stay in the local private staging area and are excluded from exports and
Git.

## Operational boundary

This is historical design evidence only. It does not recommend tooling,
identify a physical asset, establish availability/condition, or approve
manufacturing. Production use requires engineer-labelled evidence and approved
thresholds; synthetic/private prototype metrics are not production metrics.

## Phase 19 handoff

The next phase may add broader evidence-backed historical tooling-set analysis
only after multiple anonymized flowers, reliable station/assembly context, and
engineer-reviewed support thresholds exist. It must initially remain retrieval
and review only.
