# Task 8 Report: Manual and Automatic Profile Extraction

## Implemented

- Added `src/rollform_extractor/profile_detector.py`.
- Added `src/rollform_extractor/feature_extractor.py`.
- Added focused detector tests in `tests/test_profile_detector.py`.
- Added focused feature and fingerprint tests in `tests/test_feature_extractor.py`.

## TDD Evidence

- Red: `pytest tests/test_profile_detector.py tests/test_feature_extractor.py -q`
  - Failed during collection with missing `rollform_extractor.profile_detector` and `rollform_extractor.feature_extractor`.
- Red: `pytest tests/test_profile_detector.py::test_arc_connected_to_line_stays_in_same_profile_chain -q`
  - Failed because exact ARC endpoints were not used when sampled geometry was absent.
- Green: `pytest tests/test_profile_detector.py tests/test_feature_extractor.py -q`
  - `13 passed in 0.11s`.
- Full: `pytest -q`
  - `105 passed in 20.17s`.

## Notes

- Manual profile handle overrides take precedence and produce `manual_override` profiles.
- Automatic selection groups station-owned connected chains, de-duplicates repeated handles, scores layer/type/length/continuity/consecutive-length evidence, and routes ambiguous or broken contours to review warnings.
- Feature extraction uses exact normalized primitives for line, polyline, arc, and circle length; sampled points remain comparison geometry.
- Fingerprints include developed length, width, height, bend radii, and canonical sampled points, with mirrored fingerprints normalized into the same digest.

## Deliberate Limits

- The scorer is deterministic and conservative, but still intentionally small. Add richer roller-centre/topology evidence when roller detection lands.
