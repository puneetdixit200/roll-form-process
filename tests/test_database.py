from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rollform_extractor.database import (
    CadEntity,
    ExtractionBundle,
    ExtractionRun,
    ExtractionWarning,
    ProcessingStage,
    Profile,
    ResultProvenance,
    create_project_database,
    foreign_key_violations,
    persist_extraction,
    record_stage,
)
from rollform_extractor.models import (
    BBox,
    CadEntityRecord,
    CadPrimitive,
    ProfileRecord,
    StageResult,
    StationRecord,
    WarningRecord,
)


REQUIRED_PROJECT_TABLES = {
    "projects",
    "extraction_runs",
    "layers",
    "stations",
    "profiles",
    "rollers",
    "assemblies",
    "assembly_members",
    "cad_entities",
    "annotations",
    "dimensions",
    "station_transitions",
    "extraction_warnings",
    "roller_catalog",
    "roller_occurrences",
    "project_roll_usage",
    "assembly_templates",
    "geometry_fingerprints",
    "processing_stages",
    "result_provenance",
    "project_codes",
    "project_metadata",
}


def test_project_schema_contains_required_and_cross_project_tables(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")

    names = set(inspect(engine).get_table_names())

    assert REQUIRED_PROJECT_TABLES <= names
    assert foreign_key_violations(engine) == []


def test_sqlite_foreign_keys_are_enforced(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(Profile(profile_id="P-missing", station_id="missing"))
            session.commit()


def test_persist_extraction_separates_geometry_and_records_provenance(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    project_id = persist_extraction(engine, _bundle())

    with Session(engine) as session:
        entity = session.scalar(select(CadEntity).where(CadEntity.handle == "10"))
        station = session.scalar(select(Profile).where(Profile.profile_id == "P1"))
        provenance = session.scalars(
            select(ResultProvenance).where(ResultProvenance.project_id == project_id)
        ).all()

    assert entity.original_primitives_json == [
        {"kind": "LINE", "attributes": {"start": [0, 0, 0], "end": [1, 0, 0]}, "source_handle": "10"}
    ]
    assert entity.normalized_primitives_json == [
        {"kind": "LINE", "attributes": {"start": [0, 0, 0], "end": [25.4, 0, 0]}, "source_handle": "10"}
    ]
    assert entity.sampled_geometry_json == [[0, 0, 0], [25.4, 0, 0]]
    assert entity.sampled_wkt == "LINESTRING Z (0 0 0, 25.4 0 0)"
    assert station.features_json == {"developed_length_mm": 25.4}
    assert {
        (row.result_table, row.result_key, tuple(row.source_handles), row.method, row.configuration_hash)
        for row in provenance
    } >= {
        ("cad_entities", "10", ("10",), "parsed", "parse-hash"),
        ("stations", "S1", ("10",), "station_detection", "station-hash"),
        ("profiles", "P1", ("10",), "profile_detection", "profile-hash"),
    }


def test_failed_stage_and_run_keep_diagnostics(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    project_id = persist_extraction(
        engine,
        ExtractionBundle(
            drawing_id="failed-drawing",
            source_path=Path("failed.dxf"),
            source_sha256="bad-source",
            converted_path=None,
            converted_sha256=None,
            configuration_snapshot={"profiles": {"minimum_confidence": 0.7}},
            configuration_hash="failed-config",
            status="failed",
            entities=(),
            stations=(),
            profiles=(),
            roller_occurrences=(),
            warnings=(
                WarningRecord(
                    code="conversion_failed",
                    message="converter exited 1",
                    source_handles=(),
                    method="conversion",
                    configuration_hash="conversion-hash",
                    confidence=1.0,
                ),
            ),
        ),
    )
    record_stage(
        engine,
        project_id,
        StageResult(
            stage="conversion",
            records=(),
            warnings=(
                WarningRecord(
                    code="conversion_failed",
                    message="converter exited 1",
                    source_handles=(),
                    method="conversion",
                    configuration_hash="conversion-hash",
                    confidence=1.0,
                ),
            ),
            source_handles=(),
            method="oda",
            configuration_hash="conversion-hash",
            confidence=0.0,
        ),
    )

    with Session(engine) as session:
        run = session.scalar(select(ExtractionRun).where(ExtractionRun.project_id == project_id))
        stage = session.scalar(select(ProcessingStage).where(ProcessingStage.project_id == project_id))
        warnings = session.scalars(
            select(ExtractionWarning).where(ExtractionWarning.project_id == project_id)
        ).all()

    assert run.status == "failed"
    assert run.configuration_snapshot_json == {"profiles": {"minimum_confidence": 0.7}}
    assert stage.status == "failed"
    assert stage.configuration_hash == "conversion-hash"
    assert stage.diagnostics_json == {"warnings": [{"code": "conversion_failed", "message": "converter exited 1"}]}
    assert [(warning.code, warning.message) for warning in warnings] == [
        ("conversion_failed", "converter exited 1"),
        ("conversion_failed", "converter exited 1"),
    ]


def _bundle() -> ExtractionBundle:
    original = CadPrimitive(
        kind="LINE",
        attributes={"start": (0, 0, 0), "end": (1, 0, 0)},
        source_handle="10",
    )
    normalized = CadPrimitive(
        kind="LINE",
        attributes={"start": (0, 0, 0), "end": (25.4, 0, 0)},
        source_handle="10",
    )
    entity = CadEntityRecord(
        handle="10",
        entity_type="LINE",
        layer="PROFILE",
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(0, 0, 1, 0),
        original_primitives=(original,),
        normalized_primitives=(normalized,),
        sampled_geometry=((0, 0, 0), (25.4, 0, 0)),
        source_handles=("10",),
        method="parsed",
        configuration_hash="parse-hash",
        confidence=1.0,
        attributes={"lineweight": 25},
    )
    station = StationRecord(
        station_id="S1",
        sequence_index=1,
        bbox=BBox(0, 0, 10, 10),
        source_handles=("10",),
        method="station_detection",
        configuration_hash="station-hash",
        confidence=0.9,
        evidence={"label": "S1"},
    )
    profile = ProfileRecord(
        profile_id="P1",
        station_id="S1",
        source_handles=("10",),
        method="profile_detection",
        configuration_hash="profile-hash",
        confidence=0.8,
        features={"developed_length_mm": 25.4},
    )
    return ExtractionBundle(
        drawing_id="D0064-D0065-FlowerSequence",
        source_path=Path("source.dxf"),
        source_sha256="source-hash",
        converted_path=Path("converted.dxf"),
        converted_sha256="converted-hash",
        configuration_snapshot={"geometry": {"curve_sampling_spacing_mm": 0.25}},
        configuration_hash="bundle-config",
        status="success",
        entities=(entity,),
        stations=(station,),
        profiles=(profile,),
        roller_occurrences=(),
        warnings=(),
    )
