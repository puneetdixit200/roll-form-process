"""Persistence/service boundary for the visual flower workflow."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.clrsg_inference import infer_learned_candidates, load_active_model
from rollform_extractor.database import (
    ConfirmedRollerDesignUsage,
    Project,
    RollerRecognitionCandidate,
    RollerRecognitionInput,
    Station,
    VisualFlowerCandidateReviewRow,
    VisualFlowerRollerEvidenceBundleRow,
    VisualFlowerCandidateRow,
    VisualFlowerGenerationRunRow,
    VisualProfileTargetRevisionRow,
    VisualProfileTargetRow,
    create_project_database,
)
from rollform_extractor.flower_roller_evidence import (
    FLOWER_ROLLER_EVIDENCE_VERSION,
    build_candidate_roller_evidence,
)
from rollform_extractor.historical_source_traceability import historical_flower_detail, historical_pass_detail, safe_historical_flower
from rollform_extractor.roller_recognition import recognize_project
from rollform_extractor.strip_length_constraint import STRIP_LENGTH_CONSTRAINT_VERSION
from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_flower_exports import export_visual_run, historical_profile_png
from rollform_extractor.visual_profile_schema import VISUAL_ALGORITHM_VERSION, validate_profile
from rollform_extractor.historical_roller_library import attach_subsequence_rollers, configured_library, library_hash


DIRECT_ROLLER_EVIDENCE_CONFIGURATION = "flower-direct-project-roller-evidence-v1"


def profile_hash(profile: dict[str, Any]) -> str:
    return sha256(
        json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _scope_candidate_ids(candidates: list[dict[str, Any]], run_key: str) -> None:
    """Make result-local candidate IDs unique in the shared visual database."""
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_id"] = "vfg-" + sha256(
            f"{run_key}|{index}|{candidate.get('candidate_id', '')}".encode()
        ).hexdigest()[:16]


def historical_dataset() -> dict[str, Any]:
    configured = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
    if not configured:
        return {"dataset_hash": "UNCONFIGURED", "flowers": [], "source_classification": "NONE"}
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or path.name != "dataset.json":
        raise ValueError("configured visual prototype dataset is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def historical_pass_preview(source_flower_id: str, source_pass_id: str) -> bytes | None:
    """Return a customer-safe PNG of one historical pass geometry."""
    for flower in historical_dataset().get("flowers", []):
        if flower.get("flower_id") != source_flower_id:
            continue
        for item in flower.get("passes", []):
            if item.get("pass_id") == source_pass_id:
                points = (
                    item.get("profile", {}).get("points")
                    or item.get("points")
                    or item.get("canonical_points")
                )
                if not points:
                    vector = item.get("shape_vector") or []
                    points = [
                        vector[index : index + 2]
                        for index in range(0, len(vector), 2)
                        if len(vector[index : index + 2]) == 2
                    ]
                if points:
                    return historical_profile_png(points, label=f"{source_flower_id} / {source_pass_id}")
    return None


def historical_flowers(*, include_geometry: bool = False) -> list[dict[str, Any]]:
    dataset = historical_dataset()
    return [safe_historical_flower(flower, include_geometry=include_geometry, dataset_hash=str(dataset.get("dataset_hash") or "UNCONFIGURED")) for flower in sorted(dataset.get("flowers", []), key=lambda item: str(item.get("flower_id", "")))]


def historical_flower(source_flower_id: str) -> dict[str, Any] | None:
    return historical_flower_detail(historical_dataset(), source_flower_id)


def historical_pass(source_flower_id: str, source_pass_id: str) -> dict[str, Any] | None:
    return historical_pass_detail(historical_dataset(), source_flower_id, source_pass_id)


def create_target(engine, payload: dict[str, Any]) -> dict[str, Any]:
    profile = validate_profile(payload.get("profile") or payload)
    target_id = str(payload.get("target_id") or "vtarget-" + profile_hash(profile.to_dict())[:16])
    with Session(engine) as session:
        existing = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        if existing:
            return target_summary(session, existing)
        row = VisualProfileTargetRow(
            target_id=target_id,
            name=profile.name,
            schema_version=1,
            topology=profile.topology,
            current_revision=1,
            status="DRAFT",
        )
        session.add(row)
        session.flush()
        session.add(
            VisualProfileTargetRevisionRow(
                target_id=row.id,
                revision=1,
                input_hash=profile_hash(profile.to_dict()),
                profile_json=profile.to_dict(),
                validation_json={"valid": True},
            )
        )
        session.commit()
        return target_summary(session, row)


def target_summary(session: Session, row: VisualProfileTargetRow) -> dict[str, Any]:
    revision = session.scalar(
        select(VisualProfileTargetRevisionRow).where(
            VisualProfileTargetRevisionRow.target_id == row.id,
            VisualProfileTargetRevisionRow.revision == row.current_revision,
        )
    )
    return {
        "target_id": row.target_id,
        "name": row.name,
        "topology": row.topology,
        "status": row.status,
        "revision": row.current_revision,
        "profile": revision.profile_json if revision else None,
        "input_hash": revision.input_hash if revision else None,
    }


def list_targets(engine) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            target_summary(session, row)
            for row in session.scalars(select(VisualProfileTargetRow).order_by(VisualProfileTargetRow.target_id))
        ]


def get_target(engine, target_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        return target_summary(session, row) if row else None


def _roller_station_evidence_hash(dataset: dict[str, Any]) -> str:
    records = dataset.get("roller_station_evidence")
    if records is None:
        records = dataset.get("historical_roller_station_evidence")
    if records is None:
        return "UNCONFIGURED"
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode()).hexdigest()


def _inventory_snapshot(inventory_engine) -> tuple[dict[str, list[dict[str, Any]]], str]:
    if inventory_engine is None:
        return {}, "UNCONFIGURED"
    from rollform_extractor.database import RollerAsset

    inventory_assets: dict[str, list[dict[str, Any]]] = {}
    with Session(inventory_engine) as inventory_session:
        assets = inventory_session.scalars(
            select(RollerAsset).order_by(RollerAsset.design_id, RollerAsset.asset_id)
        ).all()
        for asset in assets:
            inventory_assets.setdefault(str(asset.design_id), []).append(
                {
                    "asset_id": asset.asset_id,
                    "condition": asset.condition,
                    "location_id": asset.location_id,
                    "verified": bool(asset.verified),
                }
            )
    payload = json.dumps(inventory_assets, sort_keys=True, separators=(",", ":"))
    return inventory_assets, sha256(payload.encode()).hexdigest()


def _workflow_project_database(target_id: str) -> tuple[str, Path, str] | None:
    """Resolve an integrated visual target back to its general CAD project DB."""
    root = Path(os.environ.get("ROLLFORM_WEB_WORKSPACE", Path.cwd() / "web-workspace"))
    workflows = root / "rollform_workflows"
    if not workflows.is_dir():
        return None
    for workflow_path in sorted(workflows.glob("*/workflow.json")):
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(workflow.get("selected_target_id") or "") != str(target_id):
            continue
        project_id = str(workflow.get("project_id") or "")
        record_path = root / "projects" / project_id / "project_record.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return project_id, Path(), str(workflow.get("source_sha256") or "")
        project_path_value = (record.get("summary") or {}).get("project_path")
        if not project_path_value:
            return project_id, Path(), str(workflow.get("source_sha256") or "")
        project_database = Path(str(project_path_value)) / "project.sqlite"
        return project_id, project_database, str(workflow.get("source_sha256") or "")
    return None


def _direct_project_roller_evidence(
    target_id: str,
    inventory_engine,
    *,
    units_status: str = "UNKNOWN",
) -> tuple[list[dict[str, Any]], str]:
    """Reuse the existing extraction/recognition pipeline for an integrated DXF.

    If background CAD analysis is not ready yet, generation remains available
    with historical evidence only. The pending-state hash is intentionally part
    of the generation cache key so a later generation refreshes automatically.
    """
    resolved = _workflow_project_database(target_id)
    if resolved is None:
        return [], "NOT_INTEGRATED_WORKFLOW"
    external_project_id, database_path, source_sha256 = resolved
    if not database_path or not database_path.is_file():
        return [], "PROJECT_ANALYSIS_PENDING"

    project_engine = create_project_database(database_path)
    with Session(project_engine) as session:
        project = session.scalar(select(Project).where(Project.source_sha256 == source_sha256))
        if project is None:
            # Controlled compatibility fallback for old project databases. A
            # project-local database normally contains exactly one Project row;
            # never use the workspace directory name as its identity.
            projects = session.scalars(select(Project)).all()
            if len(projects) == 1:
                project = projects[0]
        if project is None:
            return [], "PROJECT_ANALYSIS_PENDING"
        numeric_project_id = project.id

    run_id, _ = recognize_project(
        project_engine,
        numeric_project_id,
        inventory_engine=inventory_engine,
        units_status=units_status,
        configuration_hash=DIRECT_ROLLER_EVIDENCE_CONFIGURATION,
    )

    with Session(project_engine) as session:
        inputs = session.scalars(
            select(RollerRecognitionInput)
            .where(RollerRecognitionInput.run_id == run_id)
            .order_by(RollerRecognitionInput.occurrence_id)
        ).all()
        candidates = session.scalars(
            select(RollerRecognitionCandidate)
            .where(RollerRecognitionCandidate.run_id == run_id)
            .order_by(RollerRecognitionCandidate.input_id, RollerRecognitionCandidate.rank)
        ).all()
        station_rows = session.scalars(
            select(Station)
            .where(Station.project_id == numeric_project_id)
            .order_by(Station.sequence_index, Station.station_id)
        ).all()
        confirmed_rows = session.scalars(
            select(ConfirmedRollerDesignUsage).where(
                ConfirmedRollerDesignUsage.project_id == numeric_project_id,
                ConfirmedRollerDesignUsage.confirmation_status == "CONFIRMED",
            )
        ).all()

        input_by_id = {row.id: row for row in inputs}
        station_ids = [row.station_id for row in station_rows]
        station_ids.extend(row.station_id for row in inputs if row.station_id and row.station_id not in station_ids)
        station_ids = list(dict.fromkeys(station_ids))
        if not station_ids:
            return [], "NO_EXTRACTED_ROLLER_STATIONS"
        progress_by_station = {
            station_id: index / max(len(station_ids) - 1, 1)
            for index, station_id in enumerate(station_ids)
        }
        confirmed = {
            (row.occurrence_id, row.design_id, row.geometry_revision_id)
            for row in confirmed_rows
        }
        confirmed_design = {(row.occurrence_id, row.design_id) for row in confirmed_rows}

        grouped: dict[int, list[RollerRecognitionCandidate]] = {}
        for row in candidates:
            grouped.setdefault(row.input_id, []).append(row)

        records: list[dict[str, Any]] = []
        for input_id, rows in sorted(grouped.items()):
            input_row = input_by_id.get(input_id)
            if input_row is None or not input_row.station_id:
                continue
            eligible = [
                row
                for row in rows
                if float(row.overall_score or 0.0) >= 0.55
                and float(row.evidence_coverage or 0.0) >= 0.40
            ]
            if not eligible:
                continue
            ambiguous = (
                str(eligible[0].candidate_status or "").upper() == "AMBIGUOUS"
                or (
                    len(eligible) > 1
                    and float(eligible[0].overall_score or 0.0)
                    - float(eligible[1].overall_score or 0.0)
                    < 0.05
                )
            )
            feature = input_row.feature_json or {}
            quality_flags = list(feature.get("quality_flags") or [])
            for row in eligible:
                is_confirmed = (
                    (input_row.occurrence_id, row.design_id, row.geometry_revision_id) in confirmed
                    or (input_row.occurrence_id, row.design_id) in confirmed_design
                )
                records.append(
                    {
                        "source_project_id": external_project_id,
                        "source_occurrence_id": input_row.occurrence_id,
                        "station_id": input_row.station_id,
                        "station_progress": progress_by_station[input_row.station_id],
                        "role": input_row.role or "UNKNOWN",
                        "design_id": row.design_id,
                        "geometry_revision_id": row.geometry_revision_id,
                        "recognition_score": float(row.overall_score or 0.0),
                        "recognition_confidence": float(row.confidence or 0.0),
                        "evidence_coverage": float(row.evidence_coverage or 0.0),
                        "recognition_status": "AMBIGUOUS" if ambiguous else row.candidate_status,
                        "confirmation_status": "CONFIRMED" if is_confirmed else "UNCONFIRMED",
                        "association_method": "EXACT_PROJECT_STATION",
                        "quality_flags": quality_flags,
                        "hard_filters": row.hard_filter_results_json or {},
                        "score_components": row.component_scores_json or {},
                    }
                )

    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return records, sha256(payload.encode()).hexdigest()


def _generation_configuration(
    preferences: dict[str, Any],
    *,
    inventory_snapshot_hash: str = "UNCONFIGURED",
    roller_station_evidence_hash: str = "UNCONFIGURED",
    direct_project_evidence_hash: str = "UNCONFIGURED",
) -> dict[str, Any]:
    include_evidence = bool(preferences.get("include_roller_evidence", True))
    return {
        "preferences": preferences,
        "visual_algorithm_version": VISUAL_ALGORITHM_VERSION,
        "strip_length_constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
        "flower_roller_evidence_version": FLOWER_ROLLER_EVIDENCE_VERSION,
        "inventory_snapshot_hash": inventory_snapshot_hash if include_evidence else "DISABLED",
        "roller_station_evidence_hash": roller_station_evidence_hash if include_evidence else "DISABLED",
        "direct_project_evidence_hash": direct_project_evidence_hash if include_evidence else "DISABLED",
    }


def generate_for_target(
    engine,
    target_id: str,
    preferences: dict[str, Any],
    inventory_engine=None,
) -> dict[str, Any]:
    with Session(engine) as session:
        target_row = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        if not target_row:
            raise LookupError("visual target not found")
        revision = session.scalar(
            select(VisualProfileTargetRevisionRow).where(
                VisualProfileTargetRevisionRow.target_id == target_row.id,
                VisualProfileTargetRevisionRow.revision == target_row.current_revision,
            )
        )

    profile = validate_profile(revision.profile_json)
    dataset = historical_dataset()
    inventory_assets, inventory_snapshot_hash = _inventory_snapshot(inventory_engine)
    station_evidence_hash = _roller_station_evidence_hash(dataset)
    if preferences.get("include_roller_evidence", True):
        direct_evidence, direct_evidence_hash = _direct_project_roller_evidence(
            target_id,
            inventory_engine,
            units_status=str(profile.metadata.get("unit_status") or "UNKNOWN"),
        )
    else:
        direct_evidence, direct_evidence_hash = [], "DISABLED"

    result = generate_visual_candidates(
        profile,
        dataset.get("flowers", []),
        station_mode=preferences.get("station_mode", "AUTOMATIC"),
        exact_station_count=preferences.get("exact_station_count"),
        minimum_station_count=preferences.get("minimum_station_count", 8),
        maximum_station_count=preferences.get("maximum_station_count", 28),
        candidate_limit=preferences.get("candidate_limit", 3),
        allow_mirror_matching=preferences.get("allow_mirror_matching", True),
        allow_rotation_alignment=preferences.get("allow_rotation_alignment", False),
    )

    engine_mode = str(preferences.get("generation_engine", "AUTO")).upper()
    if engine_mode in {"AUTO", "COMPARE_ALL", "LEARNED_HYBRID"}:
        learned = infer_learned_candidates(profile, result, load_active_model())
        result["learned_model"] = {"status": learned["status"], "warnings": learned.get("warnings", [])}
        if learned.get("candidates"):
            result["candidates"] = (
                result.get("candidates", [])
                if engine_mode == "COMPARE_ALL"
                else result.get("candidates", [])[:1]
            ) + learned["candidates"]
    else:
        result["learned_model"] = {"status": "DETERMINISTIC_ONLY", "warnings": []}

    configuration = _generation_configuration(
        preferences,
        inventory_snapshot_hash=inventory_snapshot_hash,
        roller_station_evidence_hash=station_evidence_hash,
        direct_project_evidence_hash=direct_evidence_hash,
    )
    roller_library = configured_library()
    configuration["historical_roller_library_hash"] = library_hash(roller_library, str(dataset.get("dataset_hash")))
    configuration["historical_roller_link_version"] = "selected-pass-v2"
    configuration_json = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    run_key = "vrun-" + sha256(
        f"{target_id}|{revision.input_hash}|{configuration_json}|{dataset.get('dataset_hash')}".encode()
    ).hexdigest()[:16]
    configuration_hash = sha256(configuration_json.encode()).hexdigest()

    _scope_candidate_ids(result.get("candidates", []), run_key)
    attach_subsequence_rollers(result.get("candidates", []), roller_library, str(dataset.get("dataset_hash")))
    if preferences.get("include_roller_evidence", True):
        for candidate in result.get("candidates", []):
            candidate["roller_evidence"] = build_candidate_roller_evidence(
                candidate,
                historical_dataset=dataset,
                inventory_assets=inventory_assets,
                inventory_snapshot_hash=inventory_snapshot_hash,
                direct_project_evidence=direct_evidence,
                direct_project_evidence_hash=direct_evidence_hash,
            )

    with Session(engine) as session:
        existing = session.scalar(
            select(VisualFlowerGenerationRunRow).where(VisualFlowerGenerationRunRow.run_id == run_key)
        )
        if existing is not None:
            return existing.result_json | {"run_id": existing.run_id, "status": existing.status}

        run_status = "READY" if result["candidates"] else "NO_HISTORICAL_SUPPORT"
        run = VisualFlowerGenerationRunRow(
            run_id=run_key,
            target_id=target_row.id,
            algorithm_version=result["algorithm_version"],
            dataset_hash=dataset.get("dataset_hash", "UNCONFIGURED"),
            configuration_hash=configuration_hash,
            status=run_status,
            warnings_json=result.get("warnings", []) + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else []),
            result_json=result,
        )
        session.add(run)
        session.flush()
        for candidate in result["candidates"]:
            session.add(
                VisualFlowerCandidateRow(
                    candidate_id=candidate["candidate_id"],
                    run_id=run.id,
                    candidate_json=candidate,
                    status=candidate["status"],
                    visual_confidence=candidate["visual_confidence"]["score"],
                )
            )
            evidence = candidate.get("roller_evidence")
            if evidence:
                session.add(
                    VisualFlowerRollerEvidenceBundleRow(
                        bundle_id="vfre-" + str(evidence["evidence_bundle_hash"])[:24],
                        candidate_id=candidate["candidate_id"],
                        algorithm_version=str(evidence["algorithm_version"]),
                        configuration_hash=configuration_hash,
                        historical_dataset_hash=str(evidence["historical_dataset_hash"]),
                        inventory_snapshot_hash=str(evidence["inventory_snapshot_hash"]),
                        payload_json=evidence,
                    )
                )
        session.commit()

    return {
        "run_id": run_key,
        "status": run_status,
        "target_id": target_id,
        "candidate_ids": [item["candidate_id"] for item in result["candidates"]],
        "candidates": result["candidates"],
        "warnings": result.get("warnings", []) + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else []),
    }


def get_run(engine, run_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(select(VisualFlowerGenerationRunRow).where(VisualFlowerGenerationRunRow.run_id == run_id))
        return row.result_json | {"run_id": row.run_id, "status": row.status} if row else None


def get_candidate(engine, candidate_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(select(VisualFlowerCandidateRow).where(VisualFlowerCandidateRow.candidate_id == candidate_id))
        return row.candidate_json if row else None


def export_candidate(engine, candidate_id: str, output_root: Path) -> Path | None:
    candidate = get_candidate(engine, candidate_id)
    if candidate is None:
        return None
    directory = output_root / "visual_exports" / candidate_id
    export_visual_run(
        {"schema_version": 1, "candidates": [candidate], "source_cad_included": False},
        directory,
    )
    return directory


REVIEW_DECISIONS = {
    "ACCEPT_VISUAL_SEQUENCE",
    "REJECT_VISUAL_SEQUENCE",
    "PREFER_DETERMINISTIC",
    "PREFER_LEARNED",
    "NEEDS_MANUAL_EDIT",
    "INSUFFICIENT_SUPPORT",
}
REVIEW_REASONS = {
    "SMOOTH_PROGRESSION",
    "HISTORICAL_MATCH",
    "BAD_INTERMEDIATE_SHAPE",
    "SUDDEN_VISUAL_JUMP",
    "WRONG_TOPOLOGY",
    "OOD_CONCERN",
    "EXPORT_ISSUE",
    "OTHER",
}


def create_candidate_review(
    engine,
    candidate_id: str,
    decision: str,
    reviewer: str,
    *,
    reason_codes: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if decision not in REVIEW_DECISIONS:
        raise ValueError("INVALID_REVIEW_DECISION")
    if not reviewer.strip():
        raise ValueError("REVIEWER_REQUIRED")
    reasons = list(dict.fromkeys(reason_codes or []))
    invalid = sorted(set(reasons) - REVIEW_REASONS)
    if invalid:
        raise ValueError("INVALID_REVIEW_REASON")

    with Session(engine) as session:
        candidate = session.scalar(select(VisualFlowerCandidateRow).where(VisualFlowerCandidateRow.candidate_id == candidate_id))
        if candidate is None:
            raise LookupError("visual candidate not found")
        run = session.get(VisualFlowerGenerationRunRow, candidate.run_id)
        target = session.get(VisualProfileTargetRow, run.target_id) if run else None
        revision = (
            session.scalar(
                select(VisualProfileTargetRevisionRow).where(
                    VisualProfileTargetRevisionRow.target_id == target.id,
                    VisualProfileTargetRevisionRow.revision == target.current_revision,
                )
            )
            if target
            else None
        )
        candidate_payload = candidate.candidate_json or {}
        review_id = "vreview-" + sha256(
            f"{candidate_id}|{reviewer}|{decision}|{notes}|{len(reasons)}".encode()
        ).hexdigest()[:16]
        existing = session.scalar(
            select(VisualFlowerCandidateReviewRow).where(VisualFlowerCandidateReviewRow.review_id == review_id)
        )
        if existing:
            return candidate_review_dict(existing)
        row = VisualFlowerCandidateReviewRow(
            review_id=review_id,
            candidate_id=candidate_id,
            run_id=run.run_id if run else "UNKNOWN",
            candidate_type=str(candidate_payload.get("candidate_style", "UNKNOWN")),
            decision=decision,
            reason_codes_json=reasons,
            reviewer=reviewer.strip(),
            notes=notes,
            model_id=(
                (candidate_payload.get("learned_support") or {}).get("model_id")
                or candidate_payload.get("generation", {}).get("model_id")
            ),
            algorithm_version=(
                (candidate_payload.get("provenance") or {}).get("algorithm_version")
                or candidate_payload.get("algorithm_version")
            ),
            target_hash=profile_hash(revision.profile_json) if revision else None,
        )
        session.add(row)
        session.commit()
        return candidate_review_dict(row)


def candidate_review_dict(row: VisualFlowerCandidateReviewRow) -> dict[str, Any]:
    return {
        "review_id": row.review_id,
        "candidate_id": row.candidate_id,
        "run_id": row.run_id,
        "candidate_type": row.candidate_type,
        "decision": row.decision,
        "reason_codes": row.reason_codes_json,
        "reviewer": row.reviewer,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "model_id": row.model_id,
        "algorithm_version": row.algorithm_version,
        "target_hash": row.target_hash,
    }


def list_candidate_reviews(engine, candidate_id: str | None = None) -> list[dict[str, Any]]:
    with Session(engine) as session:
        query = select(VisualFlowerCandidateReviewRow)
        if candidate_id:
            query = query.where(VisualFlowerCandidateReviewRow.candidate_id == candidate_id)
        return [
            candidate_review_dict(row)
            for row in session.scalars(
                query.order_by(
                    VisualFlowerCandidateReviewRow.created_at,
                    VisualFlowerCandidateReviewRow.review_id,
                )
            )
        ]
