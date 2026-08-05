#!/usr/bin/env python3
"""Local-only Phase 20 private CLRSG workflow.

This operator script keeps private corpus and model paths outside Git, never
prints raw geometry, and can run the complete plan → generate → train → approve
→ optional activate workflow in one command.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rollform_extractor.phase20_ood_fix import reevaluate_private_model
from rollform_extractor.private_clrsg import (
    activate_private_model,
    approve_private_model,
    environment_paths,
    evaluate_model,
    generate_private_corpus,
    load_private_seeds,
    private_plan,
    run_full_private_workflow,
    train_private_model,
)
from rollform_extractor.synthetic_corpus_schema import load_corpus


def _redact(value):
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items() if key not in {"model_root", "dataset_path", "corpus_root", "registry_root"}}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _status(model: Path) -> dict:
    root = model.expanduser().resolve()
    payload = {}
    for name in ("manifest.json", "training_metrics.json", "validation_metrics.json", "evaluation_metrics.json", "approval.json", "ood_thresholds.json"):
        path = root / name
        if path.is_file():
            payload[name.removesuffix(".json")] = json.loads(path.read_text(encoding="utf-8"))
    if not payload:
        raise FileNotFoundError("no CLRSG model metadata was found")
    return _redact(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-phase20-private-clrsg")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--dataset", type=Path)
    plan.add_argument("--samples-per-seed", type=int, default=100)

    generate = sub.add_parser("generate")
    generate.add_argument("--dataset", type=Path)
    generate.add_argument("--output", type=Path)
    generate.add_argument("--samples-per-seed", type=int, default=100)
    generate.add_argument("--seed", type=int, default=1729)

    train = sub.add_parser("train")
    train.add_argument("corpus", type=Path)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--dataset", type=Path)
    train.add_argument("--ensemble-members", type=int, default=5)
    train.add_argument("--seed", type=int, default=1729)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("corpus", type=Path)
    evaluate.add_argument("model", type=Path)

    reevaluate = sub.add_parser("reevaluate")
    reevaluate.add_argument("corpus", type=Path)
    reevaluate.add_argument("model", type=Path)
    reevaluate.add_argument("--dataset", type=Path)
    reevaluate.add_argument("--registry", type=Path)
    reevaluate.add_argument("--activate-if-approved", action="store_true")

    approve = sub.add_parser("approve")
    approve.add_argument("model", type=Path)

    activate = sub.add_parser("activate")
    activate.add_argument("model", type=Path)
    activate.add_argument("--registry", type=Path)

    status = sub.add_parser("status")
    status.add_argument("model", type=Path)

    all_cmd = sub.add_parser("all")
    all_cmd.add_argument("--dataset", type=Path)
    all_cmd.add_argument("--corpus-root", type=Path)
    all_cmd.add_argument("--registry-root", type=Path)
    all_cmd.add_argument("--samples-per-seed", type=int, default=100)
    all_cmd.add_argument("--ensemble-members", type=int, default=5)
    all_cmd.add_argument("--seed", type=int, default=1729)
    all_cmd.add_argument("--activate-if-approved", action="store_true")

    args = parser.parse_args(argv)
    try:
        needs_env = args.command in {"plan", "generate", "activate", "all"}
        env = environment_paths() if needs_env else {}
        if args.command == "plan":
            result = private_plan(args.dataset or env["dataset"], samples_per_seed=args.samples_per_seed)
        elif args.command == "generate":
            output = args.output or (env["corpus_root"] / "private-two-seed-v1")
            _, summary = generate_private_corpus(args.dataset or env["dataset"], output, samples_per_seed=args.samples_per_seed, seed=args.seed)
            result = summary.to_dict() | {"output_configured": True}
        elif args.command == "train":
            seeds = load_private_seeds(args.dataset) if args.dataset else None
            result = train_private_model(load_corpus(args.corpus), args.output, ensemble_members=args.ensemble_members, seed=args.seed, private_seeds=seeds)
        elif args.command == "evaluate":
            result = evaluate_model(args.model, load_corpus(args.corpus))
        elif args.command == "reevaluate":
            result = reevaluate_private_model(
                args.corpus,
                args.model,
                dataset_path=args.dataset,
                registry_root=args.registry,
                activate_if_approved=args.activate_if_approved,
            )
        elif args.command == "approve":
            result = approve_private_model(args.model)
        elif args.command == "activate":
            result = activate_private_model(args.model, args.registry or env["model_root"])
        elif args.command == "status":
            result = _status(args.model)
        else:
            result = run_full_private_workflow(args.dataset or env["dataset"], args.corpus_root or env["corpus_root"], args.registry_root or env["model_root"], samples_per_seed=args.samples_per_seed, seed=args.seed, ensemble_members=args.ensemble_members, activate_if_approved=args.activate_if_approved)
        print(json.dumps(_redact(result), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
