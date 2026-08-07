from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from rollform_extractor.visual_flower_exports import export_visual_run, verify_visual_export
from rollform_extractor.visual_profile_schema import validate_profile
from rollform_extractor.database import VisualFlowerCandidateRow, VisualFlowerGenerationRunRow, VisualProfileTargetRow, create_project_database
from sqlalchemy.orm import Session
from rollform_extractor.web.backend.api.app import create_app


FIXTURES = Path(__file__).parent / "fixtures" / "visual_flower_golden"


def test_public_golden_manifest_is_safe_and_complete():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["classification"] == "PUBLIC_SYNTHETIC_TEST"
    assert manifest["supported_count"] >= 30
    assert manifest["negative_count"] >= 10
    assert {entry["requested_station_count"] for entry in manifest["fixtures"]} >= {8, 16, 28}
    for entry in manifest["fixtures"]:
        payload = json.loads((FIXTURES / entry["path"]).read_text())
        validate_profile(payload)
        assert payload["metadata"]["source"] == "PUBLIC_SYNTHETIC_TEST"
        assert "/home/pd/" not in json.dumps(payload)
        assert "rollform-private" not in json.dumps(payload)


def test_model_doctor_is_available_without_private_model(tmp_path, monkeypatch):
    monkeypatch.delenv("ROLLFORM_ACTIVE_CLRSG_MODEL", raising=False)
    client = TestClient(create_app(tmp_path / "workspace", auto_run_jobs=False))
    response = client.get("/api/visual-flower/model/doctor")
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_READY"
    assert response.json()["deterministic_fallback"] is True
    assert response.json()["private_paths_redacted"] is True


def test_candidate_review_is_append_only_and_exportable(tmp_path):
    candidate_id = "candidate-public-001"
    output = tmp_path / "export"
    result = {"schema_version": 1, "source_cad_included": False, "candidates": [{"candidate_id": candidate_id, "candidate_style": "DETERMINISTIC", "visual_confidence": {"score": 55.0, "band": "MEDIUM"}, "passes": [{"pass_id": "p1", "order": 1, "progress": 1.0, "profile": {"points": [[0, 0], [1, 0]], "topology": "OPEN_PATH"}, "visual_confidence": {"score": 55.0}, "historical_match": {"best_match": {"source_pass_id": "PUBLIC-P1"}}}], "warnings": ["Visual prototype only"]}]}
    export_visual_run(result, output)
    verification = verify_visual_export(output)
    assert verification["status"] == "PASS"


def test_candidate_review_api_preserves_provenance(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = create_project_database(workspace / "visual_flower.sqlite")
    profile = json.loads((Path(__file__).parent / "fixtures/visual_profiles/open_channel.json").read_text())
    from rollform_extractor.visual_flower_service import create_target
    target = create_target(engine, {"profile": profile})
    with Session(engine) as session:
        target_row = session.query(VisualProfileTargetRow).filter_by(target_id=target["target_id"]).one()
        run = VisualFlowerGenerationRunRow(run_id="run-public-001", target_id=target_row.id, algorithm_version="test", dataset_hash="public", configuration_hash="config", status="READY", result_json={})
        session.add(run); session.flush()
        session.add(VisualFlowerCandidateRow(candidate_id="candidate-api-001", run_id=run.id, candidate_json={"candidate_style": "DETERMINISTIC", "algorithm_version": "test"}, status="READY", visual_confidence=50.0)); session.commit()
    client = TestClient(create_app(workspace, auto_run_jobs=False))
    response = client.post("/api/visual-flower/candidates/candidate-api-001/review", json={"decision": "PREFER_DETERMINISTIC", "reviewer": "public-engineer", "reason_codes": ["SMOOTH_PROGRESSION"], "notes": "stable public fixture"})
    assert response.status_code == 200
    review = response.json()
    assert review["candidate_id"] == "candidate-api-001"
    assert review["target_hash"]
    assert client.get("/api/visual-flower/candidates/candidate-api-001/reviews").json()[0]["decision"] == "PREFER_DETERMINISTIC"
