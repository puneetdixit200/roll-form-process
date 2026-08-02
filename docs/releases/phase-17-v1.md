# Phase 17 v1 release record

Phase 17 is merged and tagged as `phase-17-v1`.

- Pull request: [#4](https://github.com/puneetdixit200/roll-form-process/pull/4)
- Feature SHA: `894b2f232c556779ef543a3754f44bd87c35f3c8`
- Merge SHA: `6c57595f4fbfd7442db40928a6f7116d59d3bcff`
- Tag object SHA: `106b5b4cbd5b71585de4e4952f568eb0216df0d4`
- Final main workflow: [30740442111](https://github.com/puneetdixit200/roll-form-process/actions/runs/30740442111) — PASS
- Readiness evidence: [Phase 17 HTML report](../reports/phase-17-release-readiness.html)

The release provides deterministic, explainable roller-design candidate recognition with hard compatibility filters, score components, abstention, engineer review, provenance, persistence, API/CLI access, frontend review, synthetic evaluation, and reproducibility checks.

Controlled synthetic regression results were top-1 accuracy 1.0 on non-abstained labelled cases, top-3 recall 1.0, false-high-confidence count 0, and deterministic repeated output.

Production status remains **NOT APPROVED**. The system does not automatically identify physical roller assets, recommend tooling, generate forming sequences, calculate reuse, or predict manufacturability. Engineer-labelled data, threshold review, and production approval remain future requirements.
