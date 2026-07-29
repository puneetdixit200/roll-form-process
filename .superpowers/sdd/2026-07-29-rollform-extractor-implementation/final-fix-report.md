# Final Fix Report

## Changes

- Made expanded block entity ledger handles unique per insert occurrence while preserving the original DXF handle in `source_handles` and primitive provenance.
- Added config-path support to extraction and reprocess, including `extract --config` and `reprocess --config`.
- Loaded `review/manual_overrides.json` during pipeline runs and passed overrides through station, profile, and roller detection.
- Matched catalog similarity against detector dimension aliases: `outer_diameter_mm`, `bore_diameter_mm`, and `width_mm`.
- Removed the unsupported `--stage` CLI surface instead of advertising choices that the pipeline rejects.

## Regression Tests

- `tests/test_entity_parser.py::test_repeated_insert_expansion_gives_each_occurrence_a_unique_ledger_handle`
- `tests/test_pipeline.py::test_reprocess_applies_project_manual_overrides`
- `tests/test_pipeline.py::test_extract_uses_request_config_path`
- `tests/test_cli.py::test_cli_reprocess_accepts_config_path`
- `tests/test_catalog.py::test_similarity_matches_detector_dimension_aliases`

## Verification

- Red run: the focused regression set failed on the missing behavior before production edits.
- Focused green run: `5 passed in 4.97s`.
- Full suite: `176 passed in 45.79s`.
