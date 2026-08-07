# Visual Flower Demo Operator Runbook

Environment variables are local-only:

```bash
export ROLLFORM_FLOWER_PROTOTYPE_DATASET=/private/path/dataset.json
export ROLLFORM_ACTIVE_CLRSG_MODEL=/private/path/private-clrsg-candidate
```

Run:

```bash
python scripts/run_visual_flower_demo.py doctor
python scripts/run_visual_flower_demo.py start
python scripts/run_visual_flower_demo.py status
python scripts/run_visual_flower_demo.py verify
python scripts/run_visual_flower_demo.py stop
```

The launcher writes only redacted status to stdout and runtime logs/PIDs under
`/tmp/rollform-visual-flower-demo`. It does not kill unrelated processes. If
the model is absent or invalid, deterministic generation remains available.
Docker is optional for this demo because local package mirrors may be captive
portal constrained.
