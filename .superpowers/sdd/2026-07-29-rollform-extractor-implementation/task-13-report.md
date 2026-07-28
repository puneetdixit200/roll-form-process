### Task 13 Report: Production Metadata Import and Project Code Resolution

Implemented:
- `src/rollform_extractor/metadata_import.py`
- `import-metadata` CLI command in `src/rollform_extractor/cli.py`
- Focused coverage in `tests/test_metadata_import.py`
- CLI coverage in `tests/test_cli.py`

Behavior covered:
- Compound drawing names resolve to one drawing ID plus related project codes.
- CSV and XLSX imports store approved material, machine, production, customer, defect, notes, and COPRA fields.
- Missing values stay `None`.
- Rows resolve by explicit drawing ID before project code.
- Project-code imports can use existing `project_codes` rows or derived compound drawing codes.
- Metadata rows store source-file and row provenance in `project_metadata` and `result_provenance`.
- Unmatched and conflicting rows are returned in the import summary for review without overwriting existing values.

Verification:
- Red: `pytest tests/test_metadata_import.py -q` failed with missing `rollform_extractor.metadata_import`.
- Red: `pytest tests/test_cli.py::test_cli_import_metadata_uses_master_database -q` failed because `import-metadata` was not registered.
- Green focused: `pytest tests/test_metadata_import.py tests/test_cli.py::test_cli_import_metadata_uses_master_database -q` passed.
- Full: `pytest -q` passed, 159 tests.

Blocker fix:
- Added regression coverage for Task 12 master DB schema via `_create_master_schema()`.
- `import_metadata()` now supports the existing SQLAlchemy project DB path and raw sqlite master/project DB files.
- `import-metadata --master` no longer calls the ORM schema creator on Task 12 master DBs.
- Red: `pytest tests/test_metadata_import.py::test_import_metadata_accepts_task12_master_schema tests/test_cli.py::test_cli_import_metadata_uses_master_database -q` failed on sqlite/ORM schema mismatch.
- Green relevant: `pytest tests/test_metadata_import.py tests/test_cli.py tests/test_batch.py -q` passed, 23 tests.
- Full: `pytest -q` passed, 160 tests.
