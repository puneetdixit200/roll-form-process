"""Engineer-labelled recognition validation and historical design usage.

This module deliberately stops at confirmed *design* evidence.  It never
assigns a physical roller asset or produces a tooling recommendation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import csv
import json
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from rollform_extractor.database import (
    ConfirmedRollerDesignUsage,
    Project,
    RecognitionAdjudication,
    RecognitionEvaluationCase,
    RecognitionEvaluationDataset,
    RecognitionLabelAssertion,
    RecognitionThresholdEvaluation,
    RecognitionThresholdProfile,
    RollerAuditEvent,
    RollerGeometryRevision,
    RollerRecognitionCandidate,
    RollerRecognitionInput,
    RollerRecognitionRun,
    RollerUsagePromotion,
    RollerUsageRelationship,
    RollerUsageRelationshipSnapshot,
)

PHASE18_SCHEMA_VERSION = 1
PHASE18_ALGORITHM_VERSION = "validated-usage-v1"
OUTCOMES = {"MATCH_DESIGN", "NO_CATALOG_MATCH", "NOT_A_ROLLER", "INSUFFICIENT_DRAWING_EVIDENCE", "UNRESOLVED"}
DATASET_KINDS = {"SYNTHETIC", "ENGINEER_LABELLED", "PRODUCTION_CONFIRMED"}
DATASET_STATUSES = {"DRAFT", "IN_REVIEW", "LOCKED", "APPROVED_FOR_CALIBRATION", "APPROVED_FOR_VALIDATION", "RETIRED"}
SPLITS = {"CALIBRATION", "VALIDATION", "HOLDOUT"}


def _now() -> datetime:
    return datetime.now(UTC)


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_clean(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def stable_hash(value: Any) -> str:
    payload = json.dumps(_clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _audit(session: Session, entity_type: str, entity_key: str, action: str, actor: str | None, after: Any = None) -> None:
    session.add(RollerAuditEvent(entity_type=entity_type, entity_key=entity_key, action=action, actor=actor, after_json=_clean(after), source="phase18"))


@dataclass(frozen=True)
class Agreement:
    state: str
    assertion_count: int
    outcomes: tuple[str, ...]
    design_ids: tuple[str, ...]
    revision_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_evaluation_dataset(
    engine: Engine,
    name: str,
    kind: str,
    created_by: str,
    description: str = "",
    inventory_snapshot_hash: str = "",
    recognition_algorithm_version: str = "roller-recognition-v1",
    feature_schema_version: int = 1,
) -> dict[str, Any]:
    kind = kind.upper()
    if kind not in DATASET_KINDS:
        raise ValueError(f"unsupported dataset kind: {kind}")
    if not created_by.strip():
        raise ValueError("created_by is required")
    with Session(engine) as session, session.begin():
        version = (session.scalar(select(func.max(RecognitionEvaluationDataset.version)).where(RecognitionEvaluationDataset.name == name)) or 0) + 1
        dataset_id = f"EDS-{stable_hash({'name': name, 'version': version, 'kind': kind})[:12]}"
        row = RecognitionEvaluationDataset(
            dataset_id=dataset_id, name=name, kind=kind, version=version, description=description,
            created_by=created_by, inventory_snapshot_hash=inventory_snapshot_hash,
            recognition_algorithm_version=recognition_algorithm_version,
            feature_schema_version=feature_schema_version,
            split_strategy="PROJECT_GROUPED_DETERMINISTIC", limitations_json=["Not production approval by itself"],
        )
        session.add(row)
        _audit(session, "recognition_evaluation_dataset", dataset_id, "CREATE", created_by, {"kind": kind, "version": version})
        session.flush()
        return {"dataset_id": dataset_id, "version": version, "status": row.status, "kind": kind}


def _dataset(session: Session, dataset_id: str) -> RecognitionEvaluationDataset:
    row = session.scalar(select(RecognitionEvaluationDataset).where(RecognitionEvaluationDataset.dataset_id == dataset_id))
    if row is None:
        raise LookupError(f"evaluation dataset not found: {dataset_id}")
    return row


def add_evaluation_case(
    engine: Engine,
    dataset_id: str,
    project_id: int,
    occurrence_id: str,
    recognition_input_id: int | None = None,
    split: str = "CALIBRATION",
    case_key: str | None = None,
    quality_flags: list[str] | None = None,
    source_handles: list[str] | None = None,
) -> dict[str, Any]:
    split = split.upper()
    if split not in SPLITS:
        raise ValueError(f"unsupported split: {split}")
    with Session(engine) as session, session.begin():
        dataset = _dataset(session, dataset_id)
        if dataset.status not in {"DRAFT", "IN_REVIEW"}:
            raise ValueError("locked or approved datasets cannot be edited")
        if session.get(Project, project_id) is None:
            raise LookupError(f"project not found: {project_id}")
        input_row = session.get(RollerRecognitionInput, recognition_input_id) if recognition_input_id is not None else None
        if recognition_input_id is not None and input_row is None:
            raise LookupError(f"recognition input not found: {recognition_input_id}")
        key = case_key or f"{project_id}:{occurrence_id}"
        row = RecognitionEvaluationCase(
            dataset_id=dataset.id, case_key=key, project_id=project_id, occurrence_id=occurrence_id,
            recognition_input_id=recognition_input_id,
            recognition_input_hash=input_row.input_hash if input_row else None,
            inventory_snapshot_hash=dataset.inventory_snapshot_hash,
            split=split, quality_flags_json=quality_flags or [], source_handles_json=source_handles or (input_row.source_handles_json if input_row else []),
        )
        session.add(row)
        session.flush()
        _audit(session, "recognition_evaluation_case", str(row.id), "CREATE", None, {"dataset_id": dataset_id, "occurrence_id": occurrence_id})
        return {"case_id": row.id, "dataset_id": dataset_id, "split": split, "status": row.case_status}


def submit_label_assertion(
    engine: Engine,
    case_id: int,
    reviewer: str,
    outcome: str,
    reason_code: str,
    expected_design_id: str | None = None,
    expected_revision_id: str | None = None,
    confidence: float | None = None,
    evidence: Mapping[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    outcome = outcome.upper()
    if outcome not in OUTCOMES:
        raise ValueError(f"unsupported label outcome: {outcome}")
    if not reviewer.strip() or not reason_code.strip():
        raise ValueError("reviewer and reason_code are required")
    if outcome == "MATCH_DESIGN" and not expected_design_id:
        raise ValueError("MATCH_DESIGN requires expected_design_id")
    if outcome != "MATCH_DESIGN" and expected_design_id:
        raise ValueError(f"{outcome} cannot specify expected_design_id")
    if not 0.0 <= (confidence if confidence is not None else 0.0) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    with Session(engine) as session, session.begin():
        case = session.get(RecognitionEvaluationCase, case_id)
        if case is None:
            raise LookupError(f"evaluation case not found: {case_id}")
        dataset = session.get(RecognitionEvaluationDataset, case.dataset_id)
        if dataset is None or dataset.status not in {"DRAFT", "IN_REVIEW"}:
            raise ValueError("case dataset is not mutable")
        if session.scalar(select(RecognitionLabelAssertion).where(RecognitionLabelAssertion.case_id == case_id, RecognitionLabelAssertion.reviewer == reviewer, RecognitionLabelAssertion.supersedes_assertion_id.is_(None))):
            raise ValueError("reviewer already submitted an active assertion for this case")
        if expected_revision_id:
            revision = session.scalar(select(RollerGeometryRevision).where(RollerGeometryRevision.revision_id == expected_revision_id))
            if revision is None or revision.design_id != expected_design_id:
                raise ValueError("expected revision does not belong to expected design")
        row = RecognitionLabelAssertion(case_id=case_id, reviewer=reviewer, outcome=outcome, expected_design_id=expected_design_id, expected_revision_id=expected_revision_id, confidence=confidence, reason_code=reason_code, evidence_json=dict(evidence or {}), notes=notes)
        session.add(row)
        session.flush()
        _audit(session, "recognition_label_assertion", str(row.id), "SUBMIT", reviewer, {"case_id": case_id, "outcome": outcome})
        return {"assertion_id": row.id, "case_id": case_id, "outcome": outcome, "reviewer": reviewer}


def calculate_review_agreement(engine: Engine, case_id: int) -> Agreement:
    with Session(engine) as session:
        assertions = session.scalars(select(RecognitionLabelAssertion).where(RecognitionLabelAssertion.case_id == case_id, RecognitionLabelAssertion.supersedes_assertion_id.is_(None)).order_by(RecognitionLabelAssertion.id)).all()
        if len(assertions) < 2:
            state = "PENDING_SECOND_REVIEW"
        else:
            signatures = {(a.outcome, a.expected_design_id, a.expected_revision_id) for a in assertions}
            state = "AGREED" if len(signatures) == 1 else "ADJUDICATION_REQUIRED"
        return Agreement(state, len(assertions), tuple(a.outcome for a in assertions), tuple(a.expected_design_id for a in assertions if a.expected_design_id), tuple(a.expected_revision_id for a in assertions if a.expected_revision_id))


def adjudicate_case(
    engine: Engine,
    case_id: int,
    adjudicator: str,
    final_outcome: str,
    reason_code: str,
    selected_design_id: str | None = None,
    selected_revision_id: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    final_outcome = final_outcome.upper()
    if final_outcome not in OUTCOMES:
        raise ValueError(f"unsupported adjudication outcome: {final_outcome}")
    if final_outcome == "MATCH_DESIGN" and not selected_design_id:
        raise ValueError("MATCH_DESIGN adjudication requires selected_design_id")
    if final_outcome != "MATCH_DESIGN" and selected_design_id:
        raise ValueError("non-match adjudication cannot select a design")
    with Session(engine) as session, session.begin():
        case = session.get(RecognitionEvaluationCase, case_id)
        if case is None:
            raise LookupError(f"evaluation case not found: {case_id}")
        if len(session.scalars(select(RecognitionLabelAssertion).where(RecognitionLabelAssertion.case_id == case_id, RecognitionLabelAssertion.supersedes_assertion_id.is_(None))).all()) < 2:
            raise ValueError("adjudication requires two independent assertions")
        if selected_revision_id:
            revision = session.scalar(select(RollerGeometryRevision).where(RollerGeometryRevision.revision_id == selected_revision_id))
            if revision is None or revision.design_id != selected_design_id:
                raise ValueError("selected revision does not belong to selected design")
        row = RecognitionAdjudication(case_id=case_id, adjudicator=adjudicator, final_outcome=final_outcome, selected_design_id=selected_design_id, selected_revision_id=selected_revision_id, reason_code=reason_code, evidence_json=dict(evidence or {}), notes=notes)
        session.add(row)
        case.gold_outcome = final_outcome
        case.expected_design_id = selected_design_id
        case.expected_revision_id = selected_revision_id
        case.case_status = "EXCLUDED" if final_outcome == "UNRESOLVED" else "ADJUDICATED"
        session.flush()
        _audit(session, "recognition_adjudication", str(row.id), "ADJUDICATE", adjudicator, {"case_id": case_id, "outcome": final_outcome})
        return {"adjudication_id": row.id, "case_id": case_id, "final_outcome": final_outcome, "case_status": case.case_status}


def _dataset_payload(session: Session, dataset: RecognitionEvaluationDataset) -> dict[str, Any]:
    cases = session.scalars(select(RecognitionEvaluationCase).where(RecognitionEvaluationCase.dataset_id == dataset.id).order_by(RecognitionEvaluationCase.id)).all()
    assertions = session.scalars(select(RecognitionLabelAssertion).where(RecognitionLabelAssertion.case_id.in_([c.id for c in cases]) if cases else False).order_by(RecognitionLabelAssertion.id)).all()
    adjudications = session.scalars(select(RecognitionAdjudication).where(RecognitionAdjudication.case_id.in_([c.id for c in cases]) if cases else False).order_by(RecognitionAdjudication.id)).all()
    return {"dataset": {"dataset_id": dataset.dataset_id, "name": dataset.name, "kind": dataset.kind, "version": dataset.version, "status": dataset.status, "inventory_snapshot_hash": dataset.inventory_snapshot_hash, "algorithm_version": dataset.recognition_algorithm_version, "feature_schema_version": dataset.feature_schema_version}, "cases": [_clean({k: getattr(c, k) for k in ("id", "case_key", "project_id", "occurrence_id", "recognition_input_id", "recognition_input_hash", "inventory_snapshot_hash", "split", "case_status", "gold_outcome", "expected_design_id", "expected_revision_id", "quality_flags_json", "source_handles_json")}) for c in cases], "assertions": [_clean({k: getattr(a, k) for k in ("id", "case_id", "reviewer", "outcome", "expected_design_id", "expected_revision_id", "confidence", "reason_code", "evidence_json", "notes", "supersedes_assertion_id")}) for a in assertions], "adjudications": [_clean({k: getattr(a, k) for k in ("id", "case_id", "adjudicator", "final_outcome", "selected_design_id", "selected_revision_id", "reason_code", "evidence_json", "notes", "supersedes_adjudication_id")}) for a in adjudications]}


def validate_dataset(engine: Engine, dataset_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        dataset = _dataset(session, dataset_id)
        cases = session.scalars(select(RecognitionEvaluationCase).where(RecognitionEvaluationCase.dataset_id == dataset.id)).all()
        issues: list[str] = []
        splits: dict[int, str] = {}
        for case in cases:
            prior = splits.setdefault(case.project_id, case.split)
            if prior != case.split:
                issues.append(f"project {case.project_id} appears in multiple splits")
            if case.case_status not in {"ADJUDICATED", "EXCLUDED"}:
                issues.append(f"case {case.id} is unresolved")
            if case.gold_outcome == "MATCH_DESIGN" and not case.expected_design_id:
                issues.append(f"case {case.id} match has no design")
            if case.gold_outcome != "MATCH_DESIGN" and case.expected_design_id:
                issues.append(f"case {case.id} negative outcome has a design")
        payload = _dataset_payload(session, dataset)
        content_hash = stable_hash(payload)
        return {"valid": not issues, "issues": issues, "dataset_id": dataset_id, "case_count": len(cases), "project_count": len({c.project_id for c in cases}), "content_hash": content_hash, "status": dataset.status}


def lock_dataset_version(engine: Engine, dataset_id: str, locked_by: str) -> dict[str, Any]:
    report = validate_dataset(engine, dataset_id)
    if not report["valid"]:
        raise ValueError("dataset cannot be locked: " + "; ".join(report["issues"]))
    with Session(engine) as session, session.begin():
        dataset = _dataset(session, dataset_id)
        if dataset.status not in {"DRAFT", "IN_REVIEW"}:
            raise ValueError("dataset is already immutable")
        dataset.status = "LOCKED"
        dataset.locked_by = locked_by
        dataset.locked_at = _now()
        dataset.content_hash = report["content_hash"]
        dataset.case_count = report["case_count"]
        dataset.project_count = report["project_count"]
        dataset.design_count = len({c.expected_design_id for c in session.scalars(select(RecognitionEvaluationCase).where(RecognitionEvaluationCase.dataset_id == dataset.id)) if c.expected_design_id})
        _audit(session, "recognition_evaluation_dataset", dataset_id, "LOCK", locked_by, report)
        return {"dataset_id": dataset_id, "status": dataset.status, "content_hash": dataset.content_hash, "case_count": dataset.case_count}


def export_evaluation_dataset(engine: Engine, dataset_id: str, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        dataset = _dataset(session, dataset_id)
        payload = _dataset_payload(session, dataset)
        validation = validate_dataset(engine, dataset_id)
    (output / "dataset.json").write_text(json.dumps(payload["dataset"], indent=2, sort_keys=True), encoding="utf-8")
    (output / "cases.json").write_text(json.dumps(payload["cases"], indent=2, sort_keys=True), encoding="utf-8")
    (output / "label_assertions.json").write_text(json.dumps(payload["assertions"], indent=2, sort_keys=True), encoding="utf-8")
    (output / "adjudications.json").write_text(json.dumps(payload["adjudications"], indent=2, sort_keys=True), encoding="utf-8")
    (output / "dataset_validation.json").write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    (output / "dataset_hash.txt").write_text(validation["content_hash"] + "\n", encoding="utf-8")
    return output


def evaluate_threshold_profile(engine: Engine, dataset_id: str, configuration: Mapping[str, Any], output: Path | None = None, created_by: str = "system") -> dict[str, Any]:
    report = validate_dataset(engine, dataset_id)
    if not report["valid"]:
        raise ValueError("dataset is not valid: " + "; ".join(report["issues"]))
    with Session(engine) as session, session.begin():
        dataset = _dataset(session, dataset_id)
        cases = session.scalars(select(RecognitionEvaluationCase).where(RecognitionEvaluationCase.dataset_id == dataset.id, RecognitionEvaluationCase.case_status == "ADJUDICATED").order_by(RecognitionEvaluationCase.id)).all()
        config_hash = stable_hash(configuration)
        rows: list[dict[str, Any]] = []
        for case in cases:
            candidates = []
            if case.recognition_input_id:
                candidates = session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.input_id == case.recognition_input_id).order_by(RollerRecognitionCandidate.rank)).all()
            top = candidates[0] if candidates else None
            rows.append({"case_id": case.id, "outcome": case.gold_outcome, "expected_design_id": case.expected_design_id, "top_design_id": top.design_id if top else None, "top_score": top.overall_score if top else None, "top_status": top.candidate_status if top else "NO_MATCH"})
        matches = [r for r in rows if r["outcome"] == "MATCH_DESIGN"]
        top1 = sum(r["top_design_id"] == r["expected_design_id"] for r in matches)
        accepted = [r for r in rows if r["top_design_id"] is not None and r["top_status"] != "AMBIGUOUS"]
        false_high = sum(bool(r["top_score"] is not None and r["top_score"] >= float(configuration.get("thresholds", {}).get("high_candidate", 0.9)) and r["top_design_id"] != r["expected_design_id"]) for r in rows if r["outcome"] == "MATCH_DESIGN")
        metrics = {"sample_count": len(rows), "match_design_count": len(matches), "top_1_accuracy": top1 / len(matches) if matches else 0.0, "coverage": len(accepted) / len(rows) if rows else 0.0, "accuracy_non_abstained": sum(r["top_design_id"] == r["expected_design_id"] for r in accepted) / len(accepted) if accepted else 0.0, "false_high_confidence_count": false_high, "warnings": ["INSUFFICIENT SAMPLE SIZE"] if len(matches) < 20 else []}
        evaluation_id = f"TE-{stable_hash({'dataset': dataset_id, 'config': config_hash, 'rows': rows})[:12]}"
        session.add(RecognitionThresholdEvaluation(evaluation_id=evaluation_id, dataset_id=dataset.id, metrics_json=metrics, output_hash=stable_hash(rows)))
        profile_id = f"TP-{stable_hash({'dataset': dataset_id, 'config': config_hash})[:12]}"
        profile = RecognitionThresholdProfile(profile_id=profile_id, name=f"evaluation-{dataset.name}-{dataset.version}", algorithm_version=dataset.recognition_algorithm_version or "roller-recognition-v1", feature_schema_version=dataset.feature_schema_version or 1, configuration_json=dict(configuration), configuration_hash=config_hash, calibration_dataset_hash=dataset.content_hash or report["content_hash"], validation_dataset_hash=dataset.content_hash or report["content_hash"], status="EVALUATED", metric_summary_json=metrics, created_by=created_by)
        session.add(profile)
        _audit(session, "recognition_threshold_profile", profile_id, "EVALUATE", created_by, metrics)
    result = {"evaluation_id": evaluation_id, "profile_id": profile_id, "status": "EVALUATED", "configuration_hash": config_hash, "metrics": metrics, "rows": rows}
    if output:
        output.mkdir(parents=True, exist_ok=True)
        (output / "profile.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def approve_threshold_profile(engine: Engine, profile_id: str, reviewer: str, notes: str) -> dict[str, Any]:
    if not reviewer.strip() or not notes.strip():
        raise ValueError("reviewer and approval notes are required")
    with Session(engine) as session, session.begin():
        row = session.scalar(select(RecognitionThresholdProfile).where(RecognitionThresholdProfile.profile_id == profile_id))
        if row is None:
            raise LookupError(f"threshold profile not found: {profile_id}")
        if row.status != "EVALUATED":
            raise ValueError("only EVALUATED profiles can be approved")
        row.status = "ENGINEER_APPROVED"
        row.approved_by = reviewer
        row.approved_at = _now()
        row.approval_notes = notes
        _audit(session, "recognition_threshold_profile", profile_id, "APPROVE", reviewer, {"configuration_hash": row.configuration_hash})
        return {"profile_id": profile_id, "status": row.status, "approved_by": reviewer, "configuration_hash": row.configuration_hash}


def promote_confirmed_usage(engine: Engine, case_id: int, promoter: str, notes: str = "") -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        case = session.get(RecognitionEvaluationCase, case_id)
        if case is None:
            raise LookupError(f"evaluation case not found: {case_id}")
        dataset = session.get(RecognitionEvaluationDataset, case.dataset_id)
        if dataset is None or dataset.status not in {"LOCKED", "APPROVED_FOR_CALIBRATION", "APPROVED_FOR_VALIDATION"}:
            raise ValueError("usage promotion requires an immutable dataset")
        adjudication = session.scalar(select(RecognitionAdjudication).where(RecognitionAdjudication.case_id == case_id).order_by(RecognitionAdjudication.id.desc()))
        if adjudication is None or adjudication.final_outcome != "MATCH_DESIGN" or not adjudication.selected_design_id:
            raise ValueError("only an adjudicated MATCH_DESIGN case can be promoted")
        if not case.recognition_input_hash:
            raise ValueError("case has no immutable recognition input hash")
        revision = session.scalar(select(RollerGeometryRevision).where(RollerGeometryRevision.revision_id == adjudication.selected_revision_id)) if adjudication.selected_revision_id else None
        if adjudication.selected_revision_id and (revision is None or revision.design_id != adjudication.selected_design_id):
            raise ValueError("selected revision does not belong to selected design")
        usage_id = f"USE-{stable_hash({'case': case.id, 'input': case.recognition_input_hash, 'design': adjudication.selected_design_id})[:12]}"
        existing = session.scalar(select(ConfirmedRollerDesignUsage).where(ConfirmedRollerDesignUsage.usage_id == usage_id))
        if existing is not None:
            raise ValueError("case has already been promoted")
        input_row = session.get(RollerRecognitionInput, case.recognition_input_id) if case.recognition_input_id else None
        row = ConfirmedRollerDesignUsage(usage_id=usage_id, project_id=case.project_id, occurrence_id=case.occurrence_id, recognition_input_hash=case.recognition_input_hash, design_id=adjudication.selected_design_id, geometry_revision_id=adjudication.selected_revision_id, station_id=input_row.station_id if input_row else None, role=input_row.role if input_row else None, source_adjudication_id=adjudication.id, source_dataset_id=dataset.id, source_dataset_hash=dataset.content_hash or "", inventory_snapshot_hash=case.inventory_snapshot_hash, confirmed_by=promoter, source_handles_json=input_row.source_handles_json if input_row else case.source_handles_json, evidence_json=adjudication.evidence_json, provenance_json={"phase": "18", "case_id": case.id, "recognition_input_hash": case.recognition_input_hash})
        session.add(row)
        session.add(RollerUsagePromotion(case_id=case.id, usage_id=usage_id, action="PROMOTE", promoted_by=promoter, notes=notes, input_hash=case.recognition_input_hash))
        _audit(session, "confirmed_roller_design_usage", usage_id, "PROMOTE", promoter, {"design_id": row.design_id, "physical_asset_assignment": False})
        return {"usage_id": usage_id, "design_id": row.design_id, "confirmation_status": row.confirmation_status, "physical_asset_id": None}


def detect_stale_confirmations(engine: Engine, project_id: int | None = None) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    with Session(engine) as session, session.begin():
        query = select(ConfirmedRollerDesignUsage).where(ConfirmedRollerDesignUsage.confirmation_status == "CONFIRMED")
        if project_id is not None:
            query = query.where(ConfirmedRollerDesignUsage.project_id == project_id)
        for usage in session.scalars(query.order_by(ConfirmedRollerDesignUsage.id)).all():
            current = session.scalar(select(RollerRecognitionInput).join(RollerRecognitionRun, RollerRecognitionInput.run_id == RollerRecognitionRun.id).where(RollerRecognitionRun.project_id == usage.project_id, RollerRecognitionInput.occurrence_id == usage.occurrence_id).order_by(RollerRecognitionInput.id.desc()))
            if current is None:
                usage.confirmation_status = "STALE_SOURCE"
                usage.stale_reason = "occurrence_missing_after_reextraction"
            elif current.input_hash != usage.recognition_input_hash:
                usage.confirmation_status = "STALE_SOURCE"
                usage.stale_reason = "recognition_input_hash_changed"
            else:
                continue
            changed.append({"usage_id": usage.usage_id, "status": usage.confirmation_status, "reason": usage.stale_reason})
            _audit(session, "confirmed_roller_design_usage", usage.usage_id, "STALE", None, changed[-1])
    return changed


def revoke_confirmed_usage(engine: Engine, usage_id: str, actor: str, notes: str = "") -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        row = session.scalar(select(ConfirmedRollerDesignUsage).where(ConfirmedRollerDesignUsage.usage_id == usage_id))
        if row is None:
            raise LookupError(f"usage not found: {usage_id}")
        row.confirmation_status = "REVOKED"
        row.valid_to = _now()
        row.stale_reason = notes or "revoked_by_engineer"
        _audit(session, "confirmed_roller_design_usage", usage_id, "REVOKE", actor, {"notes": notes})
        return {"usage_id": usage_id, "confirmation_status": row.confirmation_status}


def build_usage_relationship_snapshot(engine: Engine, created_by: str = "system", include_synthetic: bool = False) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        usages = session.scalars(select(ConfirmedRollerDesignUsage).where(ConfirmedRollerDesignUsage.confirmation_status == "CONFIRMED").order_by(ConfirmedRollerDesignUsage.id)).all()
        grouped: dict[tuple[str, str], list[ConfirmedRollerDesignUsage]] = {}
        for usage in usages:
            dataset = session.get(RecognitionEvaluationDataset, usage.source_dataset_id)
            if dataset and dataset.kind == "SYNTHETIC" and not include_synthetic:
                continue
            grouped.setdefault(("DESIGN_USED_FOR_ROLE", usage.design_id + "\0" + (usage.role or "UNKNOWN")), []).append(usage)
        records: list[dict[str, Any]] = []
        for (rtype, key), items in sorted(grouped.items()):
            source, target = key.split("\0", 1)
            projects = {item.project_id for item in items}
            records.append({"relationship_type": rtype, "source_entity": source, "target_entity": target, "confirmed_occurrence_count": len(items), "distinct_project_count": len(projects), "distinct_assembly_count": len({item.assembly_id for item in items if item.assembly_id}), "support": float(len(projects)), "reliability_descriptor": "DESCRIPTIVE_ONLY", "dataset_scope": "OPERATIONAL_CONFIRMED", "supporting_usage_ids": sorted(item.usage_id for item in items), "limitations": ["Historical association is not compatibility or recommendation"]})
        payload = {"algorithm_version": PHASE18_ALGORITHM_VERSION, "include_synthetic": include_synthetic, "relationships": records}
        content_hash = stable_hash(payload)
        snapshot_id = f"RLS-{content_hash[:12]}"
        snapshot = RollerUsageRelationshipSnapshot(snapshot_id=snapshot_id, algorithm_version=PHASE18_ALGORITHM_VERSION, configuration_hash=stable_hash({"include_synthetic": include_synthetic}), dataset_scope="OPERATIONAL_CONFIRMED", content_hash=content_hash, created_by=created_by, diagnostics_json={"relationship_count": len(records)})
        session.add(snapshot)
        session.flush()
        for record in records:
            session.add(RollerUsageRelationship(snapshot_id=snapshot.id, relationship_type=record["relationship_type"], source_entity=record["source_entity"], target_entity=record["target_entity"], confirmed_occurrence_count=record["confirmed_occurrence_count"], distinct_project_count=record["distinct_project_count"], distinct_assembly_count=record["distinct_assembly_count"], support=record["support"], reliability_descriptor=record["reliability_descriptor"], dataset_scope=record["dataset_scope"], supporting_usage_ids_json=record["supporting_usage_ids"], limitations_json=record["limitations"]))
        _audit(session, "roller_usage_relationship_snapshot", snapshot_id, "BUILD", created_by, {"content_hash": content_hash})
        return {"snapshot_id": snapshot_id, "content_hash": content_hash, "relationship_count": len(records), "relationships": records}


def search_historical_usage(engine: Engine, mode: str = "DESIGN_HISTORY", design_id: str | None = None, project_id: int | None = None, role: str | None = None, station_id: str | None = None, include_synthetic: bool = False, include_stale: bool = False, min_distinct_projects: int = 0, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    mode = mode.upper()
    with Session(engine) as session:
        if mode == "UNRESOLVED_REVIEW_CASES":
            rows = session.scalars(select(RecognitionEvaluationCase).where(RecognitionEvaluationCase.case_status.in_(["OPEN", "CONFLICTED"])).order_by(RecognitionEvaluationCase.id)).all()
            return {"mode": mode, "total": len(rows), "results": [{"case_id": r.id, "project_id": r.project_id, "occurrence_id": r.occurrence_id, "classification": "UNRESOLVED REVIEW"} for r in rows[offset:offset + limit]]}
        query = select(ConfirmedRollerDesignUsage).order_by(ConfirmedRollerDesignUsage.design_id, ConfirmedRollerDesignUsage.project_id, ConfirmedRollerDesignUsage.occurrence_id)
        if design_id:
            query = query.where(ConfirmedRollerDesignUsage.design_id == design_id)
        if project_id is not None:
            query = query.where(ConfirmedRollerDesignUsage.project_id == project_id)
        if role:
            query = query.where(ConfirmedRollerDesignUsage.role == role)
        if station_id:
            query = query.where(ConfirmedRollerDesignUsage.station_id == station_id)
        if not include_stale:
            query = query.where(ConfirmedRollerDesignUsage.confirmation_status == "CONFIRMED")
        rows = session.scalars(query).all()
        results = []
        for row in rows:
            dataset = session.get(RecognitionEvaluationDataset, row.source_dataset_id)
            if dataset and dataset.kind == "SYNTHETIC" and not include_synthetic:
                continue
            results.append({"usage_id": row.usage_id, "project_id": row.project_id, "occurrence_id": row.occurrence_id, "design_id": row.design_id, "geometry_revision_id": row.geometry_revision_id, "station_id": row.station_id, "role": row.role, "confirmation_status": row.confirmation_status, "classification": "CONFIRMED HISTORICAL FACT" if row.confirmation_status == "CONFIRMED" else "STALE CONFIRMATION", "physical_asset_id": None, "limitations": ["Design evidence only; no physical asset assignment or tooling recommendation"], "source_handles": row.source_handles_json, "source_dataset_hash": row.source_dataset_hash})
        filtered = [r for r in results if (not min_distinct_projects or len({x["project_id"] for x in results if x["design_id"] == r["design_id"]}) >= min_distinct_projects)]
        return {"mode": mode, "total": len(filtered), "offset": offset, "limit": limit, "results": filtered[offset:offset + limit]}
