#!/usr/bin/env python3
"""Local-only Phase 20 private CLRSG workflow.

This script intentionally keeps private corpus and model paths outside Git. It
is a thin operator surface over ``rollform_extractor.private_clrsg`` and never
prints raw geometry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rollform_extractor.private_clrsg import (
    activate_private_model,
    approve_private_model,
    environment_paths,
    generate_private_corpus,
    private_plan,
    train_private_model,
)
from rollform_extractor.synthetic_corpus_schema import load_corpus


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
    train.add_argument("--ensemble-members", type=int, default=5)
    train.add_argument("--seed", type=int, default=1729)

    approve = sub.add_parser("approve")
    approve.add_argument("model", type=Path)

    activate = sub.add_parser("activate")
    activate.add_argument("model", type=Path)
    activate.add_argument("--registry", type=Path)

    args = parser.parse_args(argv)
    try:
        env = environment_paths() if args.command in {"plan", "generate", "activate"} else {}
        if args.command == "plan":
            result = private_plan(args.dataset or env["dataset"], samples_per_seed=args.samples_per_seed)
        elif args.command == "generate":
            output = args.output or (env["corpus_root"] / "private-two-seed-v1")
            _, summary = generate_private_corpus(
                args.dataset or env["dataset"],
                output,
                samples_per_seed=args.samples_per_seed,
                seed=args.seed,
            )
            result = summary.to_dict() | {"output_configured": True}
        elif args.command == "train":
            result = train_private_model(
                load_corpus(args.corpus),
                args.output,
                ensemble_members=args.ensemble_members,
                seed=args.seed,
            )
            result.pop("model_root", None)
        elif args.command == "approve":
            result = approve_private_model(args.model)
        else:
            result = activate_private_model(args.model, args.registry or env["model_root"])
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
