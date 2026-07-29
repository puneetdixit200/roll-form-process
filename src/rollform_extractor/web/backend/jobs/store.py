from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


PIPELINE_STAGES = (
    "UPLOADED",
    "CONVERTING",
    "PARSING",
    "DETECTING_FLOWERS",
    "EXTRACTING_PASSES",
    "ANALYSING_GEOMETRY",
    "GENERATING_REPORT",
    "CANDIDATE_READY",
)


@dataclass(frozen=True)
class UploadRecord:
    project_id: str
    job_id: str
    source_path: Path
    original_filename: str
    sha256: str


class JobStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.projects_root = workspace / "projects"
        self.outputs_root = workspace / "analysis"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)

    def create_upload(self, filename: str, content: bytes) -> UploadRecord:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".dwg", ".dxf"}:
            raise ValueError("Upload must be a DWG or DXF file")
        if suffix == ".dxf" and b"SECTION" not in content[:4096] and b"EOF" not in content[-4096:]:
            raise ValueError("DXF content signature was not recognised")
        project_id = self._project_id(Path(filename).stem)
        job_id = uuid4().hex
        project_dir = self.project_dir(project_id)
        source_dir = project_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        stored = source_dir / filename
        stored.write_bytes(content)
        digest = sha256(content).hexdigest()
        record = {
            "project_id": project_id,
            "job_id": job_id,
            "revision": 1,
            "original_filename": filename,
            "source": {"stored_path": str(stored), "sha256": digest},
            "status": "UPLOADED",
            "created_at": _now(),
        }
        self._write_project(project_id, record)
        self._write_job(
            job_id,
            {
                "job_id": job_id,
                "project_id": project_id,
                "status": "PENDING",
                "stages": [_stage("UPLOADED", "complete")],
                "logs": [],
                "warnings": [],
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        return UploadRecord(project_id, job_id, stored, filename, digest)

    def project_dir(self, project_id: str) -> Path:
        return self.projects_root / project_id

    def project_output_root(self, project_id: str) -> Path:
        root = self.outputs_root / project_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def project_output_path(self, project_id: str) -> Path | None:
        project = self.read_project(project_id)
        summary = project.get("summary") or {}
        path = summary.get("project_path")
        return Path(path) if path else None

    def read_project(self, project_id: str) -> dict[str, Any]:
        return json.loads((self.project_dir(project_id) / "project_record.json").read_text(encoding="utf-8"))

    def read_job(self, job_id: str) -> dict[str, Any]:
        for path in self.projects_root.glob("*/jobs/*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("job_id") == job_id:
                return data
        raise FileNotFoundError(job_id)

    def update_project(self, project_id: str, **updates: Any) -> dict[str, Any]:
        project = self.read_project(project_id)
        project.update(updates)
        project["updated_at"] = _now()
        self._write_project(project_id, project)
        return project

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        job = self.read_job(job_id)
        job.update(updates)
        job["updated_at"] = _now()
        self._write_job(job_id, job)
        return job

    def record_stage(self, job_id: str, stage: str, status: str, message: str | None = None) -> None:
        job = self.read_job(job_id)
        rows = [row for row in job.get("stages", []) if row.get("stage") != stage]
        rows.append(_stage(stage, status, message))
        job["stages"] = rows
        job["status"] = stage if status != "failed" else "FAILED"
        if message:
            job.setdefault("logs", []).append({"at": _now(), "stage": stage, "message": message})
        self._write_job(job_id, job)

    def _project_id(self, stem: str) -> str:
        base = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stem).strip("-") or "project"
        candidate = base
        counter = 2
        while self.project_dir(candidate).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    def _write_project(self, project_id: str, data: dict[str, Any]) -> None:
        path = self.project_dir(project_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "jobs").mkdir(exist_ok=True)
        (path / "project_record.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _write_job(self, job_id: str, data: dict[str, Any]) -> None:
        project_id = data["project_id"]
        path = self.project_dir(project_id) / "jobs"
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{job_id}.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _stage(stage: str, status: str, message: str | None = None) -> dict[str, Any]:
    now = _now()
    return {"stage": stage, "status": status, "started_at": now, "ended_at": now, "logs": ([message] if message else []), "warnings": []}


def _now() -> str:
    return datetime.now(UTC).isoformat()
