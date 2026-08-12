# Prompt for the local coding agent: execute Phase 20 with the private flowers

You are operating on the user's own computer, where the private roll-form flower dataset is available. The repository implementation is already complete on branch:

```text
feature/private-clrsg-training-evaluation
```

Your job is to execute, verify, and report the private local workflow. Do not redesign the architecture unless execution reveals a real defect. Do not upload or commit private data or trained artifacts.

## Objective

Use the two complete private historical flower sequences to:

1. generate a controlled private synthetic-derived corpus;
2. train the five-member CLRSG residual ensemble;
3. derive OOD thresholds from validation data;
4. compare learned output against the deterministic baseline;
5. run exact-seed, masked-pass, held-out, and negative-OOD diagnostics;
6. approve the model only when the quality gates pass;
7. activate it only when approved;
8. verify the learned model through the existing application;
9. report the exact metrics and remaining limitations.

This is a visual-geometry prototype only. Never claim manufacturing, tooling, production, or physical-roller approval.

## Mandatory safety rules

- Keep all private CAD, geometry, corpus shards, and model artifacts outside the Git repository.
- Do not use any external API or cloud model.
- Do not upload private artifacts to GitHub Actions.
- Do not print raw pass points or private source filenames.
- Do not force model activation.
- Do not weaken the approval thresholds after observing results.
- Do not commit `dataset.json`, `sequences.npz`, model NPZ files, private manifests, private screenshots, or local paths.
- Preserve the deterministic generator as fallback.

## Step 1: inspect Git state

Run:

```bash
git status --short
git branch --show-current
git log -8 --oneline --decorate
git fetch origin
git switch feature/private-clrsg-training-evaluation
git pull --ff-only
```

Do not discard unrelated local changes. If unrelated changes exist, preserve them and limit your edits to actual Phase 20 defects.

## Step 2: install and run public verification

Run:

```bash
python -m pip install -e ".[backend,test]"
python -m compileall src scripts
pytest -q tests/test_clrsg.py tests/test_private_clrsg.py
```

Then run the full Python suite if practical:

```bash
pytest -q
```

Also run:

```bash
cd frontend
npm ci
npm test -- --run
npm run build
cd ..
```

If a check fails, diagnose and fix the implementation. Commit only source code, tests, or redacted documentation. Never commit private outputs.

## Step 3: locate the existing private dataset

The required dataset is the private flower-prototype export containing geometry and two redacted flowers. It must contain:

```text
dataset.json
```

The file must describe exactly two complete flowers, expected to have approximately 14 and 17 passes.

Do not recreate the CAD extraction unless the dataset is missing or invalid.

Set absolute paths outside the repository:

```bash
export ROLLFORM_FLOWER_PROTOTYPE_DATASET=/absolute/private/path/to/dataset-or-dataset.json
export ROLLFORM_SYNTHETIC_CORPUS_ROOT=/absolute/private/path/to/clrsg-corpora
export ROLLFORM_MODEL_REGISTRY_ROOT=/absolute/private/path/to/clrsg-model-registry
```

Create the corpus and registry directories if necessary.

## Step 4: inspect seeds safely

Run:

```bash
python scripts/run_phase20_private_clrsg.py plan --samples-per-seed 100
```

Verify:

- seed flower count is exactly 2;
- total pass count is approximately 31;
- both sequences contain at least 8 passes;
- schedule extraction succeeds;
- output is redacted;
- no raw geometry or private source path is printed.

Stop and fix dataset loading if these checks fail.

## Step 5: run the complete development training workflow

Run:

```bash
python scripts/run_phase20_private_clrsg.py all \
  --samples-per-seed 100 \
  --ensemble-members 5 \
  --seed 1729 \
  --activate-if-approved
```

This command must:

- generate private transformed targets;
- use complete historical-sequence warp teachers;
- create grouped train/validation/test splits;
- train using parent-group bootstrap members;
- write hash-verified artifacts;
- derive OOD thresholds from validation quantiles;
- evaluate held-out baseline and learned RMS;
- run negative OOD probes;
- run exact-seed and masked-pass diagnostics;
- write separate training, validation, evaluation, calibration, approval, and OOD files;
- approve only when gates pass;
- activate only when approved;
- write a redacted summary.

## Step 6: inspect results

The model candidate is expected under:

```text
$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate
```

Run:

```bash
python scripts/run_phase20_private_clrsg.py status \
  "$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate"
```

Record:

```text
model ID
privacy classification
training sample count
validation sample count
test sample count
target PCA dimensions
residual PCA dimensions
selected ridge lambda
validation-derived OOD thresholds
baseline held-out RMS
learned held-out RMS
relative improvement
OOD true-positive rate
validation false-rejection rate
fallback rate
same-seed diagnostics
masked-pass diagnostics
approval status
activation status
```

## Step 7: respect the quality outcome

The model is approved only when the committed gates pass.

Possible honest outcomes:

```text
APPROVED_FOR_PRIVATE_PROTOTYPE
```

or:

```text
NO_MEANINGFUL_IMPROVEMENT
```

If the second result occurs:

- do not force activation;
- leave the deterministic generator active;
- report the failed metrics;
- identify likely technical causes;
- do not change the threshold merely to obtain a green badge, a venerable human tradition that has ruined enough dashboards already.

## Step 8: verify application inference

If the model is approved and active, set:

```bash
export ROLLFORM_ACTIVE_CLRSG_MODEL="$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate"
```

Start the existing backend and frontend.

In the Visual Flower Generator:

1. load or draw a profile visually close to the two seed families;
2. choose `COMPARE_ALL`;
3. generate exactly 16 stages;
4. verify deterministic baseline candidate;
5. verify CLRSG learned-mean candidate;
6. verify conservative-blend candidate;
7. inspect OOD status, blend alpha, historical confidence, model confidence, and combined confidence;
8. inspect learned correction view;
9. export JSON;
10. confirm export includes model ID and algorithm provenance but no local path.

Then load an extreme or unsupported profile and confirm deterministic fallback.

Check browser console and network errors.

## Step 9: run the larger private corpus

Only after the development workflow is technically stable, run:

```bash
python scripts/run_phase20_private_clrsg.py all \
  --samples-per-seed 1000 \
  --ensemble-members 5 \
  --seed 1729 \
  --activate-if-approved
```

Do not increase corpus size when duplicates, rejection rate, runtime, or model quality show no benefit.

## Step 10: final verification

Run:

```bash
python -m compileall src scripts
pytest -q
cd frontend && npm test -- --run && npm run build && cd ..
git status --short
```

Private directories must not appear in Git status.

Do not commit private results. Commit only a source fix if execution revealed an implementation bug, along with its tests.

## Required final response

Return:

```text
Branch
Commit used
Public Python tests
Full Python tests
Frontend tests
Frontend build
Private dataset found
Private seed count
Private pass count
Development corpus generated
Accepted/rejected/duplicate counts
Train/validation/test counts
Model ID
Privacy classification
Ensemble members
PCA dimensions
Ridge lambda
OOD thresholds
Baseline held-out RMS
Learned held-out RMS
Relative improvement
OOD true-positive rate
Validation false-rejection rate
Fallback rate
Exact-seed diagnostics
Masked-pass diagnostics
Approval status
Activation status
Frontend learned inference status
OOD fallback status
Private-data Git hygiene
Any source-code fixes committed
Known limitations

CUSTOMER VISUAL PROTOTYPE:
READY or NOT READY

MANUFACTURING APPROVAL:
NOT APPROVED

PHYSICAL ROLLER AVAILABILITY:
NOT DETERMINED
```

Do not merge or tag anything.
