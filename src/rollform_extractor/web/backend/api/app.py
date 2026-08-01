from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from rollform_extractor.web.backend.jobs.store import JobStore
from rollform_extractor.web.backend.services.analysis import AnalysisService
from rollform_extractor.database import (
    RollerAsset, RollerAuditEvent, RollerCompatibility, RollerConditionHistory,
    RollerDesign, RollerFileAsset, RollerGeometryRevision, RollerImportBatch,
    RollerImportRow, RollerLocation, RollerReviewDecision, RollerRegrindHistory,
    create_project_database,
)
from rollform_extractor.roller_inventory import export_inventory, import_inventory, inventory_stats, validate_inventory
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

    def inventory_engine():
        return create_project_database(inventory_database)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "offline"}

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
