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

## Follow-up Findings Fixed

- Added an IoU floor so zero-overlap station detections are not truth matches.
- Kept far automatic station detections counted as incorrect automatic claims.
- Made roller role accuracy station-aware instead of matching only by `occurrence_id`.
- Preserved `method` in exported `project.json` station, profile, and roller records for benchmark provenance.

## Follow-up TDD Evidence

- Red: `pytest tests/test_benchmark.py tests/test_exporters.py -q`
  - Failed 3 expected assertions:
    - zero-IoU station produced `boundary_iou=0.0` instead of no match
    - roller role accuracy returned `1.0` for a roller in the wrong station
    - exported `project.json` omitted `method`
- Green: `pytest tests/test_benchmark.py tests/test_exporters.py -q`
  - `9 passed in 1.85s`.

## Follow-up Verification

- Full: `pytest -q`
  - `167 passed in 40.07s`.
