# Task 12 Report: Batch Processing, Resume, and Master Database

## Implemented

- Added `rollform_extractor.batch` with `BatchRequest`, `BatchSummary`, `batch_extract`, `aggregate_master`, `validate_batch`, and `write_batch_report`.
- Batch extraction discovers DXF/DWG inputs, isolates per-file failures, writes `batch_ledger.json` after each file, and resumes unchanged successful projects when requested.
- Resume invalidates on source hash or configuration hash changes and revalidates existing project artifacts before skipping.
- Master aggregation writes `master/master_rollform.sqlite`, `projects.csv`, `rollers.csv`, and `extraction_dashboard.html`.
- Master rows preserve `source_database` and `source_project_id` provenance and refresh idempotently on repeated aggregation.
- Aggregation copies stations, profiles, roller occurrences, geometry fingerprints, assembly templates, roller catalog rows, project roll usage, and station transitions.
- Added CLI commands: `batch-extract`, `batch-validate`, and `batch-report`.

## TDD Evidence

- Red: `pytest tests/test_batch.py -q` failed with `ModuleNotFoundError: No module named 'rollform_extractor.batch'`.
- Red: `pytest tests/test_batch.py::test_batch_resume_skips_unchanged_successful_project -q` failed because skipped projects did not contribute artifact totals.
- Red: `pytest tests/test_batch.py::test_master_database_copies_catalog_fingerprints_templates_usage_and_transitions -q` failed because master catalog/usage/transition tables were missing.
- Green focused: `pytest tests/test_batch.py -q` -> 6 passed.
- Full suite: `pytest -q` -> 146 passed.
- Whitespace: `git diff --check` -> clean.

## Notes

- The batch layer intentionally reuses the existing single-project pipeline and validation logic.
- Master usage and transition tables keep source-local IDs instead of rebuilding every project-level relationship.

## Review Finding Fixes

- Excluded stale project databases from current batch master aggregation by rebuilding the master from successful current ledger entries.
- Preserved fallback aggregation for non-batch project output roots without a ledger.
- Added deterministic hash-qualified batch output roots when multiple input files share the same stem.
- Changed `batch-report` to refresh master aggregation before reading dashboard counts.

## Review Fix TDD Evidence

- Red: `pytest tests/test_batch.py -q` failed on stale failed rerun master count, same-stem path collision, and stale `batch-report` counts.
- Green focused: `pytest tests/test_batch.py -q` -> 9 passed.
- Full suite: `pytest -q` -> 149 passed.
- Whitespace: `git diff --check` -> clean.

## Remaining Issue Fixes

- `validate_batch()` now validates nested project outputs with `rglob("project.json")`, covering hash-qualified same-stem output directories.
- Batch reruns now mark previously successful ledger entries as `stale` when their source is no longer discovered, excluding them from current master aggregation.

## Remaining Fix TDD Evidence

- Red: `pytest tests/test_batch.py::test_batch_rerun_with_missing_source_excludes_stale_success_from_master tests/test_batch.py::test_validate_batch_checks_nested_project_outputs -q` failed on stale ledger status and missed nested validation.
- Green focused: same command -> 2 passed.
- Batch suite: `pytest tests/test_batch.py -q` -> 11 passed.
- Full suite: `pytest -q` -> 151 passed.
- Whitespace: `git diff --check` -> clean.

## Validation Filter Fix

- `validate_batch()` now excludes only paths under the root `output_root/master` batch artifact directory.
- Batch project output naming treats `master` as reserved, so a source named `master.dxf` is written to a hash-qualified nested project output instead of colliding with master artifacts.
- Fallback project database discovery uses the same root-master-only exclusion.

## Validation Filter TDD Evidence

- Red: `pytest tests/test_batch.py::test_validate_batch_checks_project_named_master -q` failed because `master.dxf` wrote into `output_root/master` and was skipped by validation.
- Green focused: same command -> 1 passed.
- Batch suite: `pytest tests/test_batch.py -q` -> 12 passed.
- Full suite: `pytest -q` -> 152 passed.
- Whitespace: `git diff --check` -> clean.
