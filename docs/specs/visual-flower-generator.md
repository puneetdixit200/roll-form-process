# Visual Flower Generator

This is an offline visual-geometry prototype layered on the existing Phase
15–18 and history-constrained flower prototype. It accepts a versioned browser
profile, canonicalizes it in Python, generates bounded 8–28 station visual
sequences, compares every generated pass with historical pass evidence, and
exports an explainable result.

## Safety boundary

Every response and export is labelled: **Visual flower-sequence prototype for
engineer review. Not manufacturing approval.** Visual similarity and visual
confidence are not manufacturability, tooling compatibility, springback, strip
length, physical roller availability, or production approval. Private CAD is
loaded only through a locally configured dataset path and is never included in
public exports.

## Input and canonicalization

`schema_version=1` profiles contain world-coordinate vertices and line/arc
segments. The backend validates references, finite coordinates, arc radius,
topology and computational seam. Canonicalization resamples by arclength,
centres the points, scale-normalizes visual shape, and uses deterministic
direction/seam choices. Raw input remains separate from normalized comparison
geometry.

## Generation modes

`HISTORY_TEMPLATE_V1` remains the existing generator. This workflow uses
`VISUAL_SKETCH_V1` / `visual_sketch_history_match_v1`. Open paths blend a flat
visual baseline toward the target using smooth progression. Closed contours use
template morphing semantics and require a computational seam; physical seams
are never inferred.

Station counts are exact, range-based, or automatic and are always clamped to
8–28. Up to three candidates are produced using uniform and historical-style
progressions. A missing local historical dataset abstains with
`NO_HISTORICAL_SUPPORT`.

## Matching and confidence

Passes are compared using point RMS, subsampled symmetric Chamfer distance,
tangent/turning signatures, aspect ratio, topology, and normalized sequence
progress. Missing components are excluded from the weighted denominator.
Each pass stores its top three historical matches, source flower/pass IDs,
variant flags, metric components and evidence coverage.

Visual confidence is a bounded, non-calibrated index combining raw match,
coverage, historical support, warning penalties, mean/minimum pass support and
progression smoothness. Bands are `STRONG_VISUAL_SUPPORT`,
`MODERATE_VISUAL_SUPPORT`, `WEAK_VISUAL_SUPPORT`, and
`INSUFFICIENT_VISUAL_SUPPORT`.

## Persistence and exports

Targets are revisioned. Runs, candidates, passes, matches, confidence
components, reviews and artifacts use additive SQLite tables. Exports include
JSON, CSV, SVG, combined DXF, HTML and ZIP with a manifest. Source drawings are
not copied into the export package.

## Next data request

The current evidence is two complete historical flowers. Request 10–20
anonymized complete flowers across profile families, station counts, open and
closed geometries before requesting the remaining corpus.
