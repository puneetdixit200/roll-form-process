from __future__ import annotations

import json

from rollform_extractor.flower_evidence_organizer import build_flower_evidence_library


def _pass(index: int) -> dict:
    return {
        "pass_id": f"F1-pass-{index:03d}",
        "inferred_order": index,
        "source_handle": f"H{index}",
        "points": [[0, 0], [index + 1, index]],
        "width": index + 1,
        "height": index,
        "developed_length": index + 2,
        "topology": "OPEN_PATH",
        "quality_flags": [],
    }


def test_builds_four_labelled_folders_and_direct_indexes(tmp_path):
    source = tmp_path / "source.dxf"
    roller = tmp_path / "roller.dxf"
    unindexed = tmp_path / "unindexed.dxf"
    source.write_text("flower", encoding="utf-8")
    roller.write_text("roller", encoding="utf-8")
    unindexed.write_text("review", encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({
        "dataset_id": "D1",
        "dataset_hash": "abc",
        "flowers": [{"flower_id": "F1", "passes": [_pass(i) for i in range(5)]}],
    }), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "dataset_path": str(dataset),
        "flowers": [{
            "flower_id": "F1",
            "source_path": str(source),
            "roller_sources": [{"evidence_id": "R1", "path": str(roller), "association_status": "UNRESOLVED_STATION_ASSOCIATION"}],
        }],
        "unindexed_sources": [{"source_id": "SOURCE-2", "source_path": str(unindexed)}],
    }), encoding="utf-8")

    result = build_flower_evidence_library(manifest, tmp_path / "library")

    assert result["folder_contract"] == ["01_FLOWER_SEQUENCES", "02_STATIONS", "03_SUBSEQUENCES", "04_ROLLERS"]
    assert result["verified_flowers"][0]["station_count"] == 5
    assert result["verified_flowers"][0]["subsequence_count"] == 3
    assert result["physical_asset_assignment"] is False
    assert (tmp_path / "library/02_STATIONS/F1/STATION-003/PROFILE.svg").is_file()
    assert (tmp_path / "library/03_SUBSEQUENCES/F1/SUBSEQUENCE-002-TO-004/SUBSEQUENCE.json").is_file()
    evidence = json.loads((tmp_path / "library/04_ROLLERS/F1/ROLLER_EVIDENCE.json").read_text())
    assert evidence["records"][0]["association_status"] == "UNRESOLVED_STATION_ASSOCIATION"
    station = json.loads((tmp_path / "library/02_STATIONS/F1/STATION-003/STATION.json").read_text())
    assert station["roller_evidence_link"] == "../../../04_ROLLERS/F1/ROLLER_EVIDENCE.json"
    locations = json.loads((tmp_path / "library/FILE_LOCATIONS.json").read_text())
    station_location = next(item for item in locations["files"] if item["relative_path"] == "02_STATIONS/F1/STATION-003/STATION.json")
    assert station_location["absolute_path"] == str(tmp_path / "library/02_STATIONS/F1/STATION-003/STATION.json")
    assert station_location["station_label"] == "STATION-003"
    assert station_location["visibility"] == "PRIVATE_LOCAL_ONLY"
    review_location = next(item for item in locations["files"] if item["filename"] == "SOURCE_STATUS.json")
    assert review_location["source_id"] == "SOURCE-2"
    assert review_location["flower_id"] is None
    assert (tmp_path / "library/FILE_LOCATIONS.csv").is_file()
    assert (tmp_path / "library/INDEX.html").is_file()


def test_regeneration_replaces_only_the_named_library(tmp_path):
    source = tmp_path / "source.dxf"
    source.write_text("flower", encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"flowers": [{"flower_id": "F1", "passes": [_pass(i) for i in range(3)]}]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"dataset_path": str(dataset), "flowers": [{"flower_id": "F1", "source_path": str(source)}]}), encoding="utf-8")
    library = tmp_path / "library"

    first = build_flower_evidence_library(manifest, library)
    second = build_flower_evidence_library(manifest, library)

    assert first == second
    assert json.loads((library / "INDEX.json").read_text()) == second
    assert not list(tmp_path.glob(".library.tmp-*"))
    assert not list(tmp_path.glob(".library.backup-*"))
