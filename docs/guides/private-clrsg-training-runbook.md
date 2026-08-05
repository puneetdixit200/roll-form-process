# Private CLRSG training runbook

## Purpose

This is the only Phase 20 work that must run on the machine holding the two private flower sequences. The repository code, safety checks, grouped training, validation-derived OOD thresholds, evaluation, approval gates, and optional activation are already implemented.

Private corpus shards and trained model weights must remain outside the Git repository.

## 1. Check out the implementation branch

```bash
git fetch origin
git switch feature/private-clrsg-training-evaluation
git pull --ff-only
```

## 2. Install and verify dependencies

```bash
python -m pip install -e ".[backend,test]"
python -m compileall src scripts
pytest -q tests/test_clrsg.py tests/test_private_clrsg.py
```

## 3. Configure local-only paths

Every output path must be outside the repository.

```bash
export ROLLFORM_FLOWER_PROTOTYPE_DATASET=/absolute/private/path/to/flower-prototype-cli/dataset
export ROLLFORM_SYNTHETIC_CORPUS_ROOT=/absolute/private/path/to/clrsg-corpora
export ROLLFORM_MODEL_REGISTRY_ROOT=/absolute/private/path/to/clrsg-model-registry
```

`ROLLFORM_FLOWER_PROTOTYPE_DATASET` may point either to the directory containing `dataset.json` or directly to `dataset.json`.

## 4. Inspect the two seeds without printing geometry

```bash
python scripts/run_phase20_private_clrsg.py plan --samples-per-seed 100
```

Expected evidence:

- exactly two redacted flower IDs;
- approximately 31 total passes;
- each flower has at least eight passes;
- no private source filename or raw geometry is printed.

## 5. Run the complete development workflow

```bash
python scripts/run_phase20_private_clrsg.py all \
  --samples-per-seed 100 \
  --ensemble-members 5 \
  --seed 1729 \
  --activate-if-approved
```

This command performs:

1. private seed loading;
2. historical visual-progress schedule extraction;
3. controlled private-derived target generation;
4. complete historical-sequence warp teacher generation;
5. grouped train/validation/test splitting;
6. five-member parent-group bootstrap training;
7. validation-derived OOD thresholds;
8. held-out baseline-versus-learned evaluation;
9. negative OOD probes;
10. exact-seed and masked-pass diagnostics;
11. approval-gate evaluation;
12. activation only when all quality gates pass;
13. redacted aggregate summary creation.

The command never commits or uploads the private corpus or model.

## 6. Inspect the model status

The candidate model is written under:

```text
$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate
```

Inspect redacted metadata:

```bash
python scripts/run_phase20_private_clrsg.py status \
  "$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate"
```

If the model passes, the status is:

```text
APPROVED_FOR_PRIVATE_PROTOTYPE
```

If it does not improve enough, the status is:

```text
NO_MEANINGFUL_IMPROVEMENT
```

That is an acceptable result. Do not weaken the metric or force activation.

## 7. Use the active model

When activation succeeds:

```bash
export ROLLFORM_ACTIVE_CLRSG_MODEL="$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate"
```

Start the existing backend and frontend normally. Select `COMPARE_ALL` in the Visual Flower Generator and verify deterministic, learned-mean, and conservative-blend candidates.

## 8. Full-size run

After the 100-sample-per-seed development run succeeds technically, rerun with a larger corpus:

```bash
python scripts/run_phase20_private_clrsg.py all \
  --samples-per-seed 1000 \
  --ensemble-members 5 \
  --seed 1729 \
  --activate-if-approved
```

Increase beyond 1000 only when runtime and storage remain reasonable. Thousands of near-duplicate synthetic rows are not wisdom, despite the software industry's recurring belief that a larger integer is a research contribution.

## 9. Files that must never be committed

Do not commit:

- private `dataset.json`;
- `sequences.npz` from the private corpus;
- private target profiles;
- PCA arrays;
- ensemble member NPZ files;
- private model manifests containing local paths;
- `active_model.json`;
- private screenshots or pass thumbnails.

The deterministic generator remains available when the model is missing, invalid, unapproved, or out of distribution.

The private model remains a visual prototype. It is not manufacturing, tooling, or physical-roller approval.
