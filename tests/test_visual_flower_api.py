from __future__ import annotations

import json

from fastapi.testclient import TestClient

from rollform_extractor.web.backend.api.app import create_app


def test_visual_target_create_validate_and_generate(tmp_path, monkeypatch):
    monkeypatch.delenv("ROLLFORM_FLOWER_PROTOTYPE_DATASET", raising=False)
    profile = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures/visual_profiles/open_channel.json").read_text())
    client = TestClient(create_app(tmp_path / "workspace", auto_run_jobs=False))
    created = client.post("/api/visual-flower/targets", json={"profile": profile})
    assert created.status_code == 200
    target_id = created.json()["target_id"]
    assert client.get(f"/api/visual-flower/targets/{target_id}").status_code == 200
    generated = client.post(f"/api/visual-flower/targets/{target_id}/generate", json={"station_mode": "EXACT", "exact_station_count": 16, "candidate_limit": 1})
    assert generated.status_code == 200
    assert generated.json()["status"] == "NO_HISTORICAL_SUPPORT"
    assert generated.json()["candidates"] == []
    assert generated.json()["warnings"]


def test_visual_invalid_closed_profile_returns_stable_error(tmp_path):
    profile = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures/visual_profiles/closed_without_seam.json").read_text())
    client = TestClient(create_app(tmp_path / "workspace", auto_run_jobs=False))
    response = client.post("/api/visual-flower/targets", json={"profile": profile})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SEAM_REQUIRED"
