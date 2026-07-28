from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.pipeline import ExtractionRequest, extract_project, reprocess_project
from rollform_extractor.validation import validate_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rollform-extractor")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_cmd = sub.add_parser("inspect")
    inspect_cmd.add_argument("source", type=Path)
    extract_cmd = sub.add_parser("extract")
    extract_cmd.add_argument("source", type=Path)
    extract_cmd.add_argument("output", type=Path)
    extract_cmd.add_argument("--stage", choices=("profiles", "rollers"))
    review_cmd = sub.add_parser("review")
    review_cmd.add_argument("project", type=Path)
    reprocess_cmd = sub.add_parser("reprocess")
    reprocess_cmd.add_argument("project", type=Path)
    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("project", type=Path)
    args = parser.parse_args(argv)

    if args.command == "inspect":
        print(json.dumps(inspect_drawing(args.source).to_dict(), default=str, sort_keys=True))
        return 0
    if args.command == "extract":
        try:
            summary = extract_project(ExtractionRequest(args.source, args.output, args.stage))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"{summary.project_path} stations={summary.station_count} warnings={summary.warning_count}")
        return 0
    if args.command == "review":
        path = args.project / "review" / "review_queue.json"
        print(path if path.exists() else "no review queue")
        return 0
    if args.command == "reprocess":
        summary = reprocess_project(args.project)
        print(f"{summary.project_path} stations={summary.station_count} warnings={summary.warning_count}")
        return 0
    if args.command == "validate":
        report = validate_project(args.project)
        print("valid" if report.valid else "\n".join(f"{issue.code}: {issue.message}" for issue in report.issues))
        return 0 if report.valid else 1
    return 2
