# Phase 19: Synthetic Corpus and Learned Visual Sequence Model

Phase 19 adds a conservative, offline learned residual prototype called CLRSG (`clrsg_visual_sequence_v1`). It is conditioned on canonical target geometry and station count, learns teacher-minus-baseline residuals with NumPy PCA and ridge regression, and returns learned candidates only when artifact integrity, topology, support, and out-of-distribution checks permit them.

## Boundaries

The existing deterministic visual generator remains the mandatory baseline and fallback. CLRSG does not assign physical rollers, recommend tooling, predict manufacturability, or claim production feasibility. Synthetic samples are not historical evidence, and scores are visual prototype support rather than probabilities.

## Public corpus

The committable corpus contains only procedural families: U, C, Z, hat, step, asymmetric channel, curved wave, mixed line/arc, rounded rectangle, and asymmetric loop. Samples carry a schema version, classification, family, parent group, recipe, station count, split, target hash, teacher hash, and baseline hash. Grouped splits prevent sibling leakage. Private seed-derived samples and private model artifacts are local-only and use `PRIVATE_SYNTHETIC_DERIVED` / `PRIVATE_PROTOTYPE_MODEL` classifications.

## Model

Sequences are normalized to `(28, 128, 2)`. Target points are reduced with deterministic SVD PCA; teacher-minus-baseline residuals use a second SVD PCA with deterministic component signs. Five deterministic bootstrap group members fit closed-form ridge regressions. The artifact is NPZ/JSON only; loaders verify hashes, schema, algorithm version, supported topology, shapes, and privacy classification.

Inference always generates the deterministic baseline first. CLRSG predicts an ensemble mean residual, estimates condition distance and disagreement, selects `IN_DISTRIBUTION`, `NEAR_DISTRIBUTION`, or `OUT_OF_DISTRIBUTION`, blends conservatively, projects the sequence, and anchors the final station exactly to the target. Invalid or unsupported inference falls back without failing baseline generation.

## Evaluation and approval

Public synthetic evaluation is infrastructure and regression evidence only. Same-seed, cross-seed, hidden-pass, family-holdout, transformation-holdout, and station-count diagnostics must remain separately labelled. Model activation is explicit and artifact-verified. `PUBLIC_TEST_MODEL` means CI-safe only; `PRIVATE_PROTOTYPE_MODEL` means local engineer review only. Neither status is manufacturing approval.
