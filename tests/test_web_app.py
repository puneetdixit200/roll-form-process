from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.cad_factory import make_flower_dxf


def test_upload_dxf_starts_job_preserves_source_and_exposes_results(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    source = make_flower_dxf(tmp_path / "upload.dxf", station_count=3, labels=True)
    client = TestClient(create_app(workspace=tmp_path / "web"))

    with source.open("rb") as handle:
        response = client.post("/api/projects", files={"file": ("upload.dxf", handle, "application/dxf")})

    assert response.status_code == 202
    payload = response.json()
    assert payload["project_id"]
    assert payload["job_id"]
    project = client.get(f"/api/projects/{payload['project_id']}").json()
    assert project["source"]["sha256"]
    assert Path(project["source"]["stored_path"]).exists()
    assert project["status"] in {"UPLOADED", "CANDIDATE_READY", "FAILED"}
    job = client.get(f"/api/jobs/{payload['job_id']}").json()
    assert [stage["stage"] for stage in job["stages"]][:1] == ["UPLOADED"]

    result = _wait_until_ready(client, payload["project_id"], payload["job_id"])
    assert result["status"] == "CANDIDATE_READY"
    assert result["summary"]["project_path"]
    assert result["summary"]["candidate_extraction"] is True

    report = client.get(f"/api/projects/{payload['project_id']}/report-data")
    assert report.status_code == 200
    assert "sequences" in report.json()


def test_rejects_invalid_upload_type(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    client = TestClient(create_app(workspace=tmp_path / "web"))
    response = client.post("/api/projects", files={"file": ("bad.txt", b"not cad", "text/plain")})

    assert response.status_code == 400
    assert "DWG or DXF" in response.json()["detail"]


def test_dwg_upload_is_accepted_and_preserved_without_running_job(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    client = TestClient(create_app(workspace=tmp_path / "web", auto_run_jobs=False))
    response = client.post("/api/projects", files={"file": ("flower.dwg", b"AC1027 fake dwg payload", "application/acad")})

    assert response.status_code == 202
    project = client.get(f"/api/projects/{response.json()['project_id']}").json()
    assert project["source"]["stored_path"].endswith("flower.dwg")
    assert Path(project["source"]["stored_path"]).read_bytes() == b"AC1027 fake dwg payload"


def test_artifact_download_and_export_manifest(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    source = make_flower_dxf(tmp_path / "download.dxf", station_count=2, labels=True)
    client = TestClient(create_app(workspace=tmp_path / "web"))
    with source.open("rb") as handle:
        upload = client.post("/api/projects", files={"file": ("download.dxf", handle, "application/dxf")}).json()
    _wait_until_ready(client, upload["project_id"], upload["job_id"])

    manifest = client.get(f"/api/projects/{upload['project_id']}/artifacts").json()
    assert "project.json" in manifest["files"]
    artifact = client.get(f"/api/projects/{upload['project_id']}/artifacts/project.json")
    assert artifact.status_code == 200
    assert artifact.json()["drawing_id"] == "download"
    package = client.get(f"/api/projects/{upload['project_id']}/exports/package.zip")
    assert package.status_code == 200
    assert package.content.startswith(b"PK")


def test_review_decisions_create_new_revision_without_confirming_unrelated_items(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    source = make_flower_dxf(tmp_path / "review.dxf", station_count=1, labels=True)
    client = TestClient(create_app(workspace=tmp_path / "web"))
    with source.open("rb") as handle:
        upload = client.post("/api/projects", files={"file": ("review.dxf", handle, "application/dxf")}).json()
    _wait_until_ready(client, upload["project_id"], upload["job_id"])
    decisions = {
        "schema_version": 1,
        "drawing_units": {"detected_unit": "Unitless", "engineer_confirmed_unit": "mm", "conversion_factor_to_mm": 1.0, "confirmed_by": "test"},
        "composite_passes": [],
    }

    response = client.post(f"/api/projects/{upload['project_id']}/review-decisions", json=decisions)

    assert response.status_code == 200
    project = client.get(f"/api/projects/{upload['project_id']}").json()
    assert project["revision"] == 2
    report = client.get(f"/api/projects/{upload['project_id']}/report-data").json()
    assert report.get("manual_review_decisions", {}).get("drawing_units", {}).get("engineer_confirmed_unit") == "mm"
    assert report["project"]["confirmed_transitions"] == 0


def test_pending_job_can_be_recovered_after_app_restart(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    source = make_flower_dxf(tmp_path / "restart.dxf", station_count=1, labels=True)
    workspace = tmp_path / "web"
    first = TestClient(create_app(workspace=workspace, auto_run_jobs=False))
    with source.open("rb") as handle:
        upload = first.post("/api/projects", files={"file": ("restart.dxf", handle, "application/dxf")}).json()

    second = TestClient(create_app(workspace=workspace, auto_run_jobs=False))
    job = second.get(f"/api/jobs/{upload['job_id']}").json()

    assert job["status"] == "PENDING"
    assert job["project_id"] == upload["project_id"]


def _wait_until_ready(client: TestClient, project_id: str, job_id: str) -> dict:
    for _ in range(120):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"CANDIDATE_READY", "FAILED"}:
            break
    project = client.get(f"/api/projects/{project_id}").json()
    if job["status"] == "FAILED":
        raise AssertionError(json.dumps(job, indent=2))
    return project
