# Constant Strip-Length Implementation Audit

## Scope completed in repository

- Added `constant_centerline_length_v1` geometry projection.
- Open-path stages preserve the final target's material-coordinate segment lengths while retaining predicted segment directions.
- Closed-contour stages preserve final-target perimeter and use an equal-perimeter closed reference loop instead of uniform scaling that would collapse progression after projection.
- Deterministic candidates are constrained at every stage.
- CLRSG learned residuals remain referenced to the legacy unconstrained baseline used during private-model training; constant-length projection is applied only after residual prediction.
- Final target pass remains exact.
- Candidate and per-pass provenance records target length, actual length, relative error, projection method, and tolerance.
- Visual generation algorithm version was bumped to `visual_sketch_history_match_v2_constant_length`.
- Persisted run keys now include the visual algorithm and strip-length constraint versions, preventing old cached unconstrained runs from being returned as new results.
- JSON/CSV/HTML/PNG/DXF/SVG/ZIP exports use constrained geometry; CSV/HTML/manifest expose length evidence.
- Added a standalone JSON invariant verifier.
- Added deterministic open, closed, learned-compatibility, and export regression tests.
- Frontend TypeScript contracts expose strip-length metadata.

## Deliberately unchanged

- Private CLRSG weights are not retrained or committed.
- Private corpus is not regenerated.
- CLRSG approval thresholds and OOD thresholds are unchanged.
- Manufacturing approval remains `NOT_APPROVED`.
- Physical roller availability remains `NOT_DETERMINED`.

## Local verification still required

The connected repository environment cannot access the user's local private dataset, active private model artifact, running browser, or local SQLite workspace. The laptop run must therefore verify:

1. Full Python test suite.
2. Frontend tests and production build.
3. Existing private CLRSG model still loads as approved and active.
4. 8/16/28-station deterministic and learned candidates all satisfy the length invariant.
5. OOD fallback remains correct.
6. Export verifier passes on a real generated run.
7. Browser rendering shows the expected progression without visual regressions.
8. Performance remains acceptable after projection.

The centerline-length constraint is visual geometry evidence only. It does not model neutral-axis shift, plastic strain, thinning, springback, material constitutive behavior, tooling contact, roll forces, or manufacturability.
