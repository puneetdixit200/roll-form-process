from __future__ import annotations

import json

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.exporters import export_project
from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord, RollerOccurrenceRecord, StationRecord, WarningRecord
from rollform_extractor.pipeline import ExtractionRequest, extract_project
from tests.cad_factory import make_flower_dxf


def test_manifest_records_export_files_and_hashes(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=2, labels=True, rollers=True)

    summary = extract_project(ExtractionRequest(source, tmp_path / "out"))
    manifest = json.loads((summary.project_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["station_count"] == 2
    assert "stations/station_01/profile.dxf" in manifest["files"]
    assert "stations/station_02/profile.dxf" in manifest["files"]
    assert manifest["files"]["project.json"]["sha256"]
    assert all(path.exists() for path in summary.manifest.dxf_files)


def test_export_warns_when_profile_primitive_cannot_be_recreated_as_dxf(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    bundle = ExtractionBundle(
        drawing_id="unsupported",
        source_path=source,
        source_sha256="source",
        converted_path=source,
        converted_sha256="source",
        configuration_snapshot={"units": {"default": "mm"}},
        configuration_hash="config",
        status="success",
        entities=(),
        stations=(
            StationRecord("S1", 1, BBox(0, 0, 1, 1), ("A",), "test", "config", 1.0),
        ),
        profiles=(
            ProfileRecord("P1", "S1", ("A",), "test", "config", 1.0, {"normalized_primitives": (CadPrimitive("SPLINE", {}, "A"),)}),
        ),
        roller_occurrences=(),
        warnings=(
            WarningRecord("preexisting", "kept", (), "test", "config", 1.0),
        ),
    )

    export_project(bundle, tmp_path)
    review = json.loads((tmp_path / "flower" / "review" / "review_queue.json").read_text(encoding="utf-8"))

    assert any(item["category"] == "export" and "SPLINE" in item["message"] for item in review["items"])


def test_project_json_preserves_detection_methods_for_benchmarks(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    bundle = ExtractionBundle(
        drawing_id="methods",
        source_path=source,
        source_sha256="source",
        converted_path=source,
        converted_sha256="source",
        configuration_snapshot={"units": {"default": "mm"}},
        configuration_hash="config",
        status="success",
        entities=(),
        stations=(
            StationRecord("S1", 1, BBox(0, 0, 1, 1), ("A",), "manual_override", "config", 1.0),
        ),
        profiles=(
            ProfileRecord("P1", "S1", ("A",), "profile_detection", "config", 1.0),
        ),
        roller_occurrences=(
            RollerOccurrenceRecord("R1", "S1", "upper", ("R",), "roller_detection", "config", 1.0),
        ),
    )

    export_project(bundle, tmp_path)
    project = json.loads((tmp_path / "flower" / "project.json").read_text(encoding="utf-8"))

    assert project["stations"][0]["method"] == "manual_override"
    assert project["profiles"][0]["method"] == "profile_detection"
    assert project["rollers"][0]["method"] == "roller_detection"
