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
    VisualFlowerCandidateReviewRow,
    VisualFlowerCandidateRow,
    VisualFlowerGenerationRunRow,
    VisualProfileTargetRevisionRow,
    VisualProfileTargetRow,
    create_project_database,
)
from rollform_extractor.strip_length_constraint import STRIP_LENGTH_CONSTRAINT_VERSION
from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_flower_exports import export_visual_run
from rollform_extractor.visual_profile_schema import (
    VISUAL_ALGORITHM_VERSION,
    VisualProfileError,
    validate_profile,
)


def profile_hash(profile: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            profile,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def historical_dataset() -> dict[str, Any]:
    configured = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
    if not configured:
        return {
            "dataset_hash": "UNCONFIGURED",
            "flowers": [],
            "source_classification": "NONE",
        }
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or path.name != "dataset.json":
        raise ValueError("configured visual prototype dataset is unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


def create_target(engine, payload: dict[str, Any]) -> dict[str, Any]:
    profile = validate_profile(payload.get("profile") or payload)
    target_id = str(
        payload.get("target_id")
        or "vtarget-" + profile_hash(profile.to_dict())[:16]
    )
    with Session(engine) as session:
        existing = session.scalar(
            select(VisualProfileTargetRow).where(
                VisualProfileTargetRow.target_id == target_id
            )
        )
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
            for row in session.scalars(
                select(VisualProfileTargetRow).order_by(
                    VisualProfileTargetRow.target_id
                )
            )
        ]


def get_target(engine, target_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(
            select(VisualProfileTargetRow).where(
                VisualProfileTargetRow.target_id == target_id
            )
        )
        return target_summary(session, row) if row else None


def _generation_configuration(preferences: dict[str, Any]) -> dict[str, Any]:
    """Version persisted runs so stale pre-constraint results are never reused."""
    return {
        "preferences": preferences,
        "visual_algorithm_version": VISUAL_ALGORITHM_VERSION,
        "strip_length_constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
    }


def generate_for_target(
    engine,
    target_id: str,
    preferences: dict[str, Any],
) -> dict[str, Any]:
    with Session(engine) as session:
        target_row = session.scalar(
            select(VisualProfileTargetRow).where(
                VisualProfileTargetRow.target_id == target_id
            )
        )
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
    result = generate_visual_candidates(
        profile,
        dataset.get("flowers", []),
        station_mode=preferences.get("station_mode", "AUTOMATIC"),
        exact_station_count=preferences.get("exact_station_count"),
        minimum_station_count=preferences.get("minimum_station_count", 8),
        maximum_station_count=preferences.get("maximum_station_count", 28),
        candidate_limit=preferences.get("candidate_limit", 3),
        allow_mirror_matching=preferences.get("allow_mirror_matching", True),
        allow_rotation_alignment=preferences.get(
            "allow_rotation_alignment",
            False,
        ),
    )

    engine_mode = str(preferences.get("generation_engine", "AUTO")).upper()
    if engine_mode in {"AUTO", "COMPARE_ALL", "LEARNED_HYBRID"}:
        learned = infer_learned_candidates(
            profile,
            result,
            load_active_model(),
        )
        result["learned_model"] = {
            "status": learned["status"],
            "warnings": learned.get("warnings", []),
        }
        if learned.get("candidates"):
            result["candidates"] = (
                result.get("candidates", [])
                if engine_mode == "COMPARE_ALL"
                else result.get("candidates", [])[:1]
            ) + learned["candidates"]
    else:
        result["learned_model"] = {
            "status": "DETERMINISTIC_ONLY",
            "warnings": [],
        }

    configuration = _generation_configuration(preferences)
    configuration_json = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
    )
    run_key = "vrun-" + sha256(
        (
            f"{target_id}|{revision.input_hash}|{configuration_json}|"
            f"{dataset.get('dataset_hash')}"
        ).encode()
    ).hexdigest()[:16]
    configuration_hash = sha256(configuration_json.encode()).hexdigest()

    with Session(engine) as session:
        existing = session.scalar(
            select(VisualFlowerGenerationRunRow).where(
                VisualFlowerGenerationRunRow.run_id == run_key
            )
        )
        if existing is not None:
            return existing.result_json | {
                "run_id": existing.run_id,
                "status": existing.status,
            }

        run_status = "READY" if result["candidates"] else "NO_HISTORICAL_SUPPORT"
        run = VisualFlowerGenerationRunRow(
            run_id=run_key,
            target_id=target_row.id,
            algorithm_version=result["algorithm_version"],
            dataset_hash=dataset.get("dataset_hash", "UNCONFIGURED"),
            configuration_hash=configuration_hash,
            status=run_status,
            warnings_json=result.get("warnings", [])
            + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else []),
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
        session.commit()

    return {
        "run_id": run_key,
        "status": run_status,
        "target_id": target_id,
        "candidate_ids": [
            item["candidate_id"] for item in result["candidates"]
        ],
        "candidates": result["candidates"],
        "warnings": result.get("warnings", [])
        + (["NO_HISTORICAL_SUPPORT"] if not result["candidates"] else []),
    }


def get_run(engine, run_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(
            select(VisualFlowerGenerationRunRow).where(
                VisualFlowerGenerationRunRow.run_id == run_id
            )
        )
        return (
            row.result_json | {"run_id": row.run_id, "status": row.status}
            if row
            else None
        )


def get_candidate(engine, candidate_id: str) -> dict[str, Any] | None:
    with Session(engine) as session:
        row = session.scalar(
            select(VisualFlowerCandidateRow).where(
                VisualFlowerCandidateRow.candidate_id == candidate_id
            )
        )
        return row.candidate_json if row else None


def export_candidate(
    engine,
    candidate_id: str,
    output_root: Path,
) -> Path | None:
    candidate = get_candidate(engine, candidate_id)
    if candidate is None:
        return None
    directory = output_root / "visual_exports" / candidate_id
    export_visual_run(
        {
            "schema_version": 1,
            "candidates": [candidate],
            "source_cad_included": False,
        },
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
        candidate = session.scalar(
            select(VisualFlowerCandidateRow).where(
                VisualFlowerCandidateRow.candidate_id == candidate_id
            )
        )
        if candidate is None:
            raise LookupError("visual candidate not found")
        run = session.get(VisualFlowerGenerationRunRow, candidate.run_id)
        target = (
            session.get(VisualProfileTargetRow, run.target_id)
            if run
            else None
        )
        revision = (
            session.scalar(
                select(VisualProfileTargetRevisionRow).where(
                    VisualProfileTargetRevisionRow.target_id == target.id,
                    VisualProfileTargetRevisionRow.revision
                    == target.current_revision,
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
            select(VisualFlowerCandidateReviewRow).where(
                VisualFlowerCandidateReviewRow.review_id == review_id
            )
        )
        if existing:
            return candidate_review_dict(existing)
        row = VisualFlowerCandidateReviewRow(
            review_id=review_id,
            candidate_id=candidate_id,
            run_id=run.run_id if run else "UNKNOWN",
            candidate_type=str(
                candidate_payload.get("candidate_style", "UNKNOWN")
            ),
            decision=decision,
            reason_codes_json=reasons,
            reviewer=reviewer.strip(),
            notes=notes,
            model_id=(
                (candidate_payload.get("learned_support") or {}).get("model_id")
                or candidate_payload.get("generation", {}).get("model_id")
            ),
            algorithm_version=(
                (candidate_payload.get("provenance") or {}).get(
                    "algorithm_version"
                )
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


def list_candidate_reviews(
    engine,
    candidate_id: str | None = None,
) -> list[dict[str, Any]]:
    with Session(engine) as session:
        query = select(VisualFlowerCandidateReviewRow)
        if candidate_id:
            query = query.where(
                VisualFlowerCandidateReviewRow.candidate_id == candidate_id
            )
        return [
            candidate_review_dict(row)
            for row in session.scalars(
                query.order_by(
                    VisualFlowerCandidateReviewRow.created_at,
                    VisualFlowerCandidateReviewRow.review_id,
                )
            )
        ]
