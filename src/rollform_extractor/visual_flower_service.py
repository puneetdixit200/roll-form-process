"""Persistence/service boundary for the visual flower workflow."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.database import VisualFlowerCandidateRow, VisualFlowerGenerationRunRow, VisualProfileTargetRevisionRow, VisualProfileTargetRow, create_project_database
from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_profile_schema import VisualProfileError, validate_profile
from rollform_extractor.visual_flower_exports import export_visual_run
from rollform_extractor.clrsg_inference import infer_learned_candidates, load_active_model


def profile_hash(profile: dict[str, Any]) -> str:
    return sha256(json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def historical_dataset() -> dict[str, Any]:
    configured = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
    if not configured:
        return {"dataset_hash": "UNCONFIGURED", "flowers": [], "source_classification": "NONE"}
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or path.name != "dataset.json":
        raise ValueError("configured visual prototype dataset is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def create_target(engine, payload: dict[str, Any]) -> dict[str, Any]:
    profile = validate_profile(payload.get("profile") or payload)
    target_id = str(payload.get("target_id") or "vtarget-" + profile_hash(profile.to_dict())[:16])
    with Session(engine) as session:
        existing = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        if existing:
            return target_summary(session, existing)
        row = VisualProfileTargetRow(target_id=target_id, name=profile.name, schema_version=1, topology=profile.topology, current_revision=1, status="DRAFT")
        session.add(row); session.flush()
        session.add(VisualProfileTargetRevisionRow(target_id=row.id, revision=1, input_hash=profile_hash(profile.to_dict()), profile_json=profile.to_dict(), validation_json={"valid": True}))
        session.commit()
        return target_summary(session, row)


def target_summary(session: Session, row: VisualProfileTargetRow) -> dict[str, Any]:
    revision = session.scalar(select(VisualProfileTargetRevisionRow).where(VisualProfileTargetRevisionRow.target_id == row.id, VisualProfileTargetRevisionRow.revision == row.current_revision))
    return {"target_id": row.target_id, "name": row.name, "topology": row.topology, "status": row.status, "revision": row.current_revision, "profile": revision.profile_json if revision else None, "input_hash": revision.input_hash if revision else None}


def list_targets(engine) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [target_summary(session, row) for row in session.scalars(select(VisualProfileTargetRow).order_by(VisualProfileTargetRow.target_id))]


def get_target(engine, target_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        return target_summary(session, row) if row else None


def generate_for_target(engine, target_id: str, preferences: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        target_row = session.scalar(select(VisualProfileTargetRow).where(VisualProfileTargetRow.target_id == target_id))
        if not target_row:
            raise LookupError("visual target not found")
        revision = session.scalar(select(VisualProfileTargetRevisionRow).where(VisualProfileTargetRevisionRow.target_id == target_row.id, VisualProfileTargetRevisionRow.revision == target_row.current_revision))
    profile = validate_profile(revision.profile_json)
    dataset = historical_dataset()
    result = generate_visual_candidates(profile, dataset.get("flowers", []), station_mode=preferences.get("station_mode", "AUTOMATIC"), exact_station_count=preferences.get("exact_station_count"), minimum_station_count=preferences.get("minimum_station_count", 8), maximum_station_count=preferences.get("maximum_station_count", 28), candidate_limit=preferences.get("candidate_limit", 3), allow_mirror_matching=preferences.get("allow_mirror_matching", True), allow_rotation_alignment=preferences.get("allow_rotation_alignment", False))
    engine_mode = str(preferences.get("generation_engine", "AUTO")).upper()
    if engine_mode in {"AUTO", "COMPARE_ALL", "LEARNED_HYBRID"}:
        learned = infer_learned_candidates(profile, result, load_active_model())
        result["learned_model"] = {"status": learned["status"], "warnings": learned.get("warnings", [])}
        if engine_mode in {"AUTO", "COMPARE_ALL", "LEARNED_HYBRID"} and learned.get("candidates"):
            result["candidates"] = (result.get("candidates", []) if engine_mode == "COMPARE_ALL" else result.get("candidates", [])[:1]) + learned["candidates"]
    else:
        result["learned_model"] = {"status": "DETERMINISTIC_ONLY", "warnings": []}
    run_key = "vrun-" + sha256(f"{target_id}|{revision.input_hash}|{json.dumps(preferences, sort_keys=True)}|{dataset.get('dataset_hash')}".encode()).hexdigest()[:16]
    with Session(engine) as session:
        existing = session.scalar(select(VisualFlowerGenerationRunRow).where(VisualFlowerGenerationRunRow.run_id == run_key))
        if existing is not None:
            return existing.result_json | {"run_id": existing.run_id, "status": existing.status}
        run_status = "READY" if result["candidates"] else "NO_HISTORICAL_SUPPORT"
        run = VisualFlowerGenerationRunRow(run_id=run_key, target_id=target_row.id, algorithm_version=result["algorithm_version"], dataset_hash=dataset.get("dataset_hash", "UNCONFIGURED"), configuration_hash=sha256(json.dumps(preferences, sort_keys=True).encode()).hexdigest(), status=run_status, warnings_json=result.get("warnings", []) + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else []), result_json=result)
        session.add(run); session.flush()
        for candidate in result["candidates"]:
            session.add(VisualFlowerCandidateRow(candidate_id=candidate["candidate_id"], run_id=run.id, candidate_json=candidate, status=candidate["status"], visual_confidence=candidate["visual_confidence"]["score"]))
        session.commit()
    return {"run_id": run_key, "status": run_status, "target_id": target_id, "candidate_ids": [item["candidate_id"] for item in result["candidates"]], "candidates": result["candidates"], "warnings": result.get("warnings", []) + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else [])}


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
    export_visual_run({"schema_version": 1, "candidates": [candidate], "source_cad_included": False}, directory)
    return directory
