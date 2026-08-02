# Pass feature schema v2

Schema v2 separates audit geometry from comparison features. Audit geometry
retains absolute CAD coordinates for source navigation and previews. The scalar
and shape comparison vectors are translation invariant and must not contain
`bbox_min_x`, `bbox_min_y`, `bbox_max_x`, `bbox_max_y`, `bbox_center_x`,
`bbox_center_y`, `polygon_centroid_x`, `polygon_centroid_y`,
`neutral_centroid_x`, or `neutral_centroid_y`.

The schema version changed from v1 because vector field meaning changed. A v1
feature set must not be combined with v2 vectors without an explicit migration.
Unavailable values remain `None` in structured fields and are represented as
zero only with a corresponding missing-mask entry in numerical vectors.

Lengths use qualified names:

- `outline_perimeter_drawing_units` is the closed outline boundary perimeter.
- `generated_neutral_developed_length_drawing_units` is the geometric length
  of the generated neutral path.
- `expected_neutral_developed_length_drawing_units` is an independent expected
  value when available.
- error fields are null when no independent expectation exists.

Millimetre values are emitted only when the drawing unit conversion is
engineer-confirmed. Unconfirmed drawings remain eligible for shape-only
engineering inspection, not dimensional corpus import.
