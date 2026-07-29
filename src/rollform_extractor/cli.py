from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from rollform_extractor.batch import BatchRequest, batch_extract, validate_batch, write_batch_report
from rollform_extractor.converter import stage_input
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.metadata_import import import_metadata
from rollform_extractor.pipeline import ExtractionRequest, extract_project, reprocess_project
from rollform_extractor.validation import validate_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rollform-extractor")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect_cmd = sub.add_parser("inspect")
    inspect_cmd.add_argument("source", type=Path)
    extract_cmd = sub.add_parser("extract")
    extract_cmd.add_argument("source", type=Path)
    extract_cmd.add_argument("output", type=Path, nargs="?")
    extract_cmd.add_argument("--output", dest="output_option", type=Path)
    extract_cmd.add_argument("--stage", choices=("profiles", "rollers"))
    review_cmd = sub.add_parser("review")
    review_cmd.add_argument("project", type=Path)
    reprocess_cmd = sub.add_parser("reprocess")
    reprocess_cmd.add_argument("project", type=Path)
    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("project", type=Path)
    batch_extract_cmd = sub.add_parser("batch-extract")
    batch_extract_cmd.add_argument("source_root", type=Path)
    batch_extract_cmd.add_argument("output_root", type=Path)
    batch_extract_cmd.add_argument("--resume", action="store_true")
    batch_extract_cmd.add_argument("--skip-unchanged", action="store_true")
    batch_validate_cmd = sub.add_parser("batch-validate")
    batch_validate_cmd.add_argument("output_root", type=Path)
    batch_report_cmd = sub.add_parser("batch-report")
    batch_report_cmd.add_argument("output_root", type=Path)
    import_metadata_cmd = sub.add_parser("import-metadata")
    import_metadata_cmd.add_argument("metadata", type=Path)
    import_metadata_cmd.add_argument("--master", type=Path, default=Path("master.sqlite"))
    args = parser.parse_args(argv)

    if args.command == "inspect":
        try:
            with tempfile.TemporaryDirectory() as tmp:
                staged = stage_input(args.source, Path(tmp))
                print(json.dumps(inspect_drawing(staged.converted_file).to_dict(), default=str, sort_keys=True))
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "extract":
        output = args.output_option or args.output
        if output is None:
            parser.error("extract requires OUTPUT or --output")
        try:
            summary = extract_project(ExtractionRequest(args.source, output, args.stage))
        except (RuntimeError, ValueError) as exc:
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
    if args.command == "batch-extract":
        summary = batch_extract(BatchRequest(args.source_root, args.output_root, resume=args.resume, skip_unchanged=args.skip_unchanged))
        print(
            f"files={summary.total_files} success={summary.projects_succeeded} "
            f"failed={summary.projects_failed} skipped={summary.projects_skipped}"
        )
        return 0 if summary.projects_failed == 0 else 1
    if args.command == "batch-validate":
        report = validate_batch(args.output_root)
        print("valid" if report.valid else "\n".join(f"{issue.code}: {issue.message}" for issue in report.issues))
        return 0 if report.valid else 1
    if args.command == "batch-report":
        print(write_batch_report(args.output_root))
        return 0
    if args.command == "import-metadata":
        try:
            with sqlite3.connect(args.master) as db:
                summary = import_metadata(args.metadata, db)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"imported={summary.imported} unmatched={len(summary.unmatched)} conflicts={len(summary.conflicts)}")
        return 0 if not summary.unmatched and not summary.conflicts else 1
    return 2
