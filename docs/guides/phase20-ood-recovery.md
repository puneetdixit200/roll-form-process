# Phase 20 OOD recovery

The first private Phase 20 run achieved strong sequence improvement but failed approval because the OOD detector rejected only the extreme-aspect probes and missed the high-frequency zigzag probes.

The repair adds `visual_geometry_guard_v1`, a deterministic contour-roughness guard that runs before learned inference. It does not lower the validation-derived statistical thresholds.

## Update the branch

```bash
git fetch origin
git switch feature/private-clrsg-training-evaluation
git pull --ff-only
python -m pip install -e ".[backend,test]"
python -m compileall src scripts
pytest -q tests/test_clrsg.py tests/test_private_clrsg.py
```

## Re-evaluate the existing private model

No corpus regeneration or model retraining is required for this repair.

```bash
python scripts/run_phase20_private_clrsg.py reevaluate \
  "$ROLLFORM_SYNTHETIC_CORPUS_ROOT/private-two-seed-v1" \
  "$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate" \
  --dataset "$ROLLFORM_FLOWER_PROTOTYPE_DATASET" \
  --registry "$ROLLFORM_MODEL_REGISTRY_ROOT" \
  --activate-if-approved
```

The command:

1. loads the existing private corpus and trained model;
2. re-runs held-out sequence evaluation;
3. re-runs the negative OOD probes using the new geometry guard;
4. refreshes model artifact hashes;
5. applies the existing approval gates without changing them;
6. activates only when all gates pass.

## Inspect the result

```bash
python scripts/run_phase20_private_clrsg.py status \
  "$ROLLFORM_MODEL_REGISTRY_ROOT/models/private-clrsg-candidate"
```

Approval still requires:

- held-out learned improvement of at least 5%;
- negative OOD true-positive rate of at least 75%;
- validation false-rejection rate no greater than 20%;
- deterministic fallback preserved.

Do not force activation if another gate fails.

All results remain visual prototype evidence only. Manufacturing approval remains `NOT_APPROVED`, and physical roller availability remains `NOT_DETERMINED`.
