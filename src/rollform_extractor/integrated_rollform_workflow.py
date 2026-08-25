"""Durable orchestration metadata for a single CAD upload used two ways.

The visual target can become ready before the general project extraction. The
record intentionally contains IDs and hashes, never a filesystem path.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


def _path(root: Path, workflow_id: str) -> Path:
    return root / "rollform_workflows" / workflow_id / "workflow.json"


def create_workflow(root: Path, *, source_sha256: str, visual_import_id: str, project_id: str, analysis_job_id: str, profile_count: int) -> dict[str, Any]:
    workflow_id = "rwf-" + uuid4().hex[:16]
    now = datetime.now(UTC).isoformat()
    payload = {"workflow_id": workflow_id, "source_sha256": source_sha256, "visual_import_id": visual_import_id, "project_id": project_id, "analysis_job_id": analysis_job_id, "selected_profile_id": None, "selected_target_id": None, "visual_status": "PROFILES_READY" if profile_count else "NO_PROFILES", "analysis_status": "PENDING", "roller_recognition_status": "NOT_STARTED", "profile_count": profile_count, "warnings": [], "private_paths_redacted": True, "created_at": now, "updated_at": now}
    path = _path(root, workflow_id); path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def get_workflow(root: Path, workflow_id: str) -> dict[str, Any] | None:
    path = _path(root, workflow_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def select_profile(root: Path, workflow_id: str, profile_id: str, target_id: str) -> dict[str, Any] | None:
    payload = get_workflow(root, workflow_id)
    if payload is None:
        return None
    payload.update({"selected_profile_id": profile_id, "selected_target_id": target_id, "visual_status": "TARGET_READY", "updated_at": datetime.now(UTC).isoformat()})
    _path(root, workflow_id).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
