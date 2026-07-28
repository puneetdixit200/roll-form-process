Task 10 implemented.

Added:
- `extract_project(ExtractionRequest) -> ExtractionSummary`
- `export_project(bundle, output_root) -> Manifest`
- `validate_project(project_path) -> ValidationReport`
- CLI commands: `inspect`, `extract`, `review`, `reprocess`, `validate`
- dynamic station export tree with station-local DXFs, CSV summaries, review queue, previews, report, manifest hashes, and SQLite persistence

Validation:
- focused: `pytest tests/test_exporters.py tests/test_pipeline.py tests/test_cli.py tests/test_validation.py -q`
- full: `pytest -q`
- result: 126 passed

Blocker fix:
- reprocess now preserves `project.sqlite`, run history, and completed review decisions
- validation reports `missing_source` when the original source path is gone
- `--stage profiles/rollers` is rejected with exit code 2 instead of ignored
- DXF export writes review warnings for primitives it cannot recreate

Validation:
- focused: `pytest tests/test_exporters.py tests/test_pipeline.py tests/test_cli.py tests/test_validation.py -q`
- full: `pytest -q`
- result: 130 passed
