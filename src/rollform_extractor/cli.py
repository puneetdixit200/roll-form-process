from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from rollform_extractor.batch import BatchRequest, batch_extract, validate_batch, write_batch_report
from rollform_extractor.converter import stage_input
from rollform_extractor.config import ExtractionConfig
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.metadata_import import import_metadata
from rollform_extractor.roller_inventory import (
    export_inventory,
    export_rejected_rows,
    import_inventory,
    inventory_stats,
    validate_inventory,
    write_inventory_template,
)
from rollform_extractor.roller_recognition import export_recognition_run, review_candidate, recognize_project
from rollform_extractor.validated_usage import (
    add_evaluation_case,
    adjudicate_case,
    approve_threshold_profile,
    build_usage_relationship_snapshot,
    create_evaluation_dataset,
    detect_stale_confirmations,
    evaluate_threshold_profile,
    export_evaluation_dataset,
    lock_dataset_version,
    promote_confirmed_usage,
    search_historical_usage,
    submit_label_assertion,
    validate_dataset,
)
from rollform_extractor.flower_prototype_dataset import build_dataset, ingest_private_flower, ingest_private_roller_evidence, persist_dataset
from rollform_extractor.flower_retrieval import target_from_pass, retrieve_historical_flowers
from rollform_extractor.flower_generation import generate_candidates
from rollform_extractor.flower_reconstruction_benchmark import benchmark_dataset
from rollform_extractor.flower_exports import export_generation, export_prototype_dataset, export_benchmark
from rollform_extractor.database import create_project_database
from rollform_extractor.pipeline import ExtractionRequest, extract_project, reprocess_project
from rollform_extractor.review_apply import ReviewApplyError, apply_review_decisions
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
    extract_cmd.add_argument("--config", type=Path)
    review_cmd = sub.add_parser("review")
    review_cmd.add_argument("project", type=Path)
    reprocess_cmd = sub.add_parser("reprocess")
    reprocess_cmd.add_argument("project", type=Path)
    reprocess_cmd.add_argument("--config", type=Path)
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
    apply_review_cmd = sub.add_parser("apply-review")
    apply_review_cmd.add_argument("project", type=Path)
    apply_review_cmd.add_argument("decisions", type=Path)
    inventory_template_cmd = sub.add_parser("roller-inventory-template")
    inventory_template_cmd.add_argument("output", type=Path)
    inventory_validate_cmd = sub.add_parser("roller-inventory-validate")
    inventory_validate_cmd.add_argument("source", type=Path)
    inventory_validate_cmd.add_argument("--database", type=Path)
    inventory_import_cmd = sub.add_parser("roller-inventory-import")
    inventory_import_cmd.add_argument("source", type=Path)
    inventory_import_cmd.add_argument("--database", type=Path, default=Path("roller_inventory.sqlite"))
    inventory_export_cmd = sub.add_parser("roller-inventory-export")
    inventory_export_cmd.add_argument("--database", type=Path, default=Path("roller_inventory.sqlite"))
    inventory_export_cmd.add_argument("--batch", type=int)
    inventory_export_cmd.add_argument("--rejected-output", type=Path)
    inventory_export_cmd.add_argument("output", type=Path)
    inventory_stats_cmd = sub.add_parser("roller-inventory-stats")
    inventory_stats_cmd.add_argument("--database", type=Path, default=Path("roller_inventory.sqlite"))
    recognition_run_cmd = sub.add_parser("roller-recognition-run")
    recognition_run_cmd.add_argument("project", type=Path)
    recognition_run_cmd.add_argument("--inventory", type=Path, required=True)
    recognition_run_cmd.add_argument("--output", type=Path, required=True)
    recognition_show_cmd = sub.add_parser("roller-recognition-show")
    recognition_show_cmd.add_argument("run_id", type=int)
    recognition_show_cmd.add_argument("--database", type=Path, required=True)
    recognition_review_cmd = sub.add_parser("roller-recognition-review")
    recognition_review_cmd.add_argument("candidate_id", type=int)
    recognition_review_cmd.add_argument("--decision", required=True)
    recognition_review_cmd.add_argument("--reviewer", required=True)
    recognition_review_cmd.add_argument("--database", type=Path, required=True)
    recognition_review_cmd.add_argument("--selected-design")
    recognition_review_cmd.add_argument("--selected-revision")
    recognition_review_cmd.add_argument("--reason-code")
    recognition_review_cmd.add_argument("--notes")
    recognition_export_cmd = sub.add_parser("roller-recognition-export")
    recognition_export_cmd.add_argument("run_id", type=int)
    recognition_export_cmd.add_argument("output", type=Path)
    recognition_export_cmd.add_argument("--database", type=Path, required=True)
    recognition_evaluate_cmd = sub.add_parser("roller-recognition-evaluate")
    recognition_evaluate_cmd.add_argument("labels", type=Path)
    recognition_evaluate_cmd.add_argument("--database", type=Path, required=True)
    dataset_create_cmd = sub.add_parser("recognition-dataset-create")
    dataset_create_cmd.add_argument("--name", required=True)
    dataset_create_cmd.add_argument("--kind", required=True)
    dataset_create_cmd.add_argument("--created-by", required=True)
    dataset_create_cmd.add_argument("--database", type=Path, required=True)
    dataset_create_cmd.add_argument("--description", default="")
    dataset_validate_cmd = sub.add_parser("recognition-dataset-validate")
    dataset_validate_cmd.add_argument("dataset_id")
    dataset_validate_cmd.add_argument("--database", type=Path, required=True)
    dataset_lock_cmd = sub.add_parser("recognition-dataset-lock")
    dataset_lock_cmd.add_argument("dataset_id")
    dataset_lock_cmd.add_argument("--reviewer", required=True)
    dataset_lock_cmd.add_argument("--database", type=Path, required=True)
    dataset_export_cmd = sub.add_parser("recognition-dataset-export")
    dataset_export_cmd.add_argument("dataset_id")
    dataset_export_cmd.add_argument("output", type=Path)
    dataset_export_cmd.add_argument("--database", type=Path, required=True)
    label_submit_cmd = sub.add_parser("recognition-label-submit")
    label_submit_cmd.add_argument("case_id", type=int)
    label_submit_cmd.add_argument("--outcome", required=True)
    label_submit_cmd.add_argument("--design-id")
    label_submit_cmd.add_argument("--revision-id")
    label_submit_cmd.add_argument("--reviewer", required=True)
    label_submit_cmd.add_argument("--reason", required=True)
    label_submit_cmd.add_argument("--database", type=Path, required=True)
    adjudicate_cmd = sub.add_parser("recognition-adjudicate")
    adjudicate_cmd.add_argument("case_id", type=int)
    adjudicate_cmd.add_argument("--outcome", required=True)
    adjudicate_cmd.add_argument("--design-id")
    adjudicate_cmd.add_argument("--revision-id")
    adjudicate_cmd.add_argument("--adjudicator", required=True)
    adjudicate_cmd.add_argument("--reason", required=True)
    adjudicate_cmd.add_argument("--database", type=Path, required=True)
    threshold_eval_cmd = sub.add_parser("recognition-threshold-evaluate")
    threshold_eval_cmd.add_argument("dataset_id")
    threshold_eval_cmd.add_argument("--profile", type=Path, required=True)
    threshold_eval_cmd.add_argument("--output", type=Path)
    threshold_eval_cmd.add_argument("--database", type=Path, required=True)
    threshold_approve_cmd = sub.add_parser("recognition-threshold-approve")
    threshold_approve_cmd.add_argument("profile_id")
    threshold_approve_cmd.add_argument("--reviewer", required=True)
    threshold_approve_cmd.add_argument("--notes", required=True)
    threshold_approve_cmd.add_argument("--database", type=Path, required=True)
    usage_promote_cmd = sub.add_parser("usage-promote")
    usage_promote_cmd.add_argument("case_id", type=int)
    usage_promote_cmd.add_argument("--reviewer", required=True)
    usage_promote_cmd.add_argument("--notes", default="")
    usage_promote_cmd.add_argument("--database", type=Path, required=True)
    usage_search_cmd = sub.add_parser("usage-search")
    usage_search_cmd.add_argument("--design-id")
    usage_search_cmd.add_argument("--role")
    usage_search_cmd.add_argument("--project-id", type=int)
    usage_search_cmd.add_argument("--mode", default="DESIGN_HISTORY")
    usage_search_cmd.add_argument("--include-synthetic", action="store_true")
    usage_search_cmd.add_argument("--include-stale", action="store_true")
    usage_search_cmd.add_argument("--database", type=Path, required=True)
    usage_relationships_cmd = sub.add_parser("usage-relationships-build")
    usage_relationships_cmd.add_argument("--database", type=Path, required=True)
    usage_relationships_cmd.add_argument("--output", type=Path)
    usage_stale_cmd = sub.add_parser("usage-stale-check")
    usage_stale_cmd.add_argument("--project-id", type=int)
    usage_stale_cmd.add_argument("--database", type=Path, required=True)
    flower_ingest_cmd = sub.add_parser("flower-prototype-ingest")
    flower_ingest_cmd.add_argument("source_root", type=Path)
    flower_ingest_cmd.add_argument("output_root", type=Path)
    flower_ingest_cmd.add_argument("--database", type=Path)
    flower_ingest_cmd.add_argument("--json", action="store_true")
    flower_generate_cmd = sub.add_parser("flower-generate")
    flower_generate_cmd.add_argument("dataset", type=Path)
    flower_generate_cmd.add_argument("--flower-id", required=True)
    flower_generate_cmd.add_argument("--output", type=Path, required=True)
    flower_generate_cmd.add_argument("--scale-x", type=float, default=1.0)
    flower_generate_cmd.add_argument("--scale-y", type=float, default=1.0)
    flower_generate_cmd.add_argument("--json", action="store_true")
    flower_benchmark_cmd = sub.add_parser("flower-benchmark")
    flower_benchmark_cmd.add_argument("dataset", type=Path)
    flower_benchmark_cmd.add_argument("--output", type=Path, required=True)
    flower_benchmark_cmd.add_argument("--json", action="store_true")
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
            summary = extract_project(ExtractionRequest(args.source, output, args.config))
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"{summary.project_path} drawing_stages={summary.station_count} warnings={summary.warning_count}")
        return 0
    if args.command == "review":
        path = args.project / "review" / "review_queue.json"
        print(path if path.exists() else "no review queue")
        return 0
    if args.command == "reprocess":
        summary = reprocess_project(args.project, args.config)
        print(f"{summary.project_path} drawing_stages={summary.station_count} warnings={summary.warning_count}")
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
    if args.command == "apply-review":
        try:
            path = apply_review_decisions(args.project, args.decisions)
        except (OSError, json.JSONDecodeError, ReviewApplyError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(path)
        return 0
    if args.command == "roller-inventory-template":
        print(write_inventory_template(args.output))
        return 0
    if args.command == "roller-inventory-validate":
        try:
            engine = create_project_database(args.database) if args.database else None
            report = validate_inventory(args.source, engine)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0 if report.valid else 1
    if args.command == "roller-inventory-import":
        try:
            engine = create_project_database(args.database)
            summary = import_inventory(args.source, engine)
        except (OSError, ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(summary.to_dict(), sort_keys=True))
        return 0 if summary.rejected == 0 else 1
    if args.command == "roller-inventory-export":
        engine = create_project_database(args.database)
        if args.batch is not None:
            target = args.rejected_output or (args.output / f"rejected_batch_{args.batch}.csv")
            print(export_rejected_rows(engine, args.batch, target))
        else:
            print(export_inventory(engine, args.output))
        return 0
    if args.command == "roller-inventory-stats":
        print(json.dumps(inventory_stats(create_project_database(args.database)), sort_keys=True))
        return 0
    if args.command == "roller-recognition-run":
        try:
            project_db = args.project / "project.sqlite"
            if not project_db.exists():
                raise ValueError(f"project database is missing: {project_db}")
            if not args.inventory.exists():
                raise ValueError(f"inventory database is missing: {args.inventory}")
            # Recognition persistence is intentionally co-located with the
            # project database so occurrence ownership and foreign keys remain
            # enforceable. Inventory must have been migrated/imported into this
            # database for a persisted run.
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from rollform_extractor.database import Project
            project_engine = create_project_database(project_db)
            with Session(project_engine) as session:
                project_row = session.scalar(select(Project).order_by(Project.id))
            if project_row is None:
                raise ValueError("project database has no project record")
            recognition_config = ExtractionConfig.load()
            run_id, results = recognize_project(project_engine, project_row.id, inventory_engine=create_project_database(args.inventory), configuration_hash=recognition_config.hash_for("roller_recognition"), config=recognition_config.roller_recognition)
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "run_summary.json").write_text(json.dumps({"run_id": run_id, "results": [result.to_dict() for result in results]}, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps({"run_id": run_id, "occurrences": len(results), "output": str(args.output)}, sort_keys=True))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "roller-recognition-review":
        try:
            review_id = review_candidate(create_project_database(args.database), args.candidate_id, args.decision, args.reviewer, selected_design_id=args.selected_design, selected_revision_id=args.selected_revision, reason_code=args.reason_code, notes=args.notes)
        except (LookupError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"review_id": review_id, "decision": args.decision}, sort_keys=True))
        return 0
    if args.command == "roller-recognition-show":
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from rollform_extractor.database import RollerRecognitionCandidate, RollerRecognitionRun
        with Session(create_project_database(args.database)) as session:
            run = session.get(RollerRecognitionRun, args.run_id)
            if run is None:
                print("recognition run not found", file=sys.stderr)
                return 1
            candidates = session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.run_id == args.run_id).order_by(RollerRecognitionCandidate.rank)).all()
            print(json.dumps({"run_id": run.id, "status": run.status, "algorithm_version": run.algorithm_version, "configuration_hash": run.configuration_hash, "candidates": [{"id": item.id, "design_id": item.design_id, "revision_id": item.geometry_revision_id, "rank": item.rank, "score": item.overall_score, "status": item.candidate_status} for item in candidates]}, sort_keys=True))
            return 0
    if args.command == "roller-recognition-export":
        try:
            print(export_recognition_run(create_project_database(args.database), args.run_id, args.output))
        except (LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0
    if args.command == "roller-recognition-evaluate":
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from rollform_extractor.database import RollerRecognitionCandidate, RollerRecognitionInput, RollerRecognitionRun
        labels = {}
        with args.labels.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if row.get("occurrence_id") and row.get("expected_design_id"):
                    labels[row["occurrence_id"]] = row["expected_design_id"]
        with Session(create_project_database(args.database)) as session:
            run = session.scalar(select(RollerRecognitionRun).order_by(RollerRecognitionRun.id.desc()))
            if run is None:
                print(json.dumps({"sample_count": 0, "dataset_kind": "ENGINEER_LABELLED", "status": "NO_RUN"}, sort_keys=True))
                return 1
            inputs = {row.id: row.occurrence_id for row in session.scalars(select(RollerRecognitionInput).where(RollerRecognitionInput.run_id == run.id))}
            grouped: dict[str, list[RollerRecognitionCandidate]] = {}
            for row in session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.run_id == run.id).order_by(RollerRecognitionCandidate.rank)):
                grouped.setdefault(inputs.get(row.input_id, ""), []).append(row)
            labelled = [(occurrence_id, grouped.get(occurrence_id, []), expected) for occurrence_id, expected in labels.items()]
            top1 = sum(bool(rows and rows[0].design_id == expected) for _, rows, expected in labelled)
            top3 = sum(any(row.design_id == expected for row in rows[:3]) for _, rows, expected in labelled)
            reciprocal = sum((1 / (next(index for index, row in enumerate(rows) if row.design_id == expected) + 1) if any(row.design_id == expected for row in rows) else 0.0) for _, rows, expected in labelled)
            abstained = sum(not rows or rows[0].candidate_status == "AMBIGUOUS" for _, rows, _ in labelled)
            accepted = len(labelled) - abstained
            result = {"run_id": run.id, "dataset_kind": "ENGINEER_LABELLED", "sample_count": len(labelled), "top_1_accuracy": top1 / len(labelled) if labelled else 0.0, "top_3_recall": top3 / len(labelled) if labelled else 0.0, "mean_reciprocal_rank": reciprocal / len(labelled) if labelled else 0.0, "abstention_rate": abstained / len(labelled) if labelled else 0.0, "coverage": accepted / len(labelled) if labelled else 0.0, "accuracy_non_abstained": sum(rows and rows[0].design_id == expected for _, rows, expected in labelled if rows and rows[0].candidate_status != "AMBIGUOUS") / accepted if accepted else 0.0, "false_high_confidence_count": sum(bool(rows and rows[0].confidence >= .9 and rows[0].design_id != expected) for _, rows, expected in labelled)}
            print(json.dumps(result, sort_keys=True))
            return 0
    if args.command == "recognition-dataset-create":
        try:
            print(json.dumps(create_evaluation_dataset(create_project_database(args.database), args.name, args.kind, args.created_by, args.description), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-dataset-validate":
        try:
            result = validate_dataset(create_project_database(args.database), args.dataset_id)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["valid"] else 1
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-dataset-lock":
        try:
            print(json.dumps(lock_dataset_version(create_project_database(args.database), args.dataset_id, args.reviewer), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-dataset-export":
        try:
            print(export_evaluation_dataset(create_project_database(args.database), args.dataset_id, args.output))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-label-submit":
        try:
            print(json.dumps(submit_label_assertion(create_project_database(args.database), args.case_id, args.reviewer, args.outcome, args.reason, args.design_id, args.revision_id), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-adjudicate":
        try:
            print(json.dumps(adjudicate_case(create_project_database(args.database), args.case_id, args.adjudicator, args.outcome, args.reason, args.design_id, args.revision_id), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-threshold-evaluate":
        try:
            configuration = json.loads(args.profile.read_text(encoding="utf-8"))
            print(json.dumps(evaluate_threshold_profile(create_project_database(args.database), args.dataset_id, configuration, args.output), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "recognition-threshold-approve":
        try:
            print(json.dumps(approve_threshold_profile(create_project_database(args.database), args.profile_id, args.reviewer, args.notes), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "usage-promote":
        try:
            print(json.dumps(promote_confirmed_usage(create_project_database(args.database), args.case_id, args.reviewer, args.notes), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "usage-search":
        try:
            print(json.dumps(search_historical_usage(create_project_database(args.database), args.mode, args.design_id, args.project_id, args.role, include_synthetic=args.include_synthetic, include_stale=args.include_stale), sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "usage-relationships-build":
        try:
            result = build_usage_relationship_snapshot(create_project_database(args.database))
            if args.output:
                args.output.mkdir(parents=True, exist_ok=True)
                (args.output / "snapshot.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(result, sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "usage-stale-check":
        try:
            print(json.dumps({"stale": detect_stale_confirmations(create_project_database(args.database), args.project_id)}, sort_keys=True))
            return 0
        except (ValueError, LookupError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "flower-prototype-ingest":
        try:
            root = args.source_root.resolve()
            args.output_root.mkdir(parents=True, exist_ok=True)
            flowers = (
                ingest_private_flower(root / "flower 1.dwg", args.output_root / "private-flower-001", "PRIVATE-FLOWER-001"),
                ingest_private_flower(root / "flower2.dwg", args.output_root / "private-flower-002", "PRIVATE-FLOWER-002"),
            )
            rollers = (
                ingest_private_roller_evidence(root / "roller1_sequnece aprtial.dwg", args.output_root / "private-roller-001", "PRIVATE-ROLLER-PARTIAL-001"),
                ingest_private_roller_evidence(root / "roller2_sequence partial.dwg", args.output_root / "private-roller-002", "PRIVATE-ROLLER-PARTIAL-002"),
            )
            dataset = build_dataset(flowers, rollers)
            export_prototype_dataset(dataset, args.output_root / "dataset")
            if args.database:
                persist_dataset(create_project_database(args.database), dataset)
            result = {"dataset_id": dataset.dataset_id, "dataset_hash": dataset.dataset_hash, "flowers": [{"flower_id": f.flower_id, "station_count": len(f.passes)} for f in flowers], "roller_evidence": len(rollers), "private_paths_redacted": True}
            print(json.dumps(result, sort_keys=True) if args.json else f"dataset={dataset.dataset_id} flowers=2 stations={[len(f.passes) for f in flowers]} rollers=2")
            return 0
        except (OSError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "flower-generate":
        try:
            payload = json.loads((args.dataset / "dataset.json").read_text(encoding="utf-8"))
            from rollform_extractor.flower_prototype_dataset import _dataset_from_dict
            dataset = _dataset_from_dict(payload)
            flower = next(item for item in dataset.flowers if item.flower_id == args.flower_id)
            target = target_from_pass(flower.passes[-1], target_id="SYNTHETIC-TARGET-001", scale_x=args.scale_x, scale_y=args.scale_y)
            candidates = generate_candidates(dataset, target)
            export_generation(candidates, args.output)
            result = {"target_id": target.target_id, "candidate_count": len(candidates), "candidates": [c.to_dict() for c in candidates]}
            print(json.dumps(result, sort_keys=True) if args.json else f"candidates={len(candidates)} output={args.output}")
            return 0
        except (OSError, RuntimeError, ValueError, StopIteration, KeyError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.command == "flower-benchmark":
        try:
            payload = json.loads((args.dataset / "dataset.json").read_text(encoding="utf-8"))
            from rollform_extractor.flower_prototype_dataset import _dataset_from_dict
            result = benchmark_dataset(_dataset_from_dict(payload).flowers)
            export_benchmark(_dataset_from_dict(payload).flowers, args.output)
            print(json.dumps(result, sort_keys=True) if args.json else f"cases={result['case_count']} output={args.output}")
            return 0
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    return 2
