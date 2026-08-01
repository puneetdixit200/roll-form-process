# Phase 16: Physical Roller Inventory Knowledge Base

Status: implementation specification. Phase 16 is an offline inventory knowledge base only. It does not perform automatic roller recognition, tooling recommendation, forming-sequence generation, or manufacturability prediction.

## Domain boundaries

The model deliberately separates five concepts:

1. **Roller design** — the reusable engineering identity and intended geometry concept. A design has a stable permanent design ID and may have aliases.
2. **Physical roller asset** — an individually owned or controlled item. Multiple assets may implement one design and each asset has its own condition, location, and history.
3. **Geometry revision** — a measured or supplied geometry snapshot for a design or asset. An asset may have multiple revisions after measurement, wear, repair, or regrinding.
4. **Drawing occurrence** — a roller occurrence detected in a historical drawing/project. It may reference a design candidate, but it references a physical asset only when production or engineer-confirmed evidence identifies that exact asset.
5. **Assembly/tooling set** — a named set of design or asset members used together. Existing `assembly_templates` and project usage remain authoritative for historical extraction records.

The existing `roller_catalog`, `roller_occurrences`, `project_roll_usage`, `assembly_templates`, `geometry_fingerprints`, and `result_provenance` tables remain in the same database. New inventory tables are additive and preserve legacy IDs and foreign keys. Legacy catalog rows are represented by `LEGACY-<roller_catalog_id>` design records when the inventory schema is first upgraded; no historical project row is deleted or rewritten.

## Tables

The versioned inventory tables are `roller_designs`, `roller_assets`, `roller_geometry_revisions`, `roller_aliases`, `roller_locations`, `roller_compatibility`, `roller_condition_history`, `roller_regrind_history`, `roller_file_assets`, `roller_import_batches`, `roller_import_rows`, `roller_review_decisions`, and `roller_audit_events`.

`roller_designs` owns permanent design identity. `roller_assets.design_id` is required for a known asset; `roller_geometry_revisions` can be attached to a design and optionally an asset. Alias uniqueness is enforced on normalized aliases. Conditions, locations, regrinds, files, import rows, reviews, and audit events retain their source and timestamp.

## Unit-safe geometry

Every dimensional record retains the original value and unit, optional normalized millimetres, measurement method, source, confidence, and verification status. An unknown or unconfirmed unit may be stored, but it cannot support a verified dimensional claim or dimensional matching. Fingerprints are versioned with algorithm version, configuration hash, input-file hash, physical-dimension fingerprint, and scale-normalized shape fingerprint.

## Staged import contract

CSV and XLSX imports are immutable staged batches. The source file is SHA-256 hashed, original rows are retained, headers are normalized, unknown values become explicit nulls, and accepted normalized values are separate from source JSON. Required IDs and values are validated. Duplicate permanent IDs, alias collisions, incompatible unit claims, and conflicting verified data produce review-required rows and rejected-row reasons; they never silently overwrite verified values.

An identical source hash is idempotent and returns the existing batch. Accepted rows are committed in one transaction. Rejected rows remain queryable and are exportable with reasons. Review decisions are explicit records, not implicit importer behavior.

Supported commands are `roller-inventory-template`, `roller-inventory-validate`, `roller-inventory-import`, `roller-inventory-export`, and `roller-inventory-stats`.

## Phase boundary and matching safety

Exact permanent IDs and explicit aliases may be resolved to design records. Fingerprint or similarity results are candidate suggestions only. Unknown units prevent dimensional comparison. Phase 16 must not emit a production asset claim, reuse percentage, recommendation, or automatic tooling match.
