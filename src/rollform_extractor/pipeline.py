from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

import ezdxf

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.composite_flower import build_composite_flowers
from rollform_extractor.converter import stage_input
from rollform_extractor.database import ExtractionBundle, create_project_database, persist_extraction, record_stage
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.exporters import Manifest, export_project
from rollform_extractor.models import StageResult
from rollform_extractor.profile_detector import detect_profiles
from rollform_extractor.review import load_overrides
from rollform_extractor.roller_detector import detect_rollers
from rollform_extractor.stage_classifier import assign_stage_types, confirmed_transitions
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
    typed_for_rollers = assign_stage_types((station.record for station in stations.stations), profiles.profiles)
    rollers = detect_rollers(typed_for_rollers, profiles.profiles, classified.entities, config, overrides)
    typed_stations = assign_stage_types(typed_for_rollers, profiles.profiles, rollers.rollers)
    warnings = _unique_warnings(parsed.warnings + stations.warnings + profiles.warnings + rollers.warnings)
    snapshot = config.snapshot()
    drawing_units = getattr(overrides, "drawing_units", {}) if overrides is not None else {}
    confirmed_units = getattr(overrides, "units", None) if overrides is not None and drawing_units.get("confirmed") else None
    snapshot["units"]["detected"] = inspection.units
    snapshot["units"]["drawing_units"] = dict(drawing_units)
    snapshot["units"]["confirmed"] = bool(drawing_units.get("confirmed"))
    snapshot["units"]["default"] = confirmed_units if drawing_units.get("confirmed") else None
    snapshot["units"]["conversion_factor_to_mm"] = drawing_units.get("conversion_factor_to_mm")
    transitions = confirmed_transitions(typed_stations, profiles.profiles, config.hash_for("profile_detection"), bool(snapshot["units"]["confirmed"]))
    composite_flowers = build_composite_flowers(typed_stations, profiles.profiles, classified.entities)
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
        stations=typed_stations,
        profiles=profiles.profiles,
        roller_occurrences=rollers.rollers,
        assemblies=rollers.assemblies,
        transitions=transitions,
        composite_flowers=composite_flowers,
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


def _unique_warnings(warnings):
    seen = set()
    result = []
    for warning in warnings:
        key = (warning.code, tuple(sorted(warning.source_handles)), warning.method, warning.configuration_hash)
        if key not in seen:
            seen.add(key)
            result.append(warning)
    return tuple(result)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
