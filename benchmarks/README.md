# Benchmark Fixtures

`evaluate_benchmark(truth, extraction)` accepts labelled truth JSON and either
exported `project.json` data, the same data as a Python mapping, or a
`project.sqlite` extraction database.

Truth and extraction files use the shape in `schema.json`:

- `stations[].bbox`: station boundary in millimetres.
- `profiles[].profile_id`: expected profile identity per station.
- `profiles[].contour`: sampled profile contour points in millimetres.
- `profiles[].developed_length_mm`: developed length for percent error.
- `profiles[].bends[]`: `position_mm`, `angle_deg`, and `radius_mm`.
- `rollers[].occurrence_id`: roller component identity.
- `rollers[].role`: roller role at the station.
- `automatic`: optional extraction flag; omitted values count as automatic unless `method` is `manual_override`.

Reported metrics:

- station count accuracy
- mean station boundary IoU
- profile ID accuracy
- roller component recall and role accuracy
- incorrect automatic claim rate
- Hausdorff and mean contour distance
- developed-length, bend-position, bend-angle, and bend-radius errors

Initial target limits are reported with pass/fail status. Dimensional limits are
marked provisional until engineering approval exists: contour distance `0.20 mm`,
developed length `0.10%`, bend position `0.20 mm`, bend angle `0.50 deg`, and
bend radius `0.50 mm`.
