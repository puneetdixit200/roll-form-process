# Phase 20: Private CLRSG Training and Activation

Phase 20 converts the Phase 19 public-model framework into a local-only private prototype workflow based on the two complete historical flowers.

## Architecture

1. Load the two redacted historical flowers from the private prototype dataset.
2. Derive monotonic visual progression schedules from consecutive pass geometry.
3. Create controlled target variants using scale, rotation, mirroring, and low-frequency normal warps.
4. Warp the complete historical sequence toward each transformed final target.
5. Compare the historical-warp teacher against the deterministic visual baseline.
6. Train the existing five-member CLRSG residual ensemble.
7. Evaluate it on grouped validation and test splits.
8. Approve it only when the learned held-out error improves the deterministic baseline by at least five percent.
9. Keep deterministic generation available for every request.

## Private corpus

Every private sample is classified as `PRIVATE_SYNTHETIC_DERIVED`. The corpus manifest is `PRIVATE_PROTOTYPE_CORPUS`, is explicitly non-committable, and stores source geometry only under a configured private root outside the repository.

The teacher sequence is built from the complete historical flower. The final-profile displacement field is smoothed and applied progressively to all source passes using a geometry-derived historical progress schedule. It is not the deterministic baseline with a different easing curve.

## Approval

Training and activation are separate operations. A private model is approved only when artifact hashes pass and held-out learned RMS improves the deterministic baseline by at least five percent with an acceptable fallback rate. A model that does not improve is retained as `NO_MEANINGFUL_IMPROVEMENT` and is not activated.

## Privacy

Private corpus files and private model artifacts remain outside Git. Public reports may contain aggregate counts, hashes, and metrics only.

## Boundary

All outputs are visual geometry evidence for engineer review. They do not represent manufacturing feasibility, tooling compatibility, production approval, or physical roller availability.
