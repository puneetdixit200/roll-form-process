# Pass feature schema v1

Phase 15 derives deterministic candidate engineering descriptors from each
`CompositeFlowerPass`. The source CAD primitives, neutral line, and canonical
bend zones remain authoritative. A feature record is not a manufacturability
prediction and does not confirm roller identity or production intent.

## Identity, geometry, and units

Each record contains schema version, drawing/composite-flower/pass/profile/
station identity, inferred and confirmed order, feature configuration hash,
source handles, calculation method, software version, confidence, unit status,
quality flags, and review status. Bounding-box and neutral-line values use
drawing units unless an engineer-confirmed conversion to millimetres exists.
Open profiles do not receive invented area values; they use `null` and
`OPEN_PROFILE_AREA_UNAVAILABLE`. Neutral-line centroids are length-weighted.

Closed polylines use Shapely for area, perimeter, centroid, convex hull,
solidity, and compactness. Neutral-line features include developed length,
chord, tortuosity, chord deviation, tangents, rotation, and finite-difference
curvature. Segments are material intervals between canonical bend zones, not
arbitrary DXF vertices. Bend records preserve canonical IDs and include signed
angle, position, zone length, radius, radius-to-thickness ratio, spacing,
activation, confidence, and source handles.

## Vectors and fingerprints

`SCALAR_FEATURE_FIELDS` in `pass_features.py` is the stable scalar ordering.
Missing values remain `None` in structured records and become `0.0` only in
vectors with a matching `missing_mask`. The default shape vector has 128
material-coordinate points (256 values), the scalar vector has 94 values, and
the full vector has 350 values. Shape normalization translates to the first
material point, canonicalizes direction, scales by developed length, and
records mirror canonicalization metadata. Physical dimensions remain separate.

Physical, scale-normalized, mirror-canonical, and combined fingerprints are
SHA-256 digests over sorted, rounded, versioned JSON payloads. Consumers must
check schema version, configuration hash, field names, vector length, and
missing mask. Configuration changes require reprocessing; report-only
backfill is intentionally not used when pass geometry cannot be reconstructed
safely.

## Artifacts and API

Every pass exports `pass_features.json`, `pass_feature_vector.json`,
`segments.csv`, and `bend_features.csv`. Composite flowers export
`summaries/pass_features.csv` and `summaries/pass_feature_index.json`. Full
records are available from
`GET /api/projects/{project_id}/flowers/{flower_id}/passes/{pass_id}/features`.

These are candidate engineering descriptors, not production-approved
manufacturability results or automatic roller-recognition output.
