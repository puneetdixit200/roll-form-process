# Phase 15 release record

This permanent post-merge record identifies the Phase 15 release. The older [readiness report](../reports/phase-15-release-readiness.html) is a pre-merge readiness snapshot and is retained as historical evidence.

- Pull request: #1
- Feature head: `ed951f6df5d5a7d4561e3cc43d952d87c1c7cc6`
- Merge commit: `4ed49cc721fa776366101da785348a085d87048e`
- Tag: `phase-15-v1`
- Tag object: `6ffa5c50f244b1c27a42c07067f44021a59bef9b`
- Final main workflow: `30713454104`

## Verification

Python passed with 213 tests. Frontend tests passed with 2 tests and the production build passed. The Docker build and backend/frontend smoke tests passed on the clean GitHub runner.

The pilot contained 1 composite flower, 12 passes, 12 feature sets, and 47 segment rows. Scalar, shape, and full vectors were 94, 256, and 350 values respectively. Two-run vectors, structured feature JSON, and fingerprints were identical.

The result remains candidate engineering data. Units and review warnings require engineer confirmation where applicable. Physical roller inventory and all Phase 16+ recognition, recommendation, sequence-generation, and manufacturability work were not part of Phase 15.
