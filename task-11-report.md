# Task 11 Report: Physical Roller Catalog and Assembly Templates

## Implemented

- Added `rollform_extractor.catalog` with conservative physical roller matching.
- Matching order is factory/permanent ID, drawing ID, exact fingerprint, then dimensional similarity.
- Any tied candidate set returns manual review with no automatic catalog identity.
- Similarity requires every provided catalog dimension to be present and within tolerance.
- Catalog matches carry condition, storage location, availability, and occurrence usage payloads.
- Added assembly template signatures from ordered roles, profile-relative centers, and known catalog IDs.
- Assembly template detection reuses existing template records by signature hash.

## Verification

- `pytest tests/test_catalog.py -q` -> 9 passed
- `pytest -q` -> 139 passed
