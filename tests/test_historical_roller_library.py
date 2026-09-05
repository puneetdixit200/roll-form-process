import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from rollform_extractor.historical_roller_library import build_roller_library, attach_subsequence_rollers, library_hash, roller_asset
from rollform_extractor.web.backend.api.app import create_app


def fixture_library(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "INDEX.json").write_text(json.dumps({"dataset_hash": "test-dataset"}))
    for flower in ("A", "B", "C"):
        folder = root / "04_ROLLERS" / flower
        roller = folder / "STATION-001" / "R1"
        roller.mkdir(parents=True)
        (folder / "ROLLER_EVIDENCE.json").write_text(json.dumps({"flower_id": flower, "station_mapping": {"station_mappings": [
            {"pass_id": "P1", "station_label": "STATION-001", "source_station_id": "S1", "confirmation_status": "CANDIDATE_NOT_ENGINEER_CONFIRMED"},
            {"pass_id": "P2", "station_label": "STATION-002", "source_station_id": "S2"},
        ]}}))
        (roller / "ROLLER.json").write_text(json.dumps({"occurrence_id": "R1", "candidate_role": "UPPER", "geometry_completeness": "PARTIAL_GEOMETRY", "private_path": "/private/source.dxf"}))
        (roller / "ROLLER.png").write_bytes(b"\x89PNG" + flower.encode())
        (roller / "ROLLER.dxf").write_bytes(flower.encode())
    output = tmp_path / "rollers.sqlite"
    build_roller_library(root, output)
    return root, output


def matches():
    return [{"top_historical_subsequences": [{"source_flower_id": flower, "mapping": [{"source_pass_id": "P1"}, {"source_pass_id": "P2"}, {"source_pass_id": "missing"}]} for flower in ("A", "B", "C")]}]


def test_top_three_lookup_is_scoped_and_partial_is_preserved(tmp_path):
    root, db = fixture_library(tmp_path)
    candidates = matches()
    attach_subsequence_rollers(candidates, db, "test-dataset")
    ids = []
    for flower, match in zip(("A", "B", "C"), candidates[0]["top_historical_subsequences"]):
        first, empty, missing = match["mapping"]
        roller = first["roller_occurrences"][0]
        ids.append(roller["roller_id"])
        assert roller["geometry_completeness"] == "PARTIAL_GEOMETRY"
        assert roller["physical_asset_assignment"] is False
        assert roller_asset(db, "test-dataset", roller["roller_id"], "dxf") == flower.encode()
        assert "private_path" not in roller
        assert empty["roller_link_status"] == "NO_ROLLER_DETECTED"
        assert missing["roller_link_status"] == "NO_SOURCE_STAGE"
    assert len(set(ids)) == 3
    digest = library_hash(db, "test-dataset")
    assert build_roller_library(root, db)["content_hash"] == digest
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_stale_dataset_and_invalid_asset_kind_abstain(tmp_path):
    _, db = fixture_library(tmp_path)
    candidates = matches()
    attach_subsequence_rollers(candidates, db, "different")
    assert candidates[0]["top_historical_subsequences"][0]["mapping"][0]["roller_occurrences"] == []
    assert library_hash(db, "different") == "STALE_DATASET"
    assert roller_asset(db, "test-dataset", "x", "metadata FROM rollers") is None
    assert roller_asset(db, "different", "x", "png") is None


def test_individual_top_three_do_not_inherit_interval_or_other_pass_rollers(tmp_path):
    _, db = fixture_library(tmp_path)
    candidate = matches()[0]
    candidate["passes"] = [{"pass_id": "G1", "historical_match": {"top_matches": [
        {"source_flower_id": "B", "source_pass_id": "P1"},
        {"source_flower_id": "A", "source_pass_id": "P2"},
        {"source_flower_id": "C", "source_pass_id": "P1"},
    ]}}]
    attach_subsequence_rollers([candidate], db, "test-dataset")
    first, empty, third = candidate["passes"][0]["historical_match"]["top_matches"]
    assert roller_asset(db, "test-dataset", first["roller_occurrences"][0]["roller_id"], "dxf") == b"B"
    assert empty["roller_occurrences"] == []
    assert empty["roller_link_status"] == "NO_ROLLER_DETECTED"
    assert roller_asset(db, "test-dataset", third["roller_occurrences"][0]["roller_id"], "dxf") == b"C"


def test_failed_rebuild_preserves_previous_database(tmp_path):
    root, db = fixture_library(tmp_path)
    original = db.read_bytes()
    (root / "04_ROLLERS/A/STATION-001/R1/ROLLER.png").unlink()
    with pytest.raises(FileNotFoundError):
        build_roller_library(root, db)
    assert db.read_bytes() == original


def test_api_serves_indexed_bytes_and_rejects_missing_ids(tmp_path, monkeypatch):
    _, db = fixture_library(tmp_path)
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"dataset_hash": "test-dataset", "flowers": []}))
    monkeypatch.setenv("ROLLFORM_FLOWER_PROTOTYPE_DATASET", str(dataset))
    monkeypatch.setenv("ROLLFORM_HISTORICAL_ROLLER_SQLITE", str(db))
    candidates = matches()
    attach_subsequence_rollers(candidates, db, "test-dataset")
    identifier = candidates[0]["top_historical_subsequences"][0]["mapping"][0]["roller_occurrences"][0]["roller_id"]
    client = TestClient(create_app(tmp_path / "workspace", auto_run_jobs=False))
    response = client.get(f"/api/visual-flower/historical/rollers/{identifier}/png")
    assert response.status_code == 200
    assert response.content == b"\x89PNGA"
    assert client.get("/api/visual-flower/historical/rollers/missing/png").status_code == 404


def test_generation_persists_links_and_changed_library_invalidates_cache(tmp_path, monkeypatch):
    from pathlib import Path
    from rollform_extractor import visual_flower_service as service
    from rollform_extractor.database import create_project_database

    root, db = fixture_library(tmp_path)
    monkeypatch.setenv("ROLLFORM_HISTORICAL_ROLLER_SQLITE", str(db))
    monkeypatch.setattr(service, "historical_dataset", lambda: {"dataset_hash": "test-dataset", "flowers": []})
    def generated(*args, **kwargs):
        candidate = matches()[0] | {"candidate_id": "C1", "status": "READY", "visual_confidence": {"score": 50}}
        return {"candidates": [candidate], "algorithm_version": "test"}
    monkeypatch.setattr(service, "generate_visual_candidates", generated)
    engine = create_project_database(tmp_path / "project.sqlite")
    profile = json.loads((Path(__file__).parent / "fixtures/visual_profiles/open_channel.json").read_text())
    target = service.create_target(engine, {"profile": profile})
    preferences = {"generation_engine": "DETERMINISTIC", "include_roller_evidence": False}
    first = service.generate_for_target(engine, target["target_id"], preferences)
    stored = service.get_candidate(engine, first["candidates"][0]["candidate_id"])
    assert stored["top_historical_subsequences"][0]["mapping"][0]["roller_occurrences"]
    assert service.generate_for_target(engine, target["target_id"], preferences)["run_id"] == first["run_id"]
    (root / "04_ROLLERS/A/STATION-001/R1/ROLLER.png").write_bytes(b"updated-preview")
    build_roller_library(root, db)
    second = service.generate_for_target(engine, target["target_id"], preferences)
    assert second["run_id"] != first["run_id"]
