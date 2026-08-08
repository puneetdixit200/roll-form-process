from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from rollform_extractor.web.backend.jobs.store import JobStore
from rollform_extractor.web.backend.services.analysis import AnalysisService
from rollform_extractor.database import (
    RollerAsset, RollerAuditEvent, RollerCompatibility, RollerConditionHistory,
    RollerDesign, RollerFileAsset, RollerGeometryRevision, RollerImportBatch,
    RollerImportRow, RollerLocation, RollerReviewDecision, RollerRegrindHistory,
    Project, RollerRecognitionCandidate, RollerRecognitionInput, RollerRecognitionReview, RollerRecognitionRun,
    RecognitionEvaluationDataset, RecognitionEvaluationCase, RecognitionLabelAssertion, RecognitionAdjudication,
    RecognitionThresholdProfile, ConfirmedRollerDesignUsage, RollerUsageRelationship, create_project_database,
)
from rollform_extractor.roller_inventory import export_inventory, import_inventory, inventory_stats, validate_inventory
from rollform_extractor.roller_recognition import recognize_project, review_candidate
from rollform_extractor.validated_usage import (
    add_evaluation_case, adjudicate_case, calculate_review_agreement, create_evaluation_dataset,
    lock_dataset_version, promote_confirmed_usage, search_historical_usage, submit_label_assertion,
    validate_dataset,
)
from rollform_extractor.visual_flower_service import create_candidate_review, create_target as create_visual_target, export_candidate as export_visual_candidate, get_candidate as get_visual_candidate, get_run as get_visual_run, get_target as get_visual_target, generate_for_target as generate_visual_for_target, historical_pass_preview, list_candidate_reviews, list_targets as list_visual_targets
from rollform_extractor.visual_profile_schema import VisualProfileError
from rollform_extractor.clrsg_service import list_models, model_status
from rollform_extractor.private_clrsg_readiness import doctor_private_model
from rollform_extractor.visual_flower_import import create_import as create_visual_import, get_import as get_visual_import, list_profiles as list_visual_import_profiles, selected_profile as selected_visual_import_profile
from sqlalchemy import select
from sqlalchemy.orm import Session


def create_app(workspace: Path | None = None, auto_run_jobs: bool = True) -> FastAPI:
    root = workspace or Path(os.environ.get("ROLLFORM_WEB_WORKSPACE", Path.cwd() / "web-workspace"))
    store = JobStore(root)
    service = AnalysisService(store)
    app = FastAPI(title="Rollform Extractor Offline API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.service = service
    inventory_database = root / "roller_inventory.sqlite"
    visual_database = root / "visual_flower.sqlite"

    def inventory_engine():
        return create_project_database(inventory_database)

    def visual_engine():
        return create_project_database(visual_database)

    def recognition_engine(project_id: str):
        try:
            project_path = store.project_output_path(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project database not found") from exc
        if project_path is None or not (project_path / "project.sqlite").is_file():
            raise HTTPException(status_code=404, detail="Project database not found")
        return create_project_database(project_path / "project.sqlite")

    def recognition_project_row(project_id: str, engine):
        with Session(engine) as session:
            row = session.scalar(select(Project).where(Project.drawing_id == project_id))
            if row is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return row.id

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "offline"}

    @app.get("/api/visual-flower/dataset-status")
    def visual_dataset_status() -> dict[str, Any]:
        import os
        configured = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
        if not configured:
            return {"available": False, "dataset_hash": "UNCONFIGURED", "flower_count": 0, "pass_count": 0, "warning": "Configure the local prototype dataset to enable historical matching."}
        path = Path(configured).expanduser().resolve()
        if not path.is_file() or path.name != "dataset.json":
            raise HTTPException(status_code=404, detail={"code": "DATASET_UNAVAILABLE", "message": "configured prototype dataset is unavailable"})
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"available": True, "dataset_hash": payload.get("dataset_hash"), "flower_count": len(payload.get("flowers", [])), "pass_count": sum(len(item.get("passes", [])) for item in payload.get("flowers", [])), "source_classification": payload.get("source_classification"), "private_paths_redacted": True}

    @app.get("/api/visual-flower/historical-preview/{source_flower_id}/{source_pass_id}.png")
    def visual_historical_preview(source_flower_id: str, source_pass_id: str) -> Response:
        preview = historical_pass_preview(source_flower_id, source_pass_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="historical pass preview not found")
        return Response(content=preview, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/visual-flower/model/status")
    def visual_model_status() -> dict[str, Any]:
        return model_status(visual_engine())

    @app.get("/api/visual-flower/model/doctor")
    def visual_model_doctor() -> dict[str, Any]:
        configured = os.environ.get("ROLLFORM_ACTIVE_CLRSG_MODEL")
        if not configured:
            return {"status": "NOT_READY", "checks": {"environment_configured": False}, "model": {}, "deterministic_fallback": True, "private_paths_redacted": True, "production_approval": "NOT_APPROVED"}
        return doctor_private_model(Path(configured))

    @app.get("/api/visual-flower/model/models")
    def visual_model_list() -> list[dict[str, Any]]:
        return list_models(visual_engine())

    @app.get("/api/visual-flower/model/models/{model_id}")
    def visual_model_detail(model_id: str) -> dict[str, Any]:
        item = next((row for row in list_models(visual_engine()) if row["model_id"] == model_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="CLRSG model not found")
        return item

    @app.post("/api/visual-flower/import")
    async def visual_import(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            return create_visual_import(root, file.filename or "profile.dxf", await file.read())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "INVALID_CAD_FILE", "message": str(exc)}) from exc

    @app.get("/api/visual-flower/imports/{import_id}")
    def visual_import_status(import_id: str) -> dict[str, Any]:
        result = get_visual_import(root, import_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual import not found")
        return {key: value for key, value in result.items() if key != "profiles"} | {"profile_count": len(result.get("profiles", []))}

    @app.get("/api/visual-flower/imports/{import_id}/profiles")
    def visual_import_profiles(import_id: str) -> list[dict[str, Any]]:
        result = list_visual_import_profiles(root, import_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual import not found")
        return result

    @app.post("/api/visual-flower/imports/{import_id}/profiles/{profile_id}/use")
    def visual_use_import_profile(import_id: str, profile_id: str) -> dict[str, Any]:
        profile = selected_visual_import_profile(root, import_id, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="visual import profile not found")
        try:
            return create_visual_target(visual_engine(), {"profile": profile})
        except (ValueError, VisualProfileError) as exc:
            raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "INVALID_PROFILE"), "message": str(exc)}) from exc

    @app.post("/api/visual-flower/targets")
    def visual_create_target(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_visual_target(visual_engine(), payload)
        except VisualProfileError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_PROFILE", "message": str(exc)}) from exc

    @app.get("/api/visual-flower/targets")
    def visual_list_targets() -> list[dict[str, Any]]:
        return list_visual_targets(visual_engine())

    @app.get("/api/visual-flower/targets/{target_id}")
    def visual_get_target(target_id: str) -> dict[str, Any]:
        result = get_visual_target(visual_engine(), target_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual target not found")
        return result

    @app.post("/api/visual-flower/targets/{target_id}/generate")
    def visual_generate(target_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return generate_visual_for_target(visual_engine(), target_id, payload or {})
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, VisualProfileError) as exc:
            raise HTTPException(status_code=422, detail={"code": getattr(exc, "code", "GENERATION_FAILED"), "message": str(exc)}) from exc

    @app.get("/api/visual-flower/runs/{run_id}")
    def visual_get_run(run_id: str) -> dict[str, Any]:
        result = get_visual_run(visual_engine(), run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual run not found")
        return result

    @app.get("/api/visual-flower/candidates/{candidate_id}")
    def visual_get_candidate(candidate_id: str) -> dict[str, Any]:
        result = get_visual_candidate(visual_engine(), candidate_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        return result

    @app.get("/api/visual-flower/candidates/{candidate_id}/export/{artifact}")
    def visual_export_candidate(candidate_id: str, artifact: str):
        directory = export_visual_candidate(visual_engine(), candidate_id, root)
        if directory is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        names = {"json": "visual_run.json", "csv": "passes.csv", "zip": "visual_flower_export.zip"}
        if artifact in {"dxf", "svg", "png", "html"}:
            suffix = {"dxf": "combined.dxf", "svg": "combined.svg", "png": "contact-sheet.png", "html": "report.html"}[artifact]
            path = directory / candidate_id / suffix
        else:
            path = directory / names.get(artifact, "")
        if not path.is_file() or directory not in path.resolve().parents:
            raise HTTPException(status_code=404, detail="visual export artifact not found")
        return FileResponse(path, filename=path.name)

    @app.get("/api/visual-flower/candidates/{candidate_id}/passes")
    def visual_get_candidate_passes(candidate_id: str) -> dict[str, Any]:
        result = get_visual_candidate(visual_engine(), candidate_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        return {"candidate_id": candidate_id, "passes": result.get("passes", []), "provenance": result.get("provenance", {})}

    @app.get("/api/visual-flower/candidates/{candidate_id}/matches")
    def visual_get_candidate_matches(candidate_id: str) -> dict[str, Any]:
        result = get_visual_candidate(visual_engine(), candidate_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        return {"candidate_id": candidate_id, "matches": [item.get("historical_match", {}) for item in result.get("passes", [])]}

    @app.get("/api/visual-flower/candidates/{candidate_id}/export.json")
    def visual_export_candidate_json(candidate_id: str) -> dict[str, Any]:
        result = get_visual_candidate(visual_engine(), candidate_id)
        if result is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        return {"schema_version": 1, "export_type": "VISUAL_FLOWER_CANDIDATE", "candidate": result, "source_cad_included": False}

    @app.post("/api/visual-flower/candidates/{candidate_id}/review")
    def visual_candidate_review(candidate_id: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return create_candidate_review(visual_engine(), candidate_id, str(body.get("decision") or ""), str(body.get("reviewer") or ""), reason_codes=list(body.get("reason_codes") or []), notes=str(body.get("notes") or ""))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": str(exc), "message": str(exc)}) from exc

    @app.get("/api/visual-flower/candidates/{candidate_id}/reviews")
    def visual_candidate_reviews(candidate_id: str) -> list[dict[str, Any]]:
        if get_visual_candidate(visual_engine(), candidate_id) is None:
            raise HTTPException(status_code=404, detail="visual candidate not found")
        return list_candidate_reviews(visual_engine(), candidate_id)

    @app.get("/api/visual-flower/reviews/export.json")
    def visual_reviews_export() -> dict[str, Any]:
        return {"schema_version": 1, "export_type": "VISUAL_FLOWER_CANDIDATE_REVIEWS", "reviews": list_candidate_reviews(visual_engine()), "private_source_included": False, "safety_boundary": "Visual geometry prototype only; not manufacturing approval."}

    @app.get("/api/flower-prototype/status")
    def flower_prototype_status() -> dict[str, Any]:
        """Return only redacted prototype metadata when a local dataset is configured."""
        configured = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
        if not configured:
            return {"available": False, "reason": "no local prototype dataset configured"}
        dataset_path = Path(configured).expanduser().resolve()
        if not dataset_path.is_file() or dataset_path.name != "dataset.json":
            raise HTTPException(status_code=404, detail="prototype dataset not found")
        try:
            payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail="prototype dataset is invalid") from exc
        return {"available": True, "dataset_id": payload.get("dataset_id"), "dataset_hash": payload.get("dataset_hash"), "source_classification": payload.get("source_classification"), "flowers": [{"flower_id": item.get("flower_id"), "station_count": len(item.get("passes", [])), "topology": item.get("topology"), "quality_flags": item.get("quality_flags", [])} for item in payload.get("flowers", [])], "roller_evidence_count": len(payload.get("roller_evidence", [])), "private_paths_redacted": True}

    @app.get("/api/inventory/stats")
    def inventory_statistics() -> dict[str, int]:
        return inventory_stats(inventory_engine())

    @app.get("/api/inventory/designs")
    def inventory_designs() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"design_id": row.design_id, "name": row.name, "design_type": row.design_type, "manufacturer": row.manufacturer, "status": row.status, "verified": bool(row.verified)} for row in session.scalars(select(RollerDesign).order_by(RollerDesign.design_id))]

    @app.get("/api/inventory/assets")
    def inventory_assets() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"asset_id": row.asset_id, "design_id": row.design_id, "serial_number": row.serial_number, "condition": row.condition, "location_id": row.location_id, "verified": bool(row.verified)} for row in session.scalars(select(RollerAsset).order_by(RollerAsset.asset_id))]

    @app.get("/api/inventory/batches")
    def inventory_batches() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "source_name": row.source_name, "source_sha256": row.source_sha256, "status": row.status, "row_count": row.row_count, "accepted_count": row.accepted_count, "review_count": row.review_count, "rejected_count": row.rejected_count} for row in session.scalars(select(RollerImportBatch).order_by(RollerImportBatch.id.desc()))]

    @app.get("/api/inventory/geometry-revisions")
    def inventory_geometry_revisions() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "revision_id": row.revision_id, "design_id": row.design_id, "asset_id": row.asset_id, "dimensions": row.dimensions_json, "unit_status": row.unit_status, "verification_status": row.verification_status, "physical_fingerprint": row.physical_fingerprint, "shape_fingerprint": row.shape_fingerprint} for row in session.scalars(select(RollerGeometryRevision).order_by(RollerGeometryRevision.id))]

    @app.get("/api/inventory/locations")
    def inventory_locations() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"location_id": row.location_id, "name": row.name, "location_type": row.location_type, "parent_location_id": row.parent_location_id} for row in session.scalars(select(RollerLocation).order_by(RollerLocation.location_id))]

    @app.get("/api/inventory/conditions")
    def inventory_conditions() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "asset_id": row.asset_id, "condition": row.condition, "observed_at": row.observed_at, "source": row.source, "notes": row.notes} for row in session.scalars(select(RollerConditionHistory).order_by(RollerConditionHistory.id))]

    @app.get("/api/inventory/regrinds")
    def inventory_regrinds() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "asset_id": row.asset_id, "performed_at": row.performed_at, "amount_removed": row.amount_removed, "amount_unit": row.amount_unit, "resulting_revision_id": row.resulting_revision_id, "source": row.source, "notes": row.notes} for row in session.scalars(select(RollerRegrindHistory).order_by(RollerRegrindHistory.id))]

    @app.get("/api/inventory/compatibility")
    def inventory_compatibility() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "design_id": row.design_id, "compatible_design_id": row.compatible_design_id, "status": row.status, "evidence": row.evidence_json, "verified": bool(row.verified)} for row in session.scalars(select(RollerCompatibility).order_by(RollerCompatibility.id))]

    @app.get("/api/inventory/files")
    def inventory_files() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "sha256": row.sha256, "file_name": row.file_name, "relative_path": row.relative_path, "content_type": row.content_type, "design_id": row.design_id, "asset_id": row.asset_id, "revision_id": row.revision_id} for row in session.scalars(select(RollerFileAsset).order_by(RollerFileAsset.id))]

    @app.get("/api/inventory/audit-events")
    def inventory_audit_events() -> list[dict[str, Any]]:
        with Session(inventory_engine()) as session:
            return [{"id": row.id, "entity_type": row.entity_type, "entity_key": row.entity_key, "action": row.action, "actor": row.actor, "source": row.source} for row in session.scalars(select(RollerAuditEvent).order_by(RollerAuditEvent.id))]

    async def _save_inventory_upload(file: UploadFile) -> Path:
        name = Path(file.filename or "inventory.csv").name
        if Path(name).suffix.lower() not in {".csv", ".xlsx", ".xlsm"}:
            raise HTTPException(status_code=400, detail="Inventory upload must be CSV or XLSX")
        target = root / "inventory_imports" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(await file.read())
        return target

    @app.post("/api/inventory/validate")
    async def validate_inventory_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        return validate_inventory(await _save_inventory_upload(file), inventory_engine()).to_dict()

    @app.post("/api/inventory/import")
    async def import_inventory_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        return import_inventory(await _save_inventory_upload(file), inventory_engine()).to_dict()

    @app.get("/api/inventory/export")
    def inventory_export():
        from fastapi.responses import FileResponse as _FileResponse
        path = export_inventory(inventory_engine(), root / "inventory_exports")
        return _FileResponse(path, filename="roller_inventory.csv", media_type="text/csv")

    @app.post("/api/inventory/review-decisions")
    def inventory_review_decision(decision: dict[str, Any]) -> dict[str, Any]:
        batch_id, row_id = decision.get("batch_id"), decision.get("row_id")
        if not isinstance(batch_id, int) or not isinstance(row_id, int) or decision.get("decision") not in {"ACCEPT", "REJECT"}:
            raise HTTPException(status_code=400, detail="batch_id, row_id, and ACCEPT/REJECT decision are required")
        with Session(inventory_engine()) as session, session.begin():
            row = session.get(RollerImportRow, row_id)
            if row is None or row.batch_id != batch_id:
                raise HTTPException(status_code=404, detail="Inventory review row not found")
            row.status = "ACCEPTED" if decision["decision"] == "ACCEPT" else "REJECTED"
            session.add(RollerReviewDecision(batch_id=batch_id, row_id=row_id, decision=decision["decision"], reviewer=str(decision.get("reviewer") or "engineer"), notes=decision.get("notes")))
            return {"row_id": row.id, "status": row.status}

    @app.post("/api/projects/{project_id}/roller-recognition/runs")
    def create_recognition_run(project_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        options = options or {}
        run_id, results = recognize_project(engine, numeric_id, units_status=str(options.get("units_status") or "UNKNOWN"), configuration_hash=str(options.get("configuration_hash") or ""))
        return {"run_id": run_id, "project_id": project_id, "occurrence_count": len(results), "candidate_count": sum(len(item.candidates) for item in results)}

    @app.get("/api/projects/{project_id}/roller-recognition/runs")
    def recognition_runs(project_id: str) -> list[dict[str, Any]]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            return [{"id": row.id, "run_key": row.run_key, "status": row.status, "algorithm_version": row.algorithm_version, "configuration_hash": row.configuration_hash, "occurrence_count": row.occurrence_count, "candidate_count": row.candidate_count} for row in session.scalars(select(RollerRecognitionRun).where(RollerRecognitionRun.project_id == numeric_id).order_by(RollerRecognitionRun.id.desc()))]

    @app.get("/api/projects/{project_id}/roller-recognition/runs/{run_id}")
    def recognition_run(project_id: str, run_id: int) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            row = session.get(RollerRecognitionRun, run_id)
            if row is None or row.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Recognition run not found")
            return {"id": row.id, "project_id": project_id, "status": row.status, "algorithm_version": row.algorithm_version, "feature_schema_version": row.feature_schema_version, "configuration_hash": row.configuration_hash, "inventory_snapshot_hash": row.inventory_snapshot_hash, "occurrence_count": row.occurrence_count, "candidate_count": row.candidate_count, "diagnostics": row.diagnostics_json}

    @app.get("/api/projects/{project_id}/roller-recognition/runs/{run_id}/candidates")
    def recognition_candidates(project_id: str, run_id: int) -> list[dict[str, Any]]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            run = session.get(RollerRecognitionRun, run_id)
            if run is None or run.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Recognition run not found")
            rows = session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.run_id == run_id).order_by(RollerRecognitionCandidate.input_id, RollerRecognitionCandidate.rank)).all()
            return [{"id": row.id, "occurrence_id": session.get(RollerRecognitionInput, row.input_id).occurrence_id, "design_id": row.design_id, "geometry_revision_id": row.geometry_revision_id, "rank": row.rank, "overall_score": row.overall_score, "confidence": row.confidence, "evidence_coverage": row.evidence_coverage, "candidate_status": row.candidate_status, "components": row.component_scores_json, "hard_filters": row.hard_filter_results_json, "explanation": row.explanation_json} for row in rows]

    @app.get("/api/projects/{project_id}/roller-recognition/occurrences/{occurrence_id}")
    def recognition_occurrence(project_id: str, occurrence_id: str) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            run = session.scalar(select(RollerRecognitionRun).where(RollerRecognitionRun.project_id == numeric_id).order_by(RollerRecognitionRun.id.desc()))
            if run is None:
                raise HTTPException(status_code=404, detail="Recognition run not found")
            input_row = session.scalar(select(RollerRecognitionInput).where(RollerRecognitionInput.run_id == run.id, RollerRecognitionInput.occurrence_id == occurrence_id))
            if input_row is None:
                raise HTTPException(status_code=404, detail="Recognition occurrence not found")
            return {"input": input_row.feature_json, "candidates": [{"id": row.id, "design_id": row.design_id, "geometry_revision_id": row.geometry_revision_id, "rank": row.rank, "overall_score": row.overall_score, "confidence": row.confidence, "candidate_status": row.candidate_status, "components": row.component_scores_json, "hard_filters": row.hard_filter_results_json, "explanation": row.explanation_json} for row in session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.input_id == input_row.id).order_by(RollerRecognitionCandidate.rank))]}

    @app.post("/api/projects/{project_id}/roller-recognition/candidates/{candidate_id}/review")
    def review_recognition_candidate(project_id: str, candidate_id: int, decision: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            candidate = session.get(RollerRecognitionCandidate, candidate_id)
            run = session.get(RollerRecognitionRun, candidate.run_id) if candidate else None
            if candidate is None or run is None or run.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Recognition candidate not found")
        try:
            review_id = review_candidate(engine, candidate_id, str(decision.get("decision") or ""), str(decision.get("reviewer") or "engineer"), selected_design_id=decision.get("selected_design_id"), selected_revision_id=decision.get("selected_revision_id"), reason_code=decision.get("reason_code"), notes=decision.get("notes"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"review_id": review_id, "candidate_id": candidate_id}

    @app.get("/api/projects/{project_id}/recognition-evaluation/datasets")
    def evaluation_datasets(project_id: str) -> list[dict[str, Any]]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            rows = session.scalars(select(RecognitionEvaluationDataset).order_by(RecognitionEvaluationDataset.id.desc())).all()
            return [{"dataset_id": row.dataset_id, "name": row.name, "kind": row.kind, "version": row.version, "status": row.status, "case_count": row.case_count, "content_hash": row.content_hash} for row in rows]

    @app.post("/api/projects/{project_id}/recognition-evaluation/datasets")
    def evaluation_dataset_create(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        recognition_project_row(project_id, engine)
        try:
            return create_evaluation_dataset(engine, str(body.get("name") or ""), str(body.get("kind") or "ENGINEER_LABELLED"), str(body.get("created_by") or ""), str(body.get("description") or ""), str(body.get("inventory_snapshot_hash") or ""))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/recognition-evaluation/datasets/{dataset_id}")
    def evaluation_dataset(project_id: str, dataset_id: str) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        with Session(engine) as session:
            row = session.scalar(select(RecognitionEvaluationDataset).where(RecognitionEvaluationDataset.dataset_id == dataset_id))
            if row is None:
                raise HTTPException(status_code=404, detail="Evaluation dataset not found")
            validation = validate_dataset(engine, dataset_id)
            return {"dataset_id": row.dataset_id, "name": row.name, "kind": row.kind, "version": row.version, "status": row.status, "content_hash": row.content_hash, "validation": validation}

    @app.post("/api/projects/{project_id}/recognition-evaluation/datasets/{dataset_id}/cases")
    def evaluation_case_create(project_id: str, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        try:
            if int(body.get("project_id", numeric_id)) != numeric_id:
                raise HTTPException(status_code=404, detail="Project ownership mismatch")
            return add_evaluation_case(engine, dataset_id, numeric_id, str(body.get("occurrence_id") or ""), body.get("recognition_input_id"), str(body.get("split") or "CALIBRATION"))
        except HTTPException:
            raise
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/recognition-evaluation/cases/{case_id}/labels")
    def evaluation_label(project_id: str, case_id: int, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            case = session.get(RecognitionEvaluationCase, case_id)
            if case is None or case.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Evaluation case not found")
        try:
            result = submit_label_assertion(engine, case_id, str(body.get("reviewer") or ""), str(body.get("outcome") or ""), str(body.get("reason_code") or ""), body.get("expected_design_id"), body.get("expected_revision_id"), body.get("confidence"), body.get("evidence"), body.get("notes"))
            result["agreement"] = calculate_review_agreement(engine, case_id).to_dict()
            return result
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/recognition-evaluation/cases/{case_id}/adjudications")
    def evaluation_adjudicate(project_id: str, case_id: int, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            case = session.get(RecognitionEvaluationCase, case_id)
            if case is None or case.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Evaluation case not found")
        try:
            return adjudicate_case(engine, case_id, str(body.get("adjudicator") or ""), str(body.get("final_outcome") or ""), str(body.get("reason_code") or ""), body.get("selected_design_id"), body.get("selected_revision_id"), body.get("evidence"), body.get("notes"))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/recognition-evaluation/datasets/{dataset_id}/lock")
    def evaluation_dataset_lock(project_id: str, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        recognition_project_row(project_id, engine)
        try:
            return lock_dataset_version(engine, dataset_id, str(body.get("reviewer") or ""))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/confirmed-roller-usages/promote")
    def usage_promote(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        case_id = int(body.get("case_id") or 0)
        with Session(engine) as session:
            case = session.get(RecognitionEvaluationCase, case_id)
            if case is None or case.project_id != numeric_id:
                raise HTTPException(status_code=404, detail="Evaluation case not found")
        try:
            return promote_confirmed_usage(engine, case_id, str(body.get("reviewer") or ""), str(body.get("notes") or ""))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/confirmed-roller-usages")
    def project_usages(project_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        engine = recognition_engine(project_id)
        numeric_id = recognition_project_row(project_id, engine)
        with Session(engine) as session:
            rows = session.scalars(select(ConfirmedRollerDesignUsage).where(ConfirmedRollerDesignUsage.project_id == numeric_id).order_by(ConfirmedRollerDesignUsage.id).offset(offset).limit(min(limit, 500))).all()
            return {"results": [{"usage_id": row.usage_id, "occurrence_id": row.occurrence_id, "design_id": row.design_id, "geometry_revision_id": row.geometry_revision_id, "station_id": row.station_id, "role": row.role, "confirmation_status": row.confirmation_status, "physical_asset_id": None} for row in rows], "offset": offset, "limit": limit}

    @app.get("/api/historical-roller-search")
    def historical_search(database: str | None = None, design_id: str | None = None, role: str | None = None, mode: str = "DESIGN_HISTORY", include_synthetic: bool = False, include_stale: bool = False, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        target = Path(database) if database else inventory_database
        if database is not None and root.resolve() not in target.resolve().parents and target.resolve() != root.resolve():
            raise HTTPException(status_code=400, detail="Database path is outside the offline workspace")
        try:
            return search_historical_usage(create_project_database(target), mode, design_id, role=role, include_synthetic=include_synthetic, include_stale=include_stale, limit=min(limit, 500), offset=max(0, offset))
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects", status_code=202)
    async def upload_project(background: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, str]:
        content = await file.read()
        try:
            record = store.create_upload(file.filename or "drawing.dxf", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if auto_run_jobs:
            background.add_task(service.run_job, record.project_id, record.job_id)
        return {"project_id": record.project_id, "job_id": record.job_id}

    @app.get("/api/projects/{project_id}")
    def project(project_id: str) -> dict[str, Any]:
        try:
            return store.read_project(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        try:
            return store.read_job(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        async def stream():
            last = None
            for _ in range(120):
                try:
                    data = store.read_job(job_id)
                except FileNotFoundError:
                    yield "event: error\ndata: Job not found\n\n"
                    return
                text = json.dumps(data)
                if text != last:
                    yield f"event: progress\ndata: {text}\n\n"
                    last = text
                if data.get("status") in {"CANDIDATE_READY", "FAILED"}:
                    return
                await asyncio.sleep(0.5)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/projects/{project_id}/report-data")
    def report_data(project_id: str) -> dict[str, Any]:
        project_path = store.project_output_path(project_id)
        if project_path is None:
            return {"project": {}, "sequences": [], "composite_flowers": [], "warnings": []}
        path = project_path / "report_data.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Report data not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/projects/{project_id}/artifacts")
    def artifacts(project_id: str) -> dict[str, Any]:
        project_path = store.project_output_path(project_id)
        if project_path is None:
            raise HTTPException(status_code=404, detail="Artifacts not ready")
        manifest = project_path / "manifest.json"
        if not manifest.exists():
            raise HTTPException(status_code=404, detail="Manifest not found")
        return json.loads(manifest.read_text(encoding="utf-8"))

    @app.get("/api/projects/{project_id}/flowers/{flower_id}/passes/{pass_id}/features")
    def pass_features(project_id: str, flower_id: str, pass_id: str) -> dict[str, Any]:
        project_path = store.project_output_path(project_id)
        if project_path is None:
            raise HTTPException(status_code=404, detail="Artifacts not ready")
        target = project_path / "composite_flowers" / flower_id / "passes" / pass_id / "pass_features.json"
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Pass features not found")
        return json.loads(target.read_text(encoding="utf-8"))

    @app.get("/api/projects/{project_id}/artifacts/{artifact_path:path}")
    def artifact(project_id: str, artifact_path: str):
        project_path = store.project_output_path(project_id)
        if project_path is None:
            raise HTTPException(status_code=404, detail="Artifacts not ready")
        requested = (project_path / artifact_path).resolve()
        if project_path.resolve() not in requested.parents and requested != project_path.resolve():
            raise HTTPException(status_code=400, detail="Invalid artifact path")
        if not requested.exists() or not requested.is_file():
            raise HTTPException(status_code=404, detail="Artifact not found")
        return FileResponse(requested)

    @app.get("/api/projects/{project_id}/exports/package.zip")
    def export_package(project_id: str):
        project_path = store.project_output_path(project_id)
        if project_path is None:
            raise HTTPException(status_code=404, detail="Artifacts not ready")
        package = store.project_dir(project_id) / "exports" / "engineering_package.zip"
        package.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(package, "w", ZIP_DEFLATED) as archive:
            for path in project_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(project_path))
        return FileResponse(package, filename="engineering_package.zip", media_type="application/zip")

    @app.post("/api/projects/{project_id}/review-decisions")
    def review_decisions(project_id: str, decisions: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.apply_review(project_id, decisions)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/resume", status_code=202)
    def resume(project_id: str, background: BackgroundTasks) -> dict[str, str]:
        try:
            store.read_project(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc
        job_id = service.create_resume_job(project_id)
        if auto_run_jobs:
            background.add_task(service.run_job, project_id, job_id)
        return {"project_id": project_id, "job_id": job_id}

    return app


app = create_app()
