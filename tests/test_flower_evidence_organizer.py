from __future__ import annotations

import json

import ezdxf

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
    flower_record = json.loads((tmp_path / "library/01_FLOWER_SEQUENCES/F1/FLOWER.json").read_text())
    assert "source_region_id" in flower_record
    split_dxf = tmp_path / "library/01_FLOWER_SEQUENCES/F1/F1-EXTRACTED-SEQUENCE.dxf"
    assert split_dxf.is_file()
    assert len(ezdxf.readfile(split_dxf).modelspace().query("POLYLINE")) == 5
    assert (tmp_path / "library/01_FLOWER_SEQUENCES/F1/F1-FULL-SEQUENCE.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "library/02_STATIONS/F1/STATION-003/PROFILE.png").read_bytes().startswith(b"\x89PNG")
    subsequence = tmp_path / "library/03_SUBSEQUENCES/F1/SUBSEQUENCE-002-TO-004"
    assert len(ezdxf.readfile(subsequence / "ROLL-FORM-SUBSEQUENCE.dxf").modelspace().query("POLYLINE")) == 3
    assert (subsequence / "ROLL-FORM-SUBSEQUENCE.png").read_bytes().startswith(b"\x89PNG")
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


def test_exports_station_roller_png_and_dxf_including_partial_geometry(tmp_path):
    source = tmp_path / "source.dxf"
    source.write_text("flower", encoding="utf-8")
    extraction = tmp_path / "extraction"
    (extraction / "source").mkdir(parents=True)
    drawing = ezdxf.new("R2018")
    profile_entities = [drawing.modelspace().add_polyline3d([(0, index), (2, index + 1), (4, index)]) for index in range(3)]
    roller = drawing.modelspace().add_polyline3d([(0, 0), (1, 1), (2, 0)])
    drawing.saveas(extraction / "source" / "drawing.dxf")
    (extraction / "project.json").write_text(json.dumps({
        "profiles": [
            {"profile_id": f"P{index}", "station_id": f"S{index}", "source_handles": [entity.dxf.handle]}
            for index, entity in enumerate(profile_entities)
        ],
        "rollers": [{
            "occurrence_id": "S1-R1",
            "station_id": "S1",
            "role": None,
            "source_handles": [roller.dxf.handle],
            "confidence": 0.6,
            "evidence": {"candidate_role": "upper_left"},
        }],
    }), encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    passes = [_pass(index) for index in range(3)]
    for index, item in enumerate(passes):
        item["source_handle"] = profile_entities[index].dxf.handle
    dataset.write_text(json.dumps({"dataset_id": "D1", "dataset_hash": "abc", "flowers": [{"flower_id": "F1", "passes": passes}]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "dataset_path": str(dataset),
        "flowers": [{"flower_id": "F1", "source_path": str(source), "extraction_project_path": str(extraction)}],
    }), encoding="utf-8")

    library = tmp_path / "library"
    build_flower_evidence_library(manifest, library)

    roller_root = library / "04_ROLLERS/F1/STATION-002/S1-R1"
    assert (roller_root / "ROLLER.png").read_bytes().startswith(b"\x89PNG")
    assert len(ezdxf.readfile(roller_root / "ROLLER.dxf").modelspace().query("POLYLINE")) == 1
    first_dxf = (roller_root / "ROLLER.dxf").read_bytes()
    record = json.loads((roller_root / "ROLLER.json").read_text())
    assert record["candidate_role"] == "UPPER_LEFT"
    assert record["geometry_completeness"] == "PARTIAL_GEOMETRY"
    roller_manifest = json.loads((roller_root.parent / "STATION_ROLLERS.json").read_text())
    assert roller_manifest["roller_occurrence_count"] == 1
    assert roller_manifest["roller_occurrences"][0]["png"] == "S1-R1/ROLLER.png"
    station = json.loads((tmp_path / "library/02_STATIONS/F1/STATION-002/STATION.json").read_text())
    assert station["roller_occurrence_count"] == 1
    subsequence = json.loads((tmp_path / "library/03_SUBSEQUENCES/F1/SUBSEQUENCE-001-TO-003/SUBSEQUENCE.json").read_text())
    assert subsequence["roller_occurrence_count"] == 1

    build_flower_evidence_library(manifest, library)
    assert (roller_root / "ROLLER.dxf").read_bytes() == first_dxf
