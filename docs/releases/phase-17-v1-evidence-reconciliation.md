# Phase 17 v1 evidence reconciliation

This note clarifies the Phase 17 release evidence without changing the existing
readiness snapshot or moving the `phase-17-v1` tag.

| Evidence item | Exact value | Meaning |
|---|---|---|
| Implementation feature workflow | `30740153908` (`fed85397a53e760f1a76f415e50170b88e89a2fa`) | Feature-branch implementation workflow |
| Implementation main workflow | `30740442111` (`6c57595f4fbfd7442db40928a6f7116d59d3bcff`) | Successful workflow for the merged implementation commit |
| Release-record commit | `b7bd24628abffe5dd6287aff58e65bbef8ddc14e` | Later documentation-only commit on `main` |
| Release-record workflow | `30740593156` (`b7bd24628abffe5dd6287aff58e65bbef8ddc14e`) | Successful workflow for the release-record commit |
| Tag | `phase-17-v1` | Annotated release tag |
| Tag object SHA | `106b5b4cbd5b71585de4e4952f568eb0216df0d4` | Annotated tag object |
| Tag target SHA | `6c57595f4fbfd7442db40928a6f7116d59d3bcff` | Implementation merge commit targeted by the tag |
| Post-release main SHA | `b7bd24628abffe5dd6287aff58e65bbef8ddc14e` | `main` after the permanent release record was added |

The older `docs/reports/phase-17-release-readiness.html` and JSON are retained
as pre-merge readiness snapshots. They are not post-merge release records and
must not be read as asserting that the later documentation commit was the
implementation commit.

The phrase “final workflow” is intentionally avoided here because two distinct
successful workflows are relevant: the implementation merge workflow and the
later release-record workflow.
