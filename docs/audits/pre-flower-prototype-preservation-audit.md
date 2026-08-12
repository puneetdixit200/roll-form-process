# Pre-flower-prototype preservation audit

## Baseline

- Base branch: `main`
- Starting SHA: `c428714507eda2d9f6a98ee35280a13875b8c0e3`
- Prototype branch: `feature/history-constrained-flower-prototype`
- Existing release tags include `phase-15-v1`, `phase-16-v1`, `phase-17-v1`, and `phase-18-v1`.
- Existing Python baseline: 235 passed.
- Private source drawings were hashed read-only and are not inside the repository.

## Preserved surface

The existing Phase 15–18 extraction, inventory, recognition, validation,
historical-usage, CLI, API, frontend, database, and report systems remain the
base surface. The prototype uses additive modules and tables only. Existing
tables and release records are not renamed, dropped, or rewritten.

## Private source inventory

The private source files are represented in committed evidence only by stable
private identifiers and aggregate counts. Their filenames, absolute paths,
converted DXF files, previews, and source geometry are excluded from public
artifacts and Git.

## Expected prototype additions

- Additive flower-prototype dataset and generation tables.
- Deterministic retrieval, alignment, generation, forward-validation, and
  hidden-pass benchmark services.
- Explicit private-data hygiene checks.
- New CLI/API/frontend/report surfaces without removing prior functionality.

The post-implementation audit will be generated separately and compared with
this record for unexpected removals.
