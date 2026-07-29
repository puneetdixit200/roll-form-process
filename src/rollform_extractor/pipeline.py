from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import ezdxf

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.converter import stage_input
from rollform_extractor.database import ExtractionBundle, create_project_database, persist_extraction, record_stage
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.exporters import Manifest, export_project
from rollform_extractor.models import StageResult
from rollform_extractor.profile_detector import detect_profiles
from rollform_extractor.review import load_overrides
from rollform_extractor.roller_detector import detect_rollers
from rollform_extractor.station_detector import detect_stations
from rollform_extractor.support_classifier import classify_support


@dataclass(frozen=True)
class ExtractionRequest:
    source: Path
    output_root: Path
    config_path: Path | None = None


@dataclass(frozen=True)
class ExtractionSummary:
    project_path: Path
    manifest: Manifest
    station_count: int
    warning_count: int


def extract_project(request: ExtractionRequest) -> ExtractionSummary:
    config = ExtractionConfig.load(request.config_path)
    project_path = request.output_root / request.source.stem
    staged = stage_input(request.source, project_path / "source")
    inspection = inspect_drawing(staged.converted_file)
    doc = ezdxf.readfile(staged.converted_file)
    parsed = parse_entities(doc, config)
    entities = parsed.entities + parsed.expanded_entities
    classified = classify_support(entities, inspection, config)
    overrides = _load_project_overrides(project_path, classified.entities)
    stations = detect_stations(classified.entities, inspection, config, overrides)
    profiles = detect_profiles(tuple(station.record for station in stations.stations), classified.entities, config, overrides)
    rollers = detect_rollers(tuple(station.record for station in stations.stations), profiles.profiles, classified.entities, config, overrides)
    warnings = parsed.warnings + stations.warnings + profiles.warnings + rollers.warnings
    snapshot = config.snapshot()
    snapshot["units"]["default"] = inspection.units
    bundle = ExtractionBundle(
        drawing_id=request.source.stem,
        source_path=request.source.resolve(),
        source_sha256=_sha256(request.source),
        converted_path=staged.converted_file,
        converted_sha256=_sha256(staged.converted_file),
        configuration_snapshot=snapshot,
        configuration_hash=sha256(repr(snapshot).encode("utf-8")).hexdigest(),
        status="success",
        entities=classified.entities,
        stations=tuple(station.record for station in stations.stations),
        profiles=profiles.profiles,
        roller_occurrences=rollers.rollers,
        warnings=warnings,
    )
    manifest = export_project(bundle, request.output_root)
    engine = create_project_database(project_path / "project.sqlite")
    project_id = persist_extraction(engine, bundle)
    _record_stages(engine, project_id, parsed, classified, stations, profiles, rollers)
    manifest = export_project(bundle, request.output_root)
    return ExtractionSummary(project_path, manifest, len(bundle.stations), len(bundle.warnings))


def reprocess_project(project_path: Path, config_path: Path | None = None) -> ExtractionSummary:
    data = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    source = Path(data["source_path"])
    return extract_project(ExtractionRequest(source, project_path.parent, config_path))


def _load_project_overrides(project_path: Path, entities) -> object | None:
    path = project_path / "review" / "manual_overrides.json"
    if not path.exists():
        return None
    handles = {handle for entity in entities for handle in (entity.source_handles or (entity.handle,))}
    return load_overrides(path, handles)


def _record_stages(engine, project_id: int, parsed, classified, stations, profiles, rollers) -> None:
    for stage, records, warnings, method, config_hash, confidence in (
        ("parsing", parsed.entities + parsed.expanded_entities, parsed.warnings, parsed.method, parsed.configuration_hash, 1.0),
        ("support_classification", classified.entities, (), classified.method, classified.configuration_hash, 1.0),
        ("station_detection", stations.stations, stations.warnings, stations.method, stations.configuration_hash, 1.0),
        ("profile_detection", profiles.profiles, profiles.warnings, profiles.method, profiles.configuration_hash, 1.0),
        ("roller_detection", rollers.rollers, rollers.warnings, rollers.method, rollers.configuration_hash, 1.0),
    ):
        handles = tuple(handle for record in records for handle in getattr(record, "source_handles", ()))
        record_stage(engine, project_id, StageResult(stage, tuple(records), tuple(warnings), handles, method, config_hash, confidence))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
