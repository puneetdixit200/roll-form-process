# Engineer Review Guide

Review a candidate after inspecting the sequence animation, historical
overlay, OOD state, warnings, and export package. Choose one of:

`ACCEPT_VISUAL_SEQUENCE`, `REJECT_VISUAL_SEQUENCE`, `PREFER_DETERMINISTIC`,
`PREFER_LEARNED`, `NEEDS_MANUAL_EDIT`, or `INSUFFICIENT_SUPPORT`.

Use reason codes such as `SMOOTH_PROGRESSION`, `HISTORICAL_MATCH`,
`BAD_INTERMEDIATE_SHAPE`, `SUDDEN_VISUAL_JUMP`, `WRONG_TOPOLOGY`, `OOD_CONCERN`,
`EXPORT_ISSUE`, and `OTHER`. Reviews preserve model/target provenance and do
not retrain, change thresholds, assign rollers, or approve manufacturing.
