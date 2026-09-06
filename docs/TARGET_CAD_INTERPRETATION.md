# Target CAD interpretation

The Visual Flower Generator treats imported CAD as evidence, not as an
automatic manufacturing instruction.  A drawing may contain forming geometry,
reference points, dimensions, title-block entities, and several possible
profiles.  These are kept separate in the import contract.

## Representation classes

- `CENTERLINE_PATH`: an open path that can be used as a visual target.
- `STRIP_OUTLINE`: a closed constant-width boundary retained as raw evidence.
- `CLOSED_SECTION_BOUNDARY`: a closed section boundary; it is not silently
  converted into a flat strip.
- `GENERIC_CLOSED_CONTOUR`: a closed contour without sufficient strip evidence.
- `AMBIGUOUS`: geometry requiring engineer review.

For an elongated closed strip outline, the importer may add a separate
`DERIVED_CENTERLINE` candidate.  It records its source candidate, thickness
estimate, derivation method, and `ESTIMATED_REVIEW_REQUIRED` status.  The raw
boundary is never overwritten and the derived candidate is not a production
approval.

The current deterministic derivation is versioned as
`strip-outline-centerline-v2`. It uses area/perimeter only as a coarse hint,
selects mutually consistent end caps, estimates thickness from paired boundary
geometry, and preserves analytic LINE/ARC geometry where opposing source
segments support an offset interpretation. Unresolved local sections remain
explicit approximations rather than being mislabeled as exact geometry. The
result must be reviewed before dimensional or manufacturing use.

## Preview accounting

The safe vector preview distinguishes:

- source entities in modelspace;
- forming-geometry entities and preview primitives;
- reference entities such as `POINT`;
- unsupported source entity counts.

Reference entities are retained for inspection and are never inserted into a
target profile.  Bulged LWPOLYLINE/POLYLINE segments remain true preview ARC
primitives.  The browser receives derived vector metadata only: no source CAD
bytes or filesystem paths.

## Safety boundary

Unknown units may be visually inspected, but do not support dimensional or
manufacturing claims.  Every generated flower remains a visual prototype;
`manufacturing_approval` stays `NOT_APPROVED` and no physical roller asset is
assigned automatically.
