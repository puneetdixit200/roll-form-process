from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import os
import shutil
from uuid import uuid4

import ezdxf

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.composite_flower import apply_confirmed_pass_order, build_composite_flower_result
from rollform_extractor.converter import stage_input
from rollform_extractor.database import ExtractionBundle, create_project_database, persist_extraction, record_stage
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.exporters import Manifest, export_project
from rollform_extractor.models import StageResult
from rollform_extractor.pass_features import extract_composite_pass_features
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
    composite_result = build_composite_flower_result(typed_stations, profiles.profiles, classified.entities)
    composite_flowers = _apply_pass_order_review(request.output_root / request.source.stem, composite_result.accepted)
    feature_configuration_hash = config.hash_for("feature_extraction")
    pass_features = {
        (composite.composite_flower_id, pass_id): feature
        for composite in composite_flowers
        for pass_id, feature in extract_composite_pass_features(
            request.source.stem,
            composite,
            feature_configuration_hash,
            config.features,
            snapshot["units"],
        ).items()
    }
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
        rejected_composite_regions=composite_result.rejected,
        pass_features=pass_features,
        warnings=warnings,
    )
    manifest = export_project(bundle, request.output_root)
    engine = create_project_database(project_path / "project.sqlite")
    project_id = persist_extraction(engine, bundle)
    _record_stages(engine, project_id, parsed, classified, stations, profiles, rollers, bundle)
    manifest = export_project(bundle, request.output_root)
    return ExtractionSummary(project_path, manifest, len(bundle.stations), len(bundle.warnings))


def reprocess_project(project_path: Path, config_path: Path | None = None) -> ExtractionSummary:
    return regenerate_project(project_path, config_path)


def regenerate_project(project_path: Path, config_path: Path | None = None, review_decisions: dict | None = None) -> ExtractionSummary:
    """Regenerate into a sibling temporary project and replace atomically."""
    data = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    source = Path(data["source_path"])
    if not source.is_file():
        raise FileNotFoundError(f"source drawing is missing: {source}")
    temporary = project_path.parent / f".{project_path.name}.tmp-{uuid4().hex}"
    backup = project_path.parent / f".{project_path.name}.bak-{uuid4().hex}"
    try:
        temporary.mkdir(parents=True, exist_ok=False)
        target = temporary / project_path.name
        target.mkdir(parents=True, exist_ok=True)
        # Seed the temporary database with the prior database so extraction
        # cleanup can preserve immutable run history and review/audit rows.
        # The extractor still replaces current project results transactionally.
        previous_db = project_path / "project.sqlite"
        if previous_db.exists():
            shutil.copy2(previous_db, target / "project.sqlite")
        review_source = project_path / "review"
        if review_source.exists():
            shutil.copytree(review_source, target / "review")
        if review_decisions is not None:
            target_review = target / "review"
            target_review.mkdir(parents=True, exist_ok=True)
            if review_decisions.get("stations") or review_decisions.get("drawing_units"):
                (target_review / "manual_overrides.json").write_text(json.dumps(review_decisions, indent=2, sort_keys=True), encoding="utf-8")
            if review_decisions.get("pass_order_decisions") or review_decisions.get("composite_passes"):
                (target_review / "pass_order_decisions.json").write_text(json.dumps(review_decisions, indent=2, sort_keys=True), encoding="utf-8")
        summary = extract_project(ExtractionRequest(source, temporary, config_path))
        generated = summary.project_path
        # ExtractionRequest writes under the temporary root.  The copied review
        # directory is authoritative input and must survive the generation.
        if project_path.exists():
            os.replace(project_path, backup)
        try:
            os.replace(generated, project_path)
        except Exception:
            if backup.exists() and not project_path.exists():
                os.replace(backup, project_path)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return ExtractionSummary(project_path, summary.manifest, summary.station_count, summary.warning_count)
    except Exception:
        if backup.exists() and not project_path.exists():
            os.replace(backup, project_path)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and project_path.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _load_project_overrides(project_path: Path, entities) -> object | None:
    path = project_path / "review" / "manual_overrides.json"
    if not path.exists():
        return None
    handles = {handle for entity in entities for handle in (entity.source_handles or (entity.handle,))}
    return load_overrides(path, handles)


def _apply_pass_order_review(project_path: Path, composites):
    path = project_path / "review" / "pass_order_decisions.json"
    if not path.exists():
        return composites
    try:
        decisions = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return composites
    return apply_confirmed_pass_order(composites, decisions)


def _record_stages(engine, project_id: int, parsed, classified, stations, profiles, rollers, bundle: ExtractionBundle) -> None:
    for stage, records, warnings, method, config_hash, confidence in (
        ("parsing", parsed.entities + parsed.expanded_entities, parsed.warnings, parsed.method, parsed.configuration_hash, 1.0),
        ("support_classification", classified.entities, (), classified.method, classified.configuration_hash, 1.0),
        ("station_detection", stations.stations, stations.warnings, stations.method, stations.configuration_hash, 1.0),
        ("profile_detection", profiles.profiles, profiles.warnings, profiles.method, profiles.configuration_hash, 1.0),
        ("roller_detection", rollers.rollers, rollers.warnings, rollers.method, rollers.configuration_hash, 1.0),
        ("feature_extraction", tuple(bundle.pass_features.values()), (), "composite_pass_feature_extractor_v1", config_hash_for_bundle(bundle), min((feature.quality.confidence for feature in bundle.pass_features.values()), default=0.0)),
    ):
        handles = tuple(handle for record in records for handle in getattr(record, "source_handles", ()))
        record_stage(engine, project_id, StageResult(stage, tuple(records), tuple(warnings), handles, method, config_hash, confidence))


def config_hash_for_bundle(bundle: ExtractionBundle) -> str:
    return next(iter(bundle.pass_features.values())).configuration_hash if bundle.pass_features else bundle.configuration_hash


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
