from __future__ import annotations

import json

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.exporters import export_project
from rollform_extractor.composite_flower import build_composite_flowers
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


def test_export_writes_complete_composite_flower_package(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    entities = (
        _line_entity("H1", "FLOWER", (0, 0, 0), (10, 0, 0)),
        _line_entity("H2", "FLOWER", (0, 0, 0), (8, 4, 0)),
    )
    station = StationRecord(
        "S1",
        1,
        BBox(0, 0, 10, 4),
        ("H1", "H2"),
        "test",
        "config",
        0.9,
        {"region_type": "COMPOSITE_FLOWER", "sequence_id": 1},
    )
    profiles = (
        _composite_profile("P0", "S1", "H1", entities[0].normalized_primitives, 10.0, 10.0, 0.0, 0, 2),
        _composite_profile("P1", "S1", "H2", entities[1].normalized_primitives, 8.944, 8.0, 4.0, 1, 2),
    )
    composite_flowers = build_composite_flowers((station,), profiles, entities)
    bundle = ExtractionBundle(
        drawing_id="flower",
        source_path=source,
        source_sha256="source",
        converted_path=source,
        converted_sha256="source",
        configuration_snapshot={"units": {"detected": "Unitless", "confirmed": False}},
        configuration_hash="config",
        status="success",
        entities=entities,
        stations=(station,),
        profiles=profiles,
        roller_occurrences=(),
        composite_flowers=composite_flowers,
    )

    export_project(bundle, tmp_path)
    root = tmp_path / "flower" / "composite_flowers" / "composite_flower_01"
    sequence = (root / "sequence.csv").read_text(encoding="utf-8")

    assert (root / "complete_composite_flower.dxf").stat().st_size > 0
    assert (root / "complete_composite_flower.png").stat().st_size > 0
    assert (root / "sequence_preview.png").stat().st_size > 0
    assert (root / "overlaid_reconstruction.dxf").stat().st_size > 0
    assert (root / "overlaid_reconstruction.png").stat().st_size > 0
    assert (root / "extraction_debug.png").stat().st_size > 0
    assert "developed_length_drawing_units" in sequence
    assert "developed_length_mm" in sequence
    assert ",10.0,," in sequence
    assert (root / "passes" / "pass_00_flat" / "profile.dxf").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_original_coordinates.dxf").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_normalized.dxf").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_outline.dxf").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_neutral_line.dxf").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_outline.png").stat().st_size > 0
    assert (root / "passes" / "pass_00_flat" / "profile_neutral_line.png").stat().st_size > 0
    geometry = json.loads((root / "passes" / "pass_00_flat" / "profile_geometry.json").read_text(encoding="utf-8"))
    assert geometry["profile_representation"] == "SOURCE_STRIP_OUTLINE"
    assert geometry["neutral_line"]["method"]
    assert json.loads((root / "passes" / "pass_00_flat" / "source_entities.json").read_text(encoding="utf-8"))["entities"][0]["handle"] == "H1"


def test_report_contains_offline_interactive_flower_sequence_viewer(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    entities = (
        _line_entity("H1", "FLOWER", (0, 0, 0), (10, 0, 0)),
        _line_entity("H2", "FLOWER", (0, 0, 0), (8, 4, 0)),
    )
    station = StationRecord("S1", 1, BBox(0, 0, 10, 4), ("H1", "H2"), "test", "config", 0.9, {"region_type": "COMPOSITE_FLOWER", "sequence_id": 1})
    profiles = (
        _composite_profile("P0", "S1", "H1", entities[0].normalized_primitives, 10.0, 10.0, 0.0, 0, 2),
        _composite_profile("P1", "S1", "H2", entities[1].normalized_primitives, 8.944, 8.0, 4.0, 1, 2),
    )
    composite_flowers = build_composite_flowers((station,), profiles, entities)
    bundle = ExtractionBundle(
        drawing_id="flower",
        source_path=source,
        source_sha256="source",
        converted_path=source,
        converted_sha256="source",
        configuration_snapshot={"units": {"detected": "Unitless", "confirmed": False}},
        configuration_hash="config",
        status="success",
        entities=entities,
        stations=(station,),
        profiles=profiles,
        roller_occurrences=(),
        composite_flowers=composite_flowers,
    )

    export_project(bundle, tmp_path)
    html = (tmp_path / "flower" / "report.html").read_text(encoding="utf-8")
    report_data = json.loads((tmp_path / "flower" / "report_data.json").read_text(encoding="utf-8"))

    assert "Flower Sequences" in html
    assert 'id="report-data"' in html
    assert "Previous" in html and "Next" in html and "sequence-slider" in html
    assert "Single-pass" in html and "Overlay" in html and "Cumulative" in html
    assert report_data["composite_flowers"][0]["label"] == "Composite Flower 01"
    assert len(report_data["composite_flowers"][0]["passes"]) == 2
    assert report_data["composite_flowers"][0]["passes"][0]["physical_forming_bend_count"] == 0
    assert report_data["composite_flowers"][0]["passes"][0]["downloads"]["profile_dxf"].endswith("profile.dxf")
    assert "bend_progression" in report_data["composite_flowers"][0]
    assert "developed_length_progression" in report_data["composite_flowers"][0]
    assert "profile_step_changes" in report_data["composite_flowers"][0]
    assert "bend_change_events" in report_data["composite_flowers"][0]
    assert "segment_change_events" in report_data["composite_flowers"][0]
    assert "What Changed?" in html


def _line_entity(handle: str, layer: str, start, end) -> object:
    primitive = CadPrimitive("LINE", {"start": start, "end": end}, handle)
    bbox = BBox(min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1]))
    from rollform_extractor.models import CadEntityRecord

    return CadEntityRecord(
        handle,
        "LINE",
        layer,
        7,
        "CONTINUOUS",
        "model",
        bbox,
        (primitive,),
        (primitive,),
        (start, end),
        source_handles=(handle,),
    )


def _composite_profile(
    profile_id: str,
    station_id: str,
    handle: str,
    primitives: tuple[CadPrimitive, ...],
    developed_length: float,
    width: float,
    height: float,
    pass_index: int,
    pass_count: int,
) -> ProfileRecord:
    return ProfileRecord(
        profile_id,
        station_id,
        (handle,),
        "composite_flower_detector",
        "config",
        0.82,
        {
            "normalized_primitives": primitives,
            "original_primitives": primitives,
            "exact_length": developed_length,
            "bbox": BBox(0, 0, width, height),
            "bend_angles": (25.0,) if pass_index else (),
            "profile_state": "CENTERLINE_PROFILE",
            "composite_pass_index": pass_index,
            "composite_pass_count": pass_count,
        },
    )
