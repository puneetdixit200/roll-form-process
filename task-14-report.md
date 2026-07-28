# Task 14 Report: Quantitative Benchmarking

## Implemented

- Added `rollform_extractor.benchmark.evaluate_benchmark(truth, extraction)`.
- Added contour Hausdorff and mean distance metrics.
- Added station count accuracy and mean station boundary IoU.
- Added profile ID accuracy by matched station.
- Added roller component recall and role accuracy.
- Added incorrect automatic claim rate.
- Added developed-length, bend-position, bend-angle, and bend-radius errors.
- Added pass/fail target reporting with dimensional thresholds marked provisional.
- Added benchmark fixture docs and JSON schema in `benchmarks/`.

## TDD Evidence

- Red: `pytest tests/test_benchmark.py -q`
  - Failed with `ModuleNotFoundError: No module named 'rollform_extractor.benchmark'`.
- Green: `pytest tests/test_benchmark.py -q`
  - `4 passed in 0.03s`.

## Verification

- Focused: `pytest tests/test_benchmark.py -q`
  - `4 passed in 0.03s`.
- Full: `pytest -q`
  - `164 passed in 40.23s`.
