from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from rollform_extractor.models import (
    CadEntityRecord,
    CadPrimitive,
    ProfileRecord,
    RollerOccurrenceRecord,
    StageResult,
    StationTransitionRecord,
    StationRecord,
    WarningRecord,
)
from rollform_extractor.pass_features import FeatureKey, PassFeatureSet
from rollform_extractor.transition_analysis import bend_change_events, profile_step_changes, segment_change_events


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
    assemblies: tuple[Any, ...] = ()
    transitions: tuple[StationTransitionRecord, ...] = ()
    composite_flowers: tuple[Any, ...] = ()
    pass_features: Mapping[FeatureKey, PassFeatureSet] = field(default_factory=dict)
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
    __table_args__ = (UniqueConstraint("project_id", "station_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str] = mapped_column(String)
    sequence_index: Mapped[int | None] = mapped_column(Integer)
    bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    region_type: Mapped[str | None] = mapped_column(String)
    stage_type: Mapped[str | None] = mapped_column(String)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "profile_id"),
        ForeignKeyConstraint(["project_id", "station_id"], ["stations.project_id", "stations.station_id"], ondelete="CASCADE"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    profile_id: Mapped[str] = mapped_column(String)
    station_id: Mapped[str] = mapped_column(String)
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Roller(Base):
    __tablename__ = "rollers"
    __table_args__ = (
        UniqueConstraint("project_id", "roller_id"),
        ForeignKeyConstraint(["project_id", "station_id"], ["stations.project_id", "stations.station_id"], ondelete="SET NULL"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    roller_id: Mapped[str] = mapped_column(String)
    station_id: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Assembly(Base):
    __tablename__ = "assemblies"
    __table_args__ = (
        UniqueConstraint("project_id", "assembly_id"),
        ForeignKeyConstraint(["project_id", "station_id"], ["stations.project_id", "stations.station_id"], ondelete="SET NULL"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assembly_id: Mapped[str] = mapped_column(String)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str | None] = mapped_column(String)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("assembly_templates.template_id"))


class AssemblyMember(Base):
    __tablename__ = "assembly_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assembly_id: Mapped[int] = mapped_column(ForeignKey("assemblies.id", ondelete="CASCADE"))
    roller_id: Mapped[int] = mapped_column(ForeignKey("rollers.id", ondelete="CASCADE"))
    role: Mapped[str | None] = mapped_column(String)


class CadEntity(Base):
    __tablename__ = "cad_entities"
    __table_args__ = (UniqueConstraint("project_id", "handle"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    handle: Mapped[str] = mapped_column(String)
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
    cad_entity_id: Mapped[int | None] = mapped_column(ForeignKey("cad_entities.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)


class Dimension(Base):
    __tablename__ = "dimensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    cad_entity_id: Mapped[int | None] = mapped_column(ForeignKey("cad_entities.id", ondelete="SET NULL"))
    measurement: Mapped[float | None] = mapped_column(Float)


class StationTransition(Base):
    __tablename__ = "station_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    from_station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"))
    to_station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id", ondelete="SET NULL"))
    measurements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CompositeFlower(Base):
    __tablename__ = "composite_flowers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_region_id: Mapped[str] = mapped_column(String)
    pass_count: Mapped[int] = mapped_column(Integer)
    sequence_confidence: Mapped[float | None] = mapped_column(Float)
    confirmed: Mapped[bool] = mapped_column(Integer)
    source_bbox_json: Mapped[dict[str, float] | None] = mapped_column(JSON)


class CompositeFlowerPass(Base):
    __tablename__ = "composite_flower_passes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    inferred_order: Mapped[int] = mapped_column(Integer)
    confirmed_order: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[str] = mapped_column(String)
    profile_type: Mapped[str] = mapped_column(String)
    developed_length: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    bend_count: Mapped[int] = mapped_column(Integer)
    total_bend_angle: Mapped[float] = mapped_column(Float)
    raw_geometry_corner_count: Mapped[int | None] = mapped_column(Integer)
    raw_total_turning_angle: Mapped[float | None] = mapped_column(Float)
    physical_forming_bend_count: Mapped[int | None] = mapped_column(Integer)
    physical_total_bend_angle: Mapped[float | None] = mapped_column(Float)
    active_bend_count: Mapped[int | None] = mapped_column(Integer)
    bend_signature: Mapped[str | None] = mapped_column(String)
    vertex_turn_count: Mapped[int | None] = mapped_column(Integer)
    neutral_line_developed_length: Mapped[float | None] = mapped_column(Float)
    expected_neutral_length: Mapped[float | None] = mapped_column(Float)
    neutral_length_error: Mapped[float | None] = mapped_column(Float)
    neutral_length_error_percent: Mapped[float | None] = mapped_column(Float)
    sheet_thickness: Mapped[float | None] = mapped_column(Float)
    thickness_method: Mapped[str | None] = mapped_column(String)
    thickness_sampling_count: Mapped[int | None] = mapped_column(Integer)
    thickness_variation: Mapped[float | None] = mapped_column(Float)
    thickness_confidence: Mapped[float | None] = mapped_column(Float)
    engineer_confirmed_thickness: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Integer)


class PassFeatureSetRow(Base):
    __tablename__ = "pass_feature_sets"
    __table_args__ = (UniqueConstraint("project_id", "composite_flower_id", "composite_pass_id", "schema_version", "configuration_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    composite_pass_record_id: Mapped[int] = mapped_column(ForeignKey("composite_flower_passes.id", ondelete="CASCADE"))
    composite_flower_id: Mapped[str] = mapped_column(String)
    composite_pass_id: Mapped[str] = mapped_column(String)
    pass_identifier: Mapped[str] = mapped_column(String)
    schema_version: Mapped[int] = mapped_column(Integer)
    configuration_hash: Mapped[str] = mapped_column(String)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scalar_vector_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    shape_vector_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    full_vector_json: Mapped[list[float]] = mapped_column(JSON, default=list)
    scalar_field_names_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    shape_field_names_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_mask_json: Mapped[list[bool]] = mapped_column(JSON, default=list)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    physical_fingerprint_hash: Mapped[str] = mapped_column(String)
    shape_fingerprint_hash: Mapped[str] = mapped_column(String)
    combined_fingerprint_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PassSegment(Base):
    __tablename__ = "pass_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_set_id: Mapped[int] = mapped_column(ForeignKey("pass_feature_sets.id", ondelete="CASCADE"))
    segment_id: Mapped[str] = mapped_column(String)
    segment_index: Mapped[int] = mapped_column(Integer)
    segment_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CompositePassEntity(Base):
    __tablename__ = "composite_pass_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pass_id: Mapped[int] = mapped_column(ForeignKey("composite_flower_passes.id", ondelete="CASCADE"))
    cad_entity_id: Mapped[int | None] = mapped_column(ForeignKey("cad_entities.id", ondelete="SET NULL"))
    entity_handle: Mapped[str] = mapped_column(String)
    source_layer: Mapped[str | None] = mapped_column(String)
    sequence_in_contour: Mapped[int] = mapped_column(Integer)


class CompositePassDuplicate(Base):
    __tablename__ = "composite_pass_duplicates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_pass_id: Mapped[int] = mapped_column(ForeignKey("composite_flower_passes.id", ondelete="CASCADE"))
    duplicate_pass_id: Mapped[int] = mapped_column(ForeignKey("composite_flower_passes.id", ondelete="CASCADE"))
    similarity_score: Mapped[float] = mapped_column(Float)
    duplicate_type: Mapped[str] = mapped_column(String)


class CompositePassProfileLink(Base):
    __tablename__ = "composite_pass_profile_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_pass_id: Mapped[int] = mapped_column(ForeignKey("composite_flower_passes.id", ondelete="CASCADE"))
    individual_profile_id: Mapped[str] = mapped_column(String)
    similarity_score: Mapped[float] = mapped_column(Float)
    exact_match: Mapped[bool] = mapped_column(Integer)
    mirrored_match: Mapped[bool] = mapped_column(Integer)
    geometric_difference: Mapped[float] = mapped_column(Float)
    confirmed_link: Mapped[bool] = mapped_column(Integer)


class FlowerBendProgression(Base):
    __tablename__ = "flower_bend_progression"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    bend_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str] = mapped_column(String)
    pass_order: Mapped[int] = mapped_column(Integer)
    developed_position: Mapped[float | None] = mapped_column(Float)
    signed_angle: Mapped[float | None] = mapped_column(Float)
    radius: Mapped[float | None] = mapped_column(Float)
    activation_status: Mapped[str] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    engineer_confirmed: Mapped[bool] = mapped_column(Integer)


class CompositeStationLink(Base):
    __tablename__ = "composite_station_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    composite_pass_id: Mapped[str] = mapped_column(String)
    individual_profile_id: Mapped[str | None] = mapped_column(String)
    sequence_id: Mapped[str | None] = mapped_column(String)
    drawing_stage_id: Mapped[str | None] = mapped_column(String)
    inferred_station_order: Mapped[int | None] = mapped_column(Integer)
    similarity_score: Mapped[float | None] = mapped_column(Float)
    contour_difference: Mapped[float | None] = mapped_column(Float)
    bend_signature_difference: Mapped[float | None] = mapped_column(Float)
    developed_length_difference: Mapped[float | None] = mapped_column(Float)
    link_status: Mapped[str] = mapped_column(String)
    engineer_confirmed: Mapped[bool] = mapped_column(Integer)


class ProfileStepChange(Base):
    __tablename__ = "profile_step_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    from_pass_id: Mapped[str] = mapped_column(String)
    to_pass_id: Mapped[str] = mapped_column(String)
    measurements_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    classifications_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    engineer_confirmed: Mapped[bool] = mapped_column(Integer)


class BendChangeEvent(Base):
    __tablename__ = "bend_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    from_pass_id: Mapped[str] = mapped_column(String)
    to_pass_id: Mapped[str] = mapped_column(String)
    bend_id: Mapped[str] = mapped_column(String)
    change_classification: Mapped[str] = mapped_column(String)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    engineer_confirmed: Mapped[bool] = mapped_column(Integer)


class SegmentChangeEvent(Base):
    __tablename__ = "segment_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    composite_flower_id: Mapped[int] = mapped_column(ForeignKey("composite_flowers.id", ondelete="CASCADE"))
    from_pass_id: Mapped[str] = mapped_column(String)
    to_pass_id: Mapped[str] = mapped_column(String)
    segment_index: Mapped[int] = mapped_column(Integer)
    change_classification: Mapped[str] = mapped_column(String)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    engineer_confirmed: Mapped[bool] = mapped_column(Integer)


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
    __table_args__ = (
        UniqueConstraint("project_id", "occurrence_id"),
        ForeignKeyConstraint(["project_id", "station_id"], ["stations.project_id", "stations.station_id"], ondelete="CASCADE"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    station_id: Mapped[str] = mapped_column(String)
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
    assembly_id: Mapped[int | None] = mapped_column(ForeignKey("assemblies.id", ondelete="SET NULL"))
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("roller_occurrences.id", ondelete="SET NULL"))


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
    source_handles: Mapped[list[str]] = mapped_column(JSON, default=list)
    method: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
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


class RollerDesign(Base):
    __tablename__ = "roller_designs"

    design_id: Mapped[str] = mapped_column(String, primary_key=True)
    legacy_catalog_id: Mapped[int | None] = mapped_column(ForeignKey("roller_catalog.roller_catalog_id", ondelete="SET NULL"), unique=True)
    name: Mapped[str | None] = mapped_column(String)
    design_type: Mapped[str | None] = mapped_column(String)
    manufacturer: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="CANDIDATE")
    verified: Mapped[bool] = mapped_column(Integer, default=0)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerLocation(Base):
    __tablename__ = "roller_locations"

    location_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    location_type: Mapped[str | None] = mapped_column(String)
    parent_location_id: Mapped[str | None] = mapped_column(ForeignKey("roller_locations.location_id", ondelete="SET NULL"))
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerAsset(Base):
    __tablename__ = "roller_assets"
    __table_args__ = (UniqueConstraint("asset_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[str] = mapped_column(String)
    design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    serial_number: Mapped[str | None] = mapped_column(String)
    condition: Mapped[str | None] = mapped_column(String)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("roller_locations.location_id", ondelete="SET NULL"))
    verified: Mapped[bool] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerGeometryRevision(Base):
    __tablename__ = "roller_geometry_revisions"
    __table_args__ = (UniqueConstraint("revision_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision_id: Mapped[str] = mapped_column(String)
    design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("roller_assets.id", ondelete="SET NULL"))
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unit_status: Mapped[str] = mapped_column(String, default="UNKNOWN")
    measurement_method: Mapped[str | None] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    verification_status: Mapped[str] = mapped_column(String, default="UNVERIFIED")
    input_file_hash: Mapped[str | None] = mapped_column(String)
    algorithm_version: Mapped[str | None] = mapped_column(String)
    configuration_hash: Mapped[str | None] = mapped_column(String)
    physical_fingerprint: Mapped[str | None] = mapped_column(String)
    shape_fingerprint: Mapped[str | None] = mapped_column(String)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerAlias(Base):
    __tablename__ = "roller_aliases"
    __table_args__ = (UniqueConstraint("normalized_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String)
    normalized_alias: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(String)
    verified: Mapped[bool] = mapped_column(Integer, default=0)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerCompatibility(Base):
    __tablename__ = "roller_compatibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="CASCADE"))
    compatible_design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="CANDIDATE")
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(Integer, default=0)


class RollerConditionHistory(Base):
    __tablename__ = "roller_condition_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("roller_assets.id", ondelete="CASCADE"))
    condition: Mapped[str] = mapped_column(String)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerRegrindHistory(Base):
    __tablename__ = "roller_regrind_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("roller_assets.id", ondelete="CASCADE"))
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    amount_removed: Mapped[float | None] = mapped_column(Float)
    amount_unit: Mapped[str | None] = mapped_column(String)
    resulting_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    source: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerFileAsset(Base):
    __tablename__ = "roller_file_assets"
    __table_args__ = (UniqueConstraint("sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String)
    relative_path: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String)
    content_type: Mapped[str | None] = mapped_column(String)
    design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("roller_assets.id", ondelete="SET NULL"))
    revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    source: Mapped[str | None] = mapped_column(String)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerImportBatch(Base):
    __tablename__ = "roller_import_batches"
    __table_args__ = (UniqueConstraint("source_sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String)
    source_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="STAGED")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerImportRow(Base):
    __tablename__ = "roller_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("roller_import_batches.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)
    original_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class RollerReviewDecision(Base):
    __tablename__ = "roller_review_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("roller_import_batches.id", ondelete="CASCADE"))
    row_id: Mapped[int] = mapped_column(ForeignKey("roller_import_rows.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerAuditEvent(Base):
    __tablename__ = "roller_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String)
    entity_key: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    actor: Mapped[str | None] = mapped_column(String)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerRecognitionRun(Base):
    __tablename__ = "roller_recognition_runs"
    __table_args__ = (UniqueConstraint("project_id", "run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_key: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String)
    feature_schema_version: Mapped[int] = mapped_column(Integer)
    configuration_hash: Mapped[str] = mapped_column(String)
    inventory_snapshot_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="COMPLETED")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerRecognitionInput(Base):
    __tablename__ = "roller_recognition_inputs"
    __table_args__ = (UniqueConstraint("run_id", "occurrence_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("roller_recognition_runs.id", ondelete="CASCADE"))
    occurrence_id: Mapped[str] = mapped_column(String)
    station_id: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scalar_vector_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    shape_vector_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    missing_mask_json: Mapped[list[bool]] = mapped_column(JSON, default=list)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    physical_fingerprint: Mapped[str | None] = mapped_column(String)
    shape_fingerprint: Mapped[str | None] = mapped_column(String)
    source_handles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_hash: Mapped[str] = mapped_column(String)


class RollerRecognitionCandidate(Base):
    __tablename__ = "roller_recognition_candidates"
    __table_args__ = (UniqueConstraint("run_id", "input_id", "design_id", "geometry_revision_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("roller_recognition_runs.id", ondelete="CASCADE"))
    input_id: Mapped[int] = mapped_column(ForeignKey("roller_recognition_inputs.id", ondelete="CASCADE"))
    design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="CASCADE"))
    geometry_revision_id: Mapped[str] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    overall_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_coverage: Mapped[float] = mapped_column(Float)
    candidate_status: Mapped[str] = mapped_column(String)
    component_scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hard_filter_results_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)


class RollerRecognitionReview(Base):
    __tablename__ = "roller_recognition_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("roller_recognition_candidates.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String)
    selected_design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    selected_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    reviewer: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    supersedes_review_id: Mapped[int | None] = mapped_column(ForeignKey("roller_recognition_reviews.id", ondelete="SET NULL"))


class RollerRecognitionLabel(Base):
    __tablename__ = "roller_recognition_labels"
    __table_args__ = (UniqueConstraint("occurrence_id", "expected_design_id", "label_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String)
    expected_design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="CASCADE"))
    expected_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    label_source: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    notes: Mapped[str | None] = mapped_column(Text)


class RollerRecognitionMetric(Base):
    __tablename__ = "roller_recognition_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("roller_recognition_runs.id", ondelete="CASCADE"))
    evaluation_set_hash: Mapped[str] = mapped_column(String)
    metric_name: Mapped[str] = mapped_column(String)
    metric_value: Mapped[float] = mapped_column(Float)
    breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RecognitionEvaluationDataset(Base):
    __tablename__ = "recognition_evaluation_datasets"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    locked_by: Mapped[str | None] = mapped_column(String)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[str | None] = mapped_column(String)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    content_hash: Mapped[str | None] = mapped_column(String)
    inventory_snapshot_hash: Mapped[str | None] = mapped_column(String)
    recognition_algorithm_version: Mapped[str | None] = mapped_column(String)
    feature_schema_version: Mapped[int | None] = mapped_column(Integer)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    project_count: Mapped[int] = mapped_column(Integer, default=0)
    design_count: Mapped[int] = mapped_column(Integer, default=0)
    split_strategy: Mapped[str | None] = mapped_column(String)
    source_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class RecognitionEvaluationCase(Base):
    __tablename__ = "recognition_evaluation_cases"
    __table_args__ = (UniqueConstraint("dataset_id", "project_id", "occurrence_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_datasets.id", ondelete="CASCADE"))
    case_key: Mapped[str] = mapped_column(String)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    occurrence_id: Mapped[str] = mapped_column(String)
    recognition_input_id: Mapped[int | None] = mapped_column(ForeignKey("roller_recognition_inputs.id", ondelete="SET NULL"))
    recognition_input_hash: Mapped[str | None] = mapped_column(String)
    inventory_snapshot_hash: Mapped[str | None] = mapped_column(String)
    split: Mapped[str] = mapped_column(String, default="CALIBRATION")
    case_status: Mapped[str] = mapped_column(String, default="OPEN")
    gold_outcome: Mapped[str | None] = mapped_column(String)
    expected_design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    expected_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_handles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RecognitionLabelAssertion(Base):
    __tablename__ = "recognition_label_assertions"
    __table_args__ = (UniqueConstraint("case_id", "reviewer", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_cases.id", ondelete="CASCADE"))
    reviewer: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    expected_design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    expected_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    confidence: Mapped[float | None] = mapped_column(Float)
    reason_code: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    supersedes_assertion_id: Mapped[int | None] = mapped_column(ForeignKey("recognition_label_assertions.id", ondelete="SET NULL"))


class RecognitionAdjudication(Base):
    __tablename__ = "recognition_adjudications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_cases.id", ondelete="CASCADE"))
    adjudicator: Mapped[str] = mapped_column(String)
    final_outcome: Mapped[str] = mapped_column(String)
    selected_design_id: Mapped[str | None] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="SET NULL"))
    selected_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    reason_code: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    supersedes_adjudication_id: Mapped[int | None] = mapped_column(ForeignKey("recognition_adjudications.id", ondelete="SET NULL"))


class RecognitionThresholdProfile(Base):
    __tablename__ = "recognition_threshold_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String)
    feature_schema_version: Mapped[int] = mapped_column(Integer)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String)
    calibration_dataset_hash: Mapped[str | None] = mapped_column(String)
    validation_dataset_hash: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    metric_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    approved_by: Mapped[str | None] = mapped_column(String)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approval_notes: Mapped[str | None] = mapped_column(Text)
    supersedes_profile_id: Mapped[str | None] = mapped_column(ForeignKey("recognition_threshold_profiles.profile_id", ondelete="SET NULL"))


class RecognitionThresholdEvaluation(Base):
    __tablename__ = "recognition_threshold_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_datasets.id", ondelete="CASCADE"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("recognition_threshold_profiles.id", ondelete="SET NULL"))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ConfirmedRollerDesignUsage(Base):
    __tablename__ = "confirmed_roller_design_usages"
    __table_args__ = (UniqueConstraint("project_id", "occurrence_id", "recognition_input_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_id: Mapped[str] = mapped_column(String, unique=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    occurrence_id: Mapped[str] = mapped_column(String)
    recognition_input_hash: Mapped[str] = mapped_column(String)
    design_id: Mapped[str] = mapped_column(ForeignKey("roller_designs.design_id", ondelete="RESTRICT"))
    geometry_revision_id: Mapped[str | None] = mapped_column(ForeignKey("roller_geometry_revisions.revision_id", ondelete="SET NULL"))
    station_id: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    assembly_id: Mapped[str | None] = mapped_column(String)
    profile_context: Mapped[str | None] = mapped_column(String)
    source_adjudication_id: Mapped[int] = mapped_column(ForeignKey("recognition_adjudications.id", ondelete="RESTRICT"))
    source_dataset_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_datasets.id", ondelete="RESTRICT"))
    source_dataset_hash: Mapped[str] = mapped_column(String)
    inventory_snapshot_hash: Mapped[str | None] = mapped_column(String)
    confirmation_status: Mapped[str] = mapped_column(String, default="CONFIRMED")
    confirmed_by: Mapped[str] = mapped_column(String)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_handles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    supersedes_usage_id: Mapped[str | None] = mapped_column(ForeignKey("confirmed_roller_design_usages.usage_id", ondelete="SET NULL"))
    stale_reason: Mapped[str | None] = mapped_column(Text)


class RollerUsagePromotion(Base):
    __tablename__ = "roller_usage_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("recognition_evaluation_cases.id", ondelete="CASCADE"))
    usage_id: Mapped[str | None] = mapped_column(ForeignKey("confirmed_roller_design_usages.usage_id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String)
    promoted_by: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RollerUsageRelationshipSnapshot(Base):
    __tablename__ = "roller_usage_relationship_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String, unique=True)
    algorithm_version: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    dataset_scope: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollerUsageRelationship(Base):
    __tablename__ = "roller_usage_relationships"
    __table_args__ = (UniqueConstraint("snapshot_id", "relationship_type", "source_entity", "target_entity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("roller_usage_relationship_snapshots.id", ondelete="CASCADE"))
    relationship_type: Mapped[str] = mapped_column(String)
    source_entity: Mapped[str] = mapped_column(String)
    target_entity: Mapped[str] = mapped_column(String)
    confirmed_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_project_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_assembly_count: Mapped[int] = mapped_column(Integer, default=0)
    support: Mapped[float] = mapped_column(Float, default=0.0)
    reliability_descriptor: Mapped[str] = mapped_column(String, default="DESCRIPTIVE_ONLY")
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    dataset_scope: Mapped[str] = mapped_column(String)
    supporting_usage_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    limitations_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class FlowerPrototypeDatasetRow(Base):
    __tablename__ = "flower_prototype_datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_hash: Mapped[str] = mapped_column(String)
    schema_version: Mapped[int] = mapped_column(Integer)
    algorithm_version: Mapped[str] = mapped_column(String)
    source_classification: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FlowerPrototypeSourceRow(Base):
    __tablename__ = "flower_prototype_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("flower_prototype_datasets.dataset_id", ondelete="CASCADE"))
    source_id: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String)
    source_classification: Mapped[str] = mapped_column(String)
    raw_profile_count: Mapped[int] = mapped_column(Integer)
    entity_count: Mapped[int] = mapped_column(Integer)
    association_status: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class HistoricalFlowerRow(Base):
    __tablename__ = "historical_flowers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("flower_prototype_datasets.dataset_id", ondelete="CASCADE"))
    flower_id: Mapped[str] = mapped_column(String)
    source_sha256: Mapped[str] = mapped_column(String)
    topology: Mapped[str] = mapped_column(String)
    pass_count: Mapped[int] = mapped_column(Integer)
    quality_flags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("dataset_id", "flower_id"),)


class HistoricalFlowerPassRow(Base):
    __tablename__ = "historical_flower_passes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String)
    flower_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str] = mapped_column(String)
    source_handle: Mapped[str] = mapped_column(String)
    inferred_order: Mapped[int] = mapped_column(Integer)
    geometry_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("dataset_id", "flower_id", "pass_id"),)


class HistoricalPassTransitionRow(Base):
    __tablename__ = "historical_pass_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String)
    flower_id: Mapped[str] = mapped_column(String)
    from_pass_id: Mapped[str] = mapped_column(String)
    to_pass_id: Mapped[str] = mapped_column(String)
    transition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class HistoricalRollerStationEvidenceRow(Base):
    """Optional station-level design evidence for the v2 flower dataset."""
    __tablename__ = "historical_roller_station_evidence"
    __table_args__ = (UniqueConstraint("dataset_id", "flower_id", "pass_id", "role", "design_id", "geometry_revision_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String)
    flower_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    design_id: Mapped[str] = mapped_column(String)
    geometry_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class HistoricalBendProgressionRow(Base):
    __tablename__ = "historical_bend_progressions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String)
    flower_id: Mapped[str] = mapped_column(String)
    bend_key: Mapped[str] = mapped_column(String)
    progression_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FlowerGenerationRunRow(Base):
    __tablename__ = "flower_generation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_id: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FlowerGenerationInputRow(Base):
    __tablename__ = "flower_generation_inputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String)
    input_hash: Mapped[str] = mapped_column(String)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FlowerGenerationCandidateRow(Base):
    __tablename__ = "flower_generation_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String)
    candidate_id: Mapped[str] = mapped_column(String)
    candidate_type: Mapped[str] = mapped_column(String)
    station_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FlowerGenerationPassRow(Base):
    __tablename__ = "flower_generation_passes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str] = mapped_column(String)
    inferred_order: Mapped[int] = mapped_column(Integer)
    pass_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FlowerGenerationProvenanceRow(Base):
    __tablename__ = "flower_generation_provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str | None] = mapped_column(String)
    source_flower_id: Mapped[str | None] = mapped_column(String)
    source_pass_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    transformation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FlowerGenerationValidationRow(Base):
    __tablename__ = "flower_generation_validations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class FlowerGenerationReviewRow(Base):
    __tablename__ = "flower_generation_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FlowerReconstructionBenchmarkRow(Base):
    __tablename__ = "flower_reconstruction_benchmarks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class FlowerReconstructionMetricRow(Base):
    __tablename__ = "flower_reconstruction_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_id: Mapped[str] = mapped_column(String)
    flower_id: Mapped[str] = mapped_column(String)
    pass_id: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def create_project_database(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    _upgrade_schema(engine)
    return engine


def _upgrade_schema(engine: Engine) -> None:
    composite_pass_columns = {
        "raw_geometry_corner_count": "INTEGER",
        "raw_total_turning_angle": "FLOAT",
        "physical_forming_bend_count": "INTEGER",
        "physical_total_bend_angle": "FLOAT",
        "active_bend_count": "INTEGER",
        "bend_signature": "VARCHAR",
        "vertex_turn_count": "INTEGER",
        "neutral_line_developed_length": "FLOAT",
        "expected_neutral_length": "FLOAT",
        "neutral_length_error": "FLOAT",
        "neutral_length_error_percent": "FLOAT",
        "sheet_thickness": "FLOAT",
        "thickness_method": "VARCHAR",
        "thickness_sampling_count": "INTEGER",
        "thickness_variation": "FLOAT",
        "thickness_confidence": "FLOAT",
        "engineer_confirmed_thickness": "FLOAT",
    }
    with engine.begin() as connection:
        table_names = {row[0] for row in connection.exec_driver_sql("select name from sqlite_master where type='table'")}
        if "composite_flower_passes" in table_names:
            existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(composite_flower_passes)")}
            for name, sql_type in composite_pass_columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE composite_flower_passes ADD COLUMN {name} {sql_type}")
        if "visual_flower_roller_evidence_reviews" in table_names:
            existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(visual_flower_roller_evidence_reviews)")}
            for name, sql_type in {
                "selected_source_reference_id": "VARCHAR",
                "selected_source_flower_id": "VARCHAR",
                "selected_source_pass_id": "VARCHAR",
                "selected_source_match_rank": "INTEGER",
            }.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE visual_flower_roller_evidence_reviews ADD COLUMN {name} {sql_type}")
    _migrate_legacy_roller_catalog(engine)


def _migrate_legacy_roller_catalog(engine: Engine) -> None:
    """Expose legacy catalog rows as design identities without changing old references."""
    with Session(engine) as session, session.begin():
        if session.scalar(select(RollerDesign.design_id).limit(1)) is not None:
            return
        for row in session.scalars(select(RollerCatalog).order_by(RollerCatalog.roller_catalog_id)):
            design_id = f"LEGACY-{row.roller_catalog_id}"
            session.add(
                RollerDesign(
                    design_id=design_id,
                    legacy_catalog_id=row.roller_catalog_id,
                    name=row.factory_id or design_id,
                    design_type="LEGACY_CATALOG",
                    manufacturer=None,
                    status="CANDIDATE",
                    verified=0,
                    provenance_json={"source": "roller_catalog", "roller_catalog_id": row.roller_catalog_id},
                )
            )


def persist_extraction(engine: Engine, bundle: ExtractionBundle) -> int:
    project_id, run_id = _record_run_header(engine, bundle)
    try:
        with Session(engine) as session, session.begin():
            _clear_current_project_results(session, project_id)
            for layer in sorted({entity.layer for entity in bundle.entities}):
                session.add(Layer(project_id=project_id, name=layer))
            for entity in bundle.entities:
                session.add(_cad_entity(project_id, entity))
                _add_provenance(session, project_id, "cad_entities", entity.handle, None, entity)
            for station in bundle.stations:
                session.add(_station(project_id, station))
                _add_provenance(session, project_id, "stations", station.station_id, None, station)
            session.flush()
            for profile in bundle.profiles:
                session.add(_profile(project_id, profile))
                _add_provenance(session, project_id, "profiles", profile.profile_id, None, profile)
            for occurrence in bundle.roller_occurrences:
                session.add(_roller_occurrence(project_id, occurrence))
                _add_provenance(session, project_id, "roller_occurrences", occurrence.occurrence_id, None, occurrence)
            session.flush()
            station_rows = {row.station_id: row for row in session.scalars(select(Station).where(Station.project_id == project_id))}
            for assembly in bundle.assemblies:
                session.add(_assembly(project_id, assembly))
            for transition in bundle.transitions:
                from_row = station_rows.get(transition.from_station_id)
                to_row = station_rows.get(transition.to_station_id)
                if from_row is not None and to_row is not None:
                    session.add(_transition(project_id, transition, from_row.id, to_row.id))
            session.flush()
            entity_rows = {row.handle: row for row in session.scalars(select(CadEntity).where(CadEntity.project_id == project_id))}
            for composite in bundle.composite_flowers:
                _add_composite_flower(session, project_id, composite, entity_rows, bundle.pass_features)
            for warning in bundle.warnings:
                session.add(_warning(project_id, warning))
    except Exception as exc:
        _mark_run_failed(engine, project_id, run_id, exc)
        raise
    return project_id


def _record_run_header(engine: Engine, bundle: ExtractionBundle) -> tuple[int, int]:
    with Session(engine) as session, session.begin():
        project = session.scalar(select(Project).where(Project.drawing_id == bundle.drawing_id))
        if project is None:
            project = Project(drawing_id=bundle.drawing_id, source_path="", source_sha256="")
            session.add(project)
            session.flush()
        project.source_path = str(bundle.source_path)
        project.source_sha256 = bundle.source_sha256
        project.converted_path = str(bundle.converted_path) if bundle.converted_path else None
        project.converted_sha256 = bundle.converted_sha256
        run = ExtractionRun(
            project_id=project.id,
            status=bundle.status,
            configuration_hash=bundle.configuration_hash,
            configuration_snapshot_json=_jsonable(bundle.configuration_snapshot),
        )
        session.add(run)
        session.flush()
        return project.id, run.id


def _clear_current_project_results(session: Session, project_id: int) -> None:
    for model in (
        PassSegment,
        PassFeatureSetRow,
        SegmentChangeEvent,
        BendChangeEvent,
        ProfileStepChange,
        CompositeStationLink,
        FlowerBendProgression,
        CompositePassProfileLink,
        CompositePassDuplicate,
        CompositePassEntity,
        CompositeFlowerPass,
    ):
        session.execute(delete(model))
    session.execute(delete(CompositeFlower).where(CompositeFlower.project_id == project_id))
    for model in (
        ProjectRollUsage,
        RollerOccurrence,
        Profile,
        Roller,
        Assembly,
        CadEntity,
        Station,
        Layer,
        GeometryFingerprint,
        ResultProvenance,
        ExtractionWarning,
    ):
        session.execute(delete(model).where(model.project_id == project_id))


def _mark_run_failed(engine: Engine, project_id: int, run_id: int, exc: Exception) -> None:
    with Session(engine) as session, session.begin():
        run = session.get(ExtractionRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = _now()
        session.add(
            ExtractionWarning(
                project_id=project_id,
                code="persistence_failed",
                message=str(exc),
                source_handles=[],
                method="persistence",
                configuration_hash=None,
                confidence=1.0,
            )
        )


def record_stage(engine: Engine, project_id: int, result: StageResult) -> None:
    warnings = [{"code": warning.code, "message": warning.message} for warning in result.warnings]
    status = _stage_status(result)
    diagnostics = {"warnings": warnings}
    if result.stage == "feature_extraction":
        diagnostics.update(
            {
                "feature_count": len(result.records),
                "vector_length": len(result.records[0].full_vector.values) if result.records else 0,
                "quality_warnings": sorted({flag for record in result.records for flag in getattr(record.quality, "flags", ())}),
            }
        )
    with Session(engine) as session, session.begin():
        session.add(
            ProcessingStage(
                project_id=project_id,
                stage=result.stage,
                status=status,
                input_hash=None,
                source_handles=list(result.source_handles),
                method=result.method,
                configuration_hash=result.configuration_hash,
                confidence=result.confidence,
                software_version=None,
                artifact_hashes_json={},
                diagnostics_json=diagnostics,
            )
        )


def _stage_status(result: StageResult) -> str:
    explicit = getattr(result, "status", None)
    if explicit:
        return explicit
    if result.confidence <= 0:
        return "failed"
    if any(_is_error_warning(warning) for warning in result.warnings):
        return "failed"
    return "success"


def _is_error_warning(warning: WarningRecord) -> bool:
    code = warning.code.lower()
    return "failed" in code or "error" in code or "exception" in code


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
        region_type=str(station.evidence.get("region_type") or station.evidence.get("stage_type") or "UNKNOWN"),
        stage_type=str(station.evidence.get("stage_type") or station.evidence.get("region_type") or "UNKNOWN"),
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


def _assembly(project_id: int, assembly: Any) -> Assembly:
    return Assembly(
        assembly_id=assembly.assembly_id,
        project_id=project_id,
        station_id=assembly.station_id,
        template_id=None,
    )


def _transition(project_id: int, transition: StationTransitionRecord, from_station_pk: int, to_station_pk: int) -> StationTransition:
    return StationTransition(
        project_id=project_id,
        from_station_id=from_station_pk,
        to_station_id=to_station_pk,
        measurements_json=_jsonable(
            {
                **dict(transition.measurements),
                "sequence_id": transition.sequence_id,
                "source_handles": transition.source_handles,
                "method": transition.method,
                "confidence": transition.confidence,
            }
        ),
    )


def _add_composite_flower(session: Session, project_id: int, composite: Any, entity_rows: dict[str, CadEntity], pass_features: Mapping[FeatureKey, PassFeatureSet] | None = None) -> None:
    row = CompositeFlower(
        project_id=project_id,
        source_region_id=composite.source_region_id,
        pass_count=composite.pass_count,
        sequence_confidence=composite.sequence_confidence,
        confirmed=bool(composite.confirmed),
        source_bbox_json=_bbox(composite.source_bbox),
    )
    session.add(row)
    session.flush()
    pass_rows: dict[str, CompositeFlowerPass] = {}
    pass_rows_by_id: dict[str, CompositeFlowerPass] = {}
    for item in composite.passes:
        pass_row = CompositeFlowerPass(
            composite_flower_id=row.id,
            inferred_order=item.inferred_order,
            confirmed_order=item.confirmed_order,
            profile_id=item.profile_id,
            profile_type=item.profile_type,
            developed_length=item.developed_length,
            width=item.width,
            height=item.height,
            bend_count=item.bend_count,
            total_bend_angle=item.total_bend_angle,
            raw_geometry_corner_count=item.raw_geometry_corner_count,
            raw_total_turning_angle=item.raw_total_turning_angle,
            physical_forming_bend_count=item.physical_forming_bend_count,
            physical_total_bend_angle=item.physical_total_bend_angle,
            active_bend_count=item.active_bend_count,
            bend_signature=item.bend_signature,
            vertex_turn_count=item.vertex_turn_count,
            neutral_line_developed_length=item.neutral_line_developed_length,
            expected_neutral_length=item.expected_neutral_length,
            neutral_length_error=item.neutral_length_error,
            neutral_length_error_percent=item.neutral_length_error_percent,
            sheet_thickness=item.sheet_thickness,
            thickness_method=item.thickness_method,
            thickness_sampling_count=item.thickness_sampling_count,
            thickness_variation=item.thickness_variation,
            thickness_confidence=item.thickness_confidence,
            engineer_confirmed_thickness=item.engineer_confirmed_thickness,
            confidence=item.confidence,
            requires_review=bool(item.requires_review),
        )
        session.add(pass_row)
        session.flush()
        pass_rows[item.profile_id] = pass_row
        pass_rows_by_id[item.pass_id] = pass_row
        for sequence, handle in enumerate(item.source_handles):
            entity = entity_rows.get(handle)
            session.add(
                CompositePassEntity(
                    pass_id=pass_row.id,
                    cad_entity_id=entity.id if entity is not None else None,
                    entity_handle=handle,
                    source_layer=(entity.layer if entity is not None else None),
                    sequence_in_contour=sequence,
                )
            )
        for match in item.individual_profile_matches:
            session.add(
                CompositePassProfileLink(
                    composite_pass_id=pass_row.id,
                    individual_profile_id=str(match["individual_profile_id"]),
                    similarity_score=float(match["similarity_score"]),
                    exact_match=bool(match["exact_match"]),
                    mirrored_match=bool(match["mirrored_match"]),
                    geometric_difference=float(match["geometric_difference"]),
                    confirmed_link=bool(match["confirmed_link"]),
                )
            )
        first_match = next(iter(item.individual_profile_matches), None)
        session.add(
            CompositeStationLink(
                composite_flower_id=row.id,
                composite_pass_id=item.pass_id,
                individual_profile_id=(str(first_match["individual_profile_id"]) if first_match else None),
                sequence_id=item.composite_flower_id,
                drawing_stage_id=(str(first_match["individual_profile_id"]) if first_match else None),
                inferred_station_order=item.inferred_order if first_match else None,
                similarity_score=(float(first_match["similarity_score"]) if first_match else None),
                contour_difference=(float(first_match["geometric_difference"]) if first_match else None),
                bend_signature_difference=None,
                developed_length_difference=None,
                link_status=("EXACT_CANDIDATE" if first_match and first_match.get("exact_match") else "SIMILAR_CANDIDATE" if first_match else "UNMATCHED"),
                engineer_confirmed=False,
            )
        )
    bend_ids = sorted({str(bend["bend_id"]) for item in composite.passes for bend in item.physical_bends})
    for item in composite.passes:
        bends_by_id = {str(bend["bend_id"]): bend for bend in item.physical_bends}
        for bend_id in bend_ids:
            bend = bends_by_id.get(bend_id, {})
            session.add(
                FlowerBendProgression(
                    composite_flower_id=row.id,
                    bend_id=bend_id,
                    pass_id=item.pass_id,
                    pass_order=item.inferred_order,
                    developed_position=bend.get("developed_length_position"),
                    signed_angle=bend.get("signed_bend_angle", 0.0),
                    radius=bend.get("neutral_line_radius"),
                    activation_status=str(bend.get("activation_status", "inactive")),
                    confidence=bend.get("confidence", 0.0),
                    engineer_confirmed=False,
                )
            )
    for item in composite.passes:
        feature = (pass_features or {}).get((composite.composite_flower_id, item.pass_id))
        pass_row = pass_rows_by_id.get(item.pass_id)
        if feature is None or pass_row is None:
            continue
        feature_row = PassFeatureSetRow(
            project_id=project_id,
            composite_pass_record_id=pass_row.id,
            composite_flower_id=feature.composite_flower_id,
            composite_pass_id=feature.pass_id,
            pass_identifier=feature.pass_id,
            schema_version=feature.schema_version,
            configuration_hash=feature.configuration_hash,
            feature_json=_jsonable(feature.to_dict()),
            scalar_vector_json=list(feature.scalar_vector.values),
            shape_vector_json=list(feature.shape_vector.values),
            full_vector_json=list(feature.full_vector.values),
            scalar_field_names_json=list(feature.scalar_vector.field_names),
            shape_field_names_json=list(feature.shape_vector.field_names),
            missing_mask_json=list(feature.full_vector.missing_mask),
            quality_json=_jsonable(asdict(feature.quality)),
            confidence=feature.quality.confidence,
            physical_fingerprint_hash=feature.fingerprints["physical_fingerprint"],
            shape_fingerprint_hash=feature.fingerprints["shape_fingerprint"],
            combined_fingerprint_hash=feature.fingerprints["combined_fingerprint"],
        )
        session.add(feature_row)
        session.flush()
        for segment in feature.segments:
            session.add(PassSegment(feature_set_id=feature_row.id, segment_id=segment.segment_id, segment_index=segment.segment_index, segment_json=_jsonable(asdict(segment))))
        for name, digest in feature.fingerprints.items():
            session.add(GeometryFingerprint(project_id=project_id, owner_table="pass_feature_sets", owner_key=f"{feature.composite_flower_id}:{feature.pass_id}:{name}", fingerprint_hash=digest, fingerprint_json={"schema_version": feature.schema_version, "composite_flower_id": feature.composite_flower_id, "pass_id": feature.pass_id, "kind": name}))
        session.add(ResultProvenance(project_id=project_id, result_table="pass_feature_sets", result_key=f"{feature.composite_flower_id}:{feature.pass_id}", field_name=None, source_handles=list(feature.source_handles), method=feature.provenance.calculation_method, configuration_hash=feature.configuration_hash, confidence=feature.quality.confidence, warning=";".join(feature.quality.flags) or None))
    for change in profile_step_changes(composite.passes):
        session.add(
            ProfileStepChange(
                composite_flower_id=row.id,
                from_pass_id=str(change["from_pass_id"]),
                to_pass_id=str(change["to_pass_id"]),
                measurements_json=_jsonable(change),
                classifications_json=list(change.get("classifications", ())),
                confidence=change.get("confidence"),
                summary=change.get("summary"),
                engineer_confirmed=bool(change.get("engineer_confirmed")),
            )
        )
    for event_row in bend_change_events(composite.passes):
        session.add(
            BendChangeEvent(
                composite_flower_id=row.id,
                from_pass_id=str(event_row["from_pass_id"]),
                to_pass_id=str(event_row["to_pass_id"]),
                bend_id=str(event_row["bend_id"]),
                change_classification=str(event_row["change_classification"]),
                event_json=_jsonable(event_row),
                confidence=event_row.get("confidence"),
                engineer_confirmed=bool(event_row.get("engineer_confirmed")),
            )
        )
    for event_row in segment_change_events(composite.passes):
        session.add(
            SegmentChangeEvent(
                composite_flower_id=row.id,
                from_pass_id=str(event_row["from_pass_id"]),
                to_pass_id=str(event_row["to_pass_id"]),
                segment_index=int(event_row["segment_index"]),
                change_classification=str(event_row["change_classification"]),
                event_json=_jsonable(event_row),
                confidence=event_row.get("confidence"),
                engineer_confirmed=bool(event_row.get("engineer_confirmed")),
            )
        )
    session.flush()
    for item in composite.passes:
        if item.duplicate_of and item.profile_id in pass_rows and item.duplicate_of in pass_rows:
            session.add(
                CompositePassDuplicate(
                    canonical_pass_id=pass_rows[item.duplicate_of].id,
                    duplicate_pass_id=pass_rows[item.profile_id].id,
                    similarity_score=float(item.similarity_score or 0.0),
                    duplicate_type="near_duplicate",
                )
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
    if isinstance(value, CadPrimitive):
        return _primitive(value)
    if hasattr(value, "min_x") and hasattr(value, "min_y") and hasattr(value, "max_x") and hasattr(value, "max_y"):
        return _bbox(value)
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


class VisualProfileTargetRow(Base):
    __tablename__ = "visual_profile_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    schema_version: Mapped[int] = mapped_column(Integer)
    topology: Mapped[str] = mapped_column(String)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class VisualProfileTargetRevisionRow(Base):
    __tablename__ = "visual_profile_target_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("visual_profile_targets.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (UniqueConstraint("target_id", "revision", name="uq_visual_target_revision"),)


class VisualFlowerGenerationRunRow(Base):
    __tablename__ = "visual_flower_generation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("visual_profile_targets.id", ondelete="CASCADE"))
    algorithm_version: Mapped[str] = mapped_column(String)
    dataset_hash: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VisualFlowerCandidateRow(Base):
    __tablename__ = "visual_flower_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String, unique=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_generation_runs.id", ondelete="CASCADE"))
    candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    visual_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VisualFlowerCandidatePassRow(Base):
    __tablename__ = "visual_flower_candidate_passes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_candidates.id", ondelete="CASCADE"))
    pass_id: Mapped[str] = mapped_column(String)
    order_index: Mapped[int] = mapped_column(Integer)
    pass_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("candidate_id", "pass_id", name="uq_visual_candidate_pass"),)


class VisualHistoricalPassMatchRow(Base):
    __tablename__ = "visual_historical_pass_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_pass_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_candidate_passes.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    match_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class VisualConfidenceComponentRow(Base):
    __tablename__ = "visual_confidence_components"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_candidates.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String)
    component_name: Mapped[str] = mapped_column(String)
    score: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str | None] = mapped_column(String)


class VisualFlowerReviewRow(Base):
    __tablename__ = "visual_flower_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_candidates.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VisualFlowerCandidateReviewRow(Base):
    """Append-only engineer feedback with model and target provenance."""
    __tablename__ = "visual_flower_candidate_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, unique=True)
    candidate_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    candidate_type: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    reviewer: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    model_id: Mapped[str | None] = mapped_column(String)
    algorithm_version: Mapped[str | None] = mapped_column(String)
    target_hash: Mapped[str | None] = mapped_column(String)


class VisualFlowerRollerEvidenceBundleRow(Base):
    """Immutable, design-only evidence snapshot for a generated flower."""
    __tablename__ = "visual_flower_roller_evidence_bundles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String, unique=True)
    candidate_id: Mapped[str] = mapped_column(String, index=True)
    algorithm_version: Mapped[str] = mapped_column(String)
    configuration_hash: Mapped[str] = mapped_column(String)
    historical_dataset_hash: Mapped[str] = mapped_column(String)
    inventory_snapshot_hash: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VisualFlowerRollerEvidenceReviewRow(Base):
    """Append-only review of a design evidence bundle; never a tooling approval."""
    __tablename__ = "visual_flower_roller_evidence_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String, unique=True)
    candidate_id: Mapped[str] = mapped_column(String, index=True)
    pass_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    selected_design_id: Mapped[str | None] = mapped_column(String)
    selected_revision_id: Mapped[str | None] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(String, default="")
    evidence_bundle_hash: Mapped[str | None] = mapped_column(String)
    selected_source_reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_source_flower_id: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_source_pass_id: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_source_match_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VisualFlowerExportArtifactRow(Base):
    __tablename__ = "visual_flower_export_artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("visual_flower_candidates.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)


class SyntheticCorpusDatasetRow(Base):
    __tablename__ = "synthetic_corpus_datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_hash: Mapped[str] = mapped_column(String)
    classification: Mapped[str] = mapped_column(String)
    generator_version: Mapped[str] = mapped_column(String)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="GENERATED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SyntheticCorpusGenerationRunRow(Base):
    __tablename__ = "synthetic_corpus_generation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("synthetic_corpus_datasets.id", ondelete="CASCADE"))
    run_key: Mapped[str] = mapped_column(String, unique=True)
    configuration_hash: Mapped[str] = mapped_column(String)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SyntheticCorpusSampleRow(Base):
    __tablename__ = "synthetic_corpus_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("synthetic_corpus_datasets.id", ondelete="CASCADE"))
    sample_id: Mapped[str] = mapped_column(String)
    parent_group_id: Mapped[str] = mapped_column(String)
    classification: Mapped[str] = mapped_column(String)
    split: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("dataset_id", "sample_id", name="uq_synthetic_corpus_sample"),)


class CLRSGTrainingRunRow(Base):
    __tablename__ = "clrsg_training_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True)
    dataset_id: Mapped[str] = mapped_column(String)
    model_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CLRSGModelRow(Base):
    __tablename__ = "clrsg_models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String, unique=True)
    algorithm_version: Mapped[str] = mapped_column(String)
    dataset_id: Mapped[str] = mapped_column(String)
    dataset_hash: Mapped[str] = mapped_column(String)
    privacy_classification: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="TRAINED")
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CLRSGModelMemberRow(Base):
    __tablename__ = "clrsg_model_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("clrsg_models.id", ondelete="CASCADE"))
    member_id: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CLRSGEvaluationRunRow(Base):
    __tablename__ = "clrsg_evaluation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String, unique=True)
    model_id: Mapped[str] = mapped_column(String)
    dataset_id: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CLRSGModelActivationRow(Base):
    __tablename__ = "clrsg_model_activations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String)
    topology_scope: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
