from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import ezdxf
from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.database import Station, create_project_database, foreign_key_violations


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]


def validate_project(project_path: Path) -> ValidationReport:
    issues: list[ValidationIssue] = []
    manifest_path = project_path / "manifest.json"
    project_json_path = project_path / "project.json"
    if not manifest_path.exists():
        return ValidationReport(False, (ValidationIssue("missing_manifest", "manifest.json is missing"),))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project = json.loads(project_json_path.read_text(encoding="utf-8")) if project_json_path.exists() else {}

    source = project.get("source_path")
    source_path = Path(source) if source else None
    if source_path is not None:
        if not source_path.is_file():
            issues.append(ValidationIssue("missing_source", "original source file is missing"))
        elif _sha256(source_path) != manifest.get("source_sha256"):
            issues.append(ValidationIssue("source_hash_mismatch", "source hash does not match manifest"))
    if not project.get("units"):
        issues.append(ValidationIssue("missing_units", "project units are not visible"))

    for relative, meta in manifest.get("files", {}).items():
        path = project_path / relative
        if not path.exists():
            issues.append(ValidationIssue("missing_file", relative))
        elif _sha256(path) != meta.get("sha256"):
            issues.append(ValidationIssue("hash_mismatch", relative))

    for relative in manifest.get("dxf_files", ()):
        try:
            ezdxf.readfile(project_path / relative)
        except Exception as exc:
            issues.append(ValidationIssue("invalid_dxf", f"{relative}: {exc}"))

    sqlite_path = project_path / "project.sqlite"
    if sqlite_path.exists():
        engine = create_project_database(sqlite_path)
        if foreign_key_violations(engine):
            issues.append(ValidationIssue("foreign_key_violation", "SQLite foreign keys are inconsistent"))
        with Session(engine) as session:
            ids = [row.station_id for row in session.scalars(select(Station)).all()]
        if len(ids) != len(set(ids)):
            issues.append(ValidationIssue("duplicate_station", "station identifiers are not unique"))

    issues.extend(_validate_features(project_path, manifest))

    stations = tuple(project.get("stations", ()))
    multi_sequence = len({int((station.get("evidence") or {}).get("sequence_id") or 1) for station in stations}) > 1
    expected_dirs = {
        _station_dir_name(station, multi_sequence)
        for station in stations
    }
    actual_dirs = {path.name for path in (project_path / "stations").iterdir() if path.is_dir()} if (project_path / "stations").exists() else set()
    if expected_dirs != actual_dirs:
        issues.append(ValidationIssue("station_tree_mismatch", "station folders do not match project stations"))
    return ValidationReport(not issues, tuple(issues))


def _validate_features(project_path: Path, manifest: dict) -> list[ValidationIssue]:
    report_path = project_path / "report_data.json"
    if not report_path.exists():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [ValidationIssue("invalid_feature_report", str(exc))]
    summary = (report.get("project") or {}).get("feature_summary")
    if not summary:
        return []
    issues: list[ValidationIssue] = []
    passes = [item for flower in report.get("composite_flowers", ()) for item in flower.get("passes", ())]
    feature_passes = [item for item in passes if item.get("features")]
    if len(feature_passes) != len(passes):
        issues.append(ValidationIssue("feature_pass_count", f"{len(feature_passes)} feature sets for {len(passes)} composite passes"))
    full_lengths = set()
    scalar_lengths = set()
    shape_lengths = set()
    for item in feature_passes:
        feature = item["features"]
        vector = feature.get("full_vector") or {}
        names = vector.get("field_names", ())
        values = vector.get("values", ())
        mask = vector.get("missing_mask", ())
        full_lengths.add(len(values))
        scalar = feature.get("scalar_vector") or {}
        shape = feature.get("shape_vector") or {}
        scalar_lengths.add(len(scalar.get("values", ())))
        shape_lengths.add(len(shape.get("values", ())))
        if feature.get("schema_version") is None or not feature.get("configuration_hash"):
            issues.append(ValidationIssue("feature_metadata_missing", item.get("pass_id", "unknown")))
        if len(names) != len(values) or len(mask) != len(values):
            issues.append(ValidationIssue("feature_vector_shape", item.get("pass_id", "unknown")))
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            issues.append(ValidationIssue("feature_nonfinite", item.get("pass_id", "unknown")))
        fingerprints = feature.get("fingerprints") or {}
        if any(not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()) for value in fingerprints.values()):
            issues.append(ValidationIssue("feature_fingerprint_invalid", item.get("pass_id", "unknown")))
        if not _finite_json(feature):
            issues.append(ValidationIssue("feature_nonfinite", item.get("pass_id", "unknown")))
        downloads = item.get("feature_downloads") or {}
        for relative in downloads.values():
            if relative and not (project_path / relative).exists():
                issues.append(ValidationIssue("missing_feature_artifact", str(relative)))
    if len(full_lengths) > 1:
        issues.append(ValidationIssue("feature_vector_length", "full vector lengths differ between passes"))
    if len(scalar_lengths) > 1 or len(shape_lengths) > 1:
        issues.append(ValidationIssue("feature_vector_length", "scalar or shape vector lengths differ between passes"))
    if summary.get("feature_set_count") != len(feature_passes):
        issues.append(ValidationIssue("feature_summary_count", "feature summary count does not match pass data"))
    return issues


def _finite_json(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_json(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return all(_finite_json(item) for item in value)
    return True


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _station_dir_name(station: dict, duplicated: bool) -> str:
    sequence_index = int(station["sequence_index"])
    if duplicated:
        sequence_id = int((station.get("evidence") or {}).get("sequence_id") or 1)
        return f"sequence_{sequence_id:02d}_station_{sequence_index:02d}"
    return f"station_{sequence_index:02d}"
