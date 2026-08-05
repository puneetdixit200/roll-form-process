# Private CLRSG training runbook

Set local-only environment variables:

```bash
export ROLLFORM_FLOWER_PROTOTYPE_DATASET=/private/dataset
export ROLLFORM_SYNTHETIC_CORPUS_ROOT=/private/corpora
export ROLLFORM_MODEL_REGISTRY_ROOT=/private/models
```

Plan the run without exposing geometry:

```bash
python scripts/run_phase20_private_clrsg.py plan --samples-per-seed 100
```

Generate a development corpus:

```bash
python scripts/run_phase20_private_clrsg.py generate --samples-per-seed 100
```

Train and evaluate:

```bash
python scripts/run_phase20_private_clrsg.py train \
  /private/corpora/private-two-seed-v1 \
  --output /private/models/model-candidate
```

Approve only when the held-out quality gate passes:

```bash
python scripts/run_phase20_private_clrsg.py approve /private/models/model-candidate
```

Activate an approved model:

```bash
python scripts/run_phase20_private_clrsg.py activate /private/models/model-candidate
export ROLLFORM_ACTIVE_CLRSG_MODEL=/private/models/model-candidate
```

The deterministic generator remains available when no model is active, an artifact is invalid, or the target is outside the supported visual distribution.

The private model is a visual prototype. It is not manufacturing, tooling, or physical-roller approval.
