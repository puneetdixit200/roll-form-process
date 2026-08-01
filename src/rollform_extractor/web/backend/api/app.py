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

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "offline"}

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

    @app.get("/api/projects/{project_id}/passes/{pass_id}/features")
    def pass_features(project_id: str, pass_id: str) -> dict[str, Any]:
        project_path = store.project_output_path(project_id)
        if project_path is None:
            raise HTTPException(status_code=404, detail="Artifacts not ready")
        matches = sorted(project_path.glob(f"composite_flowers/*/passes/{pass_id}/pass_features.json"))
        if not matches:
            raise HTTPException(status_code=404, detail="Pass features not found")
        return json.loads(matches[0].read_text(encoding="utf-8"))

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
