from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from rollform_extractor.models import (
    CadEntityRecord,
    CadPrimitive,
    ProfileRecord,
    RollerOccurrenceRecord,
    StageResult,
    StationRecord,
    WarningRecord,
)


@dataclass(frozen=True)
class ExtractionBundle:
    drawing_id: str
    source_path: Path
    source_sha256: str
    converted_path: Path | None
    converted_sha256: str | None
    configuration_snapshot: Mapping[str, Any]
    configuration_hash: str
    status: str
    entities: tuple[CadEntityRecord, ...]
    stations: tuple[StationRecord, ...]
    profiles: tuple[ProfileRecord, ...]
    roller_occurrences: tuple[RollerOccurrenceRecord, ...]
    warnings: tuple[WarningRecord, ...] = ()


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    drawing_id: Mapped[str] = mapped_column(String, unique=True)
    source_path: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String)
    converted_path: Mapped[str | None] = mapped_column(Text)
    converted_sha256: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    configuration_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Layer(Base):
    __tablename__ = "layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)


class Station(Base):
    __tablename__ = "stations"

    station_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    sequence_index: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Profile(Base):
    __tablename__ = "profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Roller(Base):
    __tablename__ = "rollers"

    roller_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str | None] = mapped_column(ForeignKey("stations.station_id", ondelete="SET NULL"))
    role: Mapped[str | None] = mapped_column(String)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Assembly(Base):
    __tablename__ = "assemblies"

    assembly_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str | None] = mapped_column(ForeignKey("stations.station_id", ondelete="SET NULL"))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("assembly_templates.template_id"))


class AssemblyMember(Base):
    __tablename__ = "assembly_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assembly_id: Mapped[str] = mapped_column(ForeignKey("assemblies.assembly_id", ondelete="CASCADE"))
    roller_id: Mapped[str] = mapped_column(ForeignKey("rollers.roller_id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String)


class CadEntity(Base):
    __tablename__ = "cad_entities"

    handle: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String)
    layer: Mapped[str] = mapped_column(String)
    color: Mapped[str | int | None] = mapped_column(JSON)
    line_type: Mapped[str | None] = mapped_column(String)
    layout: Mapped[str] = mapped_column(String)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    original_primitives_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    normalized_primitives_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sampled_geometry_json: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    sampled_wkt: Mapped[str | None] = mapped_column(Text)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entity_handle: Mapped[str | None] = mapped_column(ForeignKey("cad_entities.handle", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)


class Dimension(Base):
    __tablename__ = "dimensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entity_handle: Mapped[str | None] = mapped_column(ForeignKey("cad_entities.handle", ondelete="SET NULL"))
    measurement: Mapped[float | None] = mapped_column(Float)


class StationTransition(Base):
    __tablename__ = "station_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    from_station_id: Mapped[str | None] = mapped_column(ForeignKey("stations.station_id", ondelete="SET NULL"))
    to_station_id: Mapped[str | None] = mapped_column(ForeignKey("stations.station_id", ondelete="SET NULL"))
    measurements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExtractionWarning(Base):
    __tablename__ = "extraction_warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)


class RollerCatalog(Base):
    __tablename__ = "roller_catalog"

    roller_catalog_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    factory_id: Mapped[str | None] = mapped_column(String, unique=True)
    geometry_fingerprint_id: Mapped[int | None] = mapped_column(ForeignKey("geometry_fingerprints.id"))
    bore: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    diameter: Mapped[float | None] = mapped_column(Float)
    keyway: Mapped[str | None] = mapped_column(String)
    condition: Mapped[str | None] = mapped_column(String)
    storage_location: Mapped[str | None] = mapped_column(String)
    availability: Mapped[str | None] = mapped_column(String)


class RollerOccurrence(Base):
    __tablename__ = "roller_occurrences"

    occurrence_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.station_id", ondelete="CASCADE"))
    roller_catalog_id: Mapped[int | None] = mapped_column(ForeignKey("roller_catalog.roller_catalog_id"))
    role: Mapped[str | None] = mapped_column(String)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProjectRollUsage(Base):
    __tablename__ = "project_roll_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    roller_catalog_id: Mapped[int] = mapped_column(ForeignKey("roller_catalog.roller_catalog_id"))
    assembly_id: Mapped[str | None] = mapped_column(ForeignKey("assemblies.assembly_id", ondelete="SET NULL"))
    occurrence_id: Mapped[str | None] = mapped_column(ForeignKey("roller_occurrences.occurrence_id", ondelete="SET NULL"))


class AssemblyTemplate(Base):
    __tablename__ = "assembly_templates"

    template_id: Mapped[str] = mapped_column(String, primary_key=True)
    signature_hash: Mapped[str | None] = mapped_column(String)
    template_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GeometryFingerprint(Base):
    __tablename__ = "geometry_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    owner_table: Mapped[str | None] = mapped_column(String)
    owner_key: Mapped[str | None] = mapped_column(String)
    fingerprint_hash: Mapped[str] = mapped_column(String)
    fingerprint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProcessingStage(Base):
    __tablename__ = "processing_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    software_version: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    artifact_hashes_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ResultProvenance(Base):
    __tablename__ = "result_provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    result_table: Mapped[str] = mapped_column(String)
    result_key: Mapped[str] = mapped_column(String)
    field_name: Mapped[str | None] = mapped_column(String)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    warning: Mapped[str | None] = mapped_column(Text)


class ProjectCode(Base):
    __tablename__ = "project_codes"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source: Mapped[str | None] = mapped_column(String)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProjectMetadata(Base):
    __tablename__ = "project_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    value: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def create_project_database(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def persist_extraction(engine: Engine, bundle: ExtractionBundle) -> int:
    with Session(engine) as session, session.begin():
        project = Project(
            drawing_id=bundle.drawing_id,
            source_path=str(bundle.source_path),
            source_sha256=bundle.source_sha256,
            converted_path=str(bundle.converted_path) if bundle.converted_path else None,
            converted_sha256=bundle.converted_sha256,
        )
        session.add(project)
        session.flush()

        session.add(
            ExtractionRun(
                project_id=project.id,
                status=bundle.status,
                configuration_hash=bundle.configuration_hash,
                configuration_snapshot_json=_jsonable(bundle.configuration_snapshot),
            )
        )
        for layer in sorted({entity.layer for entity in bundle.entities}):
            session.add(Layer(project_id=project.id, name=layer))
        for entity in bundle.entities:
            session.add(_cad_entity(project.id, entity))
            _add_provenance(session, project.id, "cad_entities", entity.handle, None, entity)
        for station in bundle.stations:
            session.add(_station(project.id, station))
            _add_provenance(session, project.id, "stations", station.station_id, None, station)
        session.flush()
        for profile in bundle.profiles:
            session.add(_profile(project.id, profile))
            _add_provenance(session, project.id, "profiles", profile.profile_id, None, profile)
        for occurrence in bundle.roller_occurrences:
            session.add(_roller_occurrence(project.id, occurrence))
            _add_provenance(session, project.id, "roller_occurrences", occurrence.occurrence_id, None, occurrence)
        for warning in bundle.warnings:
            session.add(_warning(project.id, warning))

        return project.id


def record_stage(engine: Engine, project_id: int, result: StageResult) -> None:
    warnings = [{"code": warning.code, "message": warning.message} for warning in result.warnings]
    status = "failed" if warnings or result.confidence <= 0 else "success"
    with Session(engine) as session, session.begin():
        session.add(
            ProcessingStage(
                project_id=project_id,
                stage=result.stage,
                status=status,
                input_hash=",".join(result.source_handles) or None,
                configuration_hash=result.configuration_hash,
                software_version=None,
                artifact_hashes_json={},
                diagnostics_json={"warnings": warnings},
            )
        )
        for warning in result.warnings:
            session.add(_warning(project_id, warning))


def foreign_key_violations(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text("PRAGMA foreign_key_check"))]


def _cad_entity(project_id: int, entity: CadEntityRecord) -> CadEntity:
    return CadEntity(
        handle=entity.handle,
        project_id=project_id,
        entity_type=entity.entity_type,
        layer=entity.layer,
        color=_jsonable(entity.color),
        line_type=entity.line_type,
        layout=entity.layout,
        bbox_json=_bbox(entity.bbox),
        attributes_json=_jsonable(entity.attributes),
        original_primitives_json=[_primitive(primitive) for primitive in entity.original_primitives],
        normalized_primitives_json=[_primitive(primitive) for primitive in entity.normalized_primitives],
        sampled_geometry_json=_jsonable(entity.sampled_geometry),
        sampled_wkt=_linestring_z(entity.sampled_geometry),
        source_handles=list(entity.source_handles),
        method=entity.method,
        configuration_hash=entity.configuration_hash,
        confidence=entity.confidence,
    )


def _station(project_id: int, station: StationRecord) -> Station:
    return Station(
        station_id=station.station_id,
        project_id=project_id,
        sequence_index=station.sequence_index,
        bbox_json=_bbox(station.bbox),
        source_handles=list(station.source_handles),
        method=station.method,
        configuration_hash=station.configuration_hash,
        confidence=station.confidence,
        evidence_json=_jsonable(station.evidence),
    )


def _profile(project_id: int, profile: ProfileRecord) -> Profile:
    return Profile(
        profile_id=profile.profile_id,
        project_id=project_id,
        station_id=profile.station_id,
        source_handles=list(profile.source_handles),
        method=profile.method,
        configuration_hash=profile.configuration_hash,
        confidence=profile.confidence,
        features_json=_jsonable(profile.features),
    )


def _roller_occurrence(project_id: int, occurrence: RollerOccurrenceRecord) -> RollerOccurrence:
    return RollerOccurrence(
        occurrence_id=occurrence.occurrence_id,
        project_id=project_id,
        station_id=occurrence.station_id,
        role=occurrence.role,
        source_handles=list(occurrence.source_handles),
        method=occurrence.method,
        configuration_hash=occurrence.configuration_hash,
        confidence=occurrence.confidence,
        evidence_json=_jsonable(occurrence.evidence),
    )


def _warning(project_id: int, warning: WarningRecord) -> ExtractionWarning:
    return ExtractionWarning(
        project_id=project_id,
        code=warning.code,
        message=warning.message,
        source_handles=list(warning.source_handles),
        method=warning.method,
        configuration_hash=warning.configuration_hash,
        confidence=warning.confidence,
    )


def _add_provenance(
    session: Session,
    project_id: int,
    result_table: str,
    result_key: str,
    field_name: str | None,
    record: Any,
) -> None:
    session.add(
        ResultProvenance(
            project_id=project_id,
            result_table=result_table,
            result_key=result_key,
            field_name=field_name,
            source_handles=list(record.source_handles),
            method=record.method,
            configuration_hash=record.configuration_hash,
            confidence=record.confidence,
            warning=None,
        )
    )


def _primitive(primitive: CadPrimitive) -> dict[str, Any]:
    return {
        "kind": primitive.kind,
        "attributes": _jsonable(primitive.attributes),
        "source_handle": primitive.source_handle,
    }


def _bbox(bbox: Any) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {"min_x": bbox.min_x, "min_y": bbox.min_y, "max_x": bbox.max_x, "max_y": bbox.max_y}


def _jsonable(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _linestring_z(points: Sequence[tuple[float, float, float]]) -> str | None:
    if not points:
        return None
    coordinates = ", ".join(f"{_fmt(x)} {_fmt(y)} {_fmt(z)}" for x, y, z in points)
    return f"LINESTRING Z ({coordinates})"


def _fmt(value: float) -> str:
    return f"{value:g}"
