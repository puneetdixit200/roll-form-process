from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from rollform_extractor.database import Project, create_project_database
from rollform_extractor.web.backend.api.app import create_app


def test_recognition_api_scopes_runs_and_validates_reviews(tmp_path):
    workspace = tmp_path / "web"
    app = create_app(workspace=workspace, auto_run_jobs=False)
    output = workspace / "analysis" / "P1"
    output.mkdir(parents=True)
    app.state.store._write_project("P1", {"project_id": "P1", "summary": {"project_path": str(output)}})
    engine = create_project_database(output / "project.sqlite")
    with Session(engine) as session, session.begin():
        session.add(Project(drawing_id="P1", source_path="synthetic.dxf", source_sha256="a" * 64))
    client = TestClient(app)
    created = client.post("/api/projects/P1/roller-recognition/runs", json={"units_status": "UNKNOWN"})
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert client.get(f"/api/projects/P1/roller-recognition/runs/{run_id}").status_code == 200
    assert client.get(f"/api/projects/P1/roller-recognition/runs/{run_id}/candidates").status_code == 200
    assert client.get(f"/api/projects/P1/roller-recognition/runs/{run_id + 99}").status_code == 404
    assert client.post("/api/projects/P1/roller-recognition/candidates/999/review", json={"decision": "ACCEPT_CANDIDATE"}).status_code == 404


def test_phase18_dataset_api_is_project_scoped(tmp_path):
    workspace = tmp_path / "web"
    app = create_app(workspace=workspace, auto_run_jobs=False)
    output = workspace / "analysis" / "P1"
    output.mkdir(parents=True)
    app.state.store._write_project("P1", {"project_id": "P1", "summary": {"project_path": str(output)}})
    engine = create_project_database(output / "project.sqlite")
    with Session(engine) as session, session.begin():
        session.add(Project(drawing_id="P1", source_path="synthetic.dxf", source_sha256="a" * 64))
    client = TestClient(app)
    created = client.post("/api/projects/P1/recognition-evaluation/datasets", json={"name": "api-fixture", "kind": "SYNTHETIC", "created_by": "tester"})
    assert created.status_code == 200
    dataset_id = created.json()["dataset_id"]
    assert client.get(f"/api/projects/P1/recognition-evaluation/datasets/{dataset_id}").status_code == 200
    assert client.get("/api/projects/UNKNOWN/recognition-evaluation/datasets").status_code == 404
    assert client.get("/api/historical-roller-search?database=../../etc/passwd").status_code == 400
