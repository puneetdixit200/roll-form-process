from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import ezdxf
from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.database import (
    CompositeFlower,
    CompositeFlowerPass,
    PassFeatureSetRow,
    Project,
    Station,
    create_project_database,
    foreign_key_violations,
)
from rollform_extractor.pass_features import FORBIDDEN_COMPARISON_FIELDS, PASS_FEATURE_SCHEMA_VERSION


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    file_size: int | None = None
    severity: str = "ERROR"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    counts: dict[str, int] | None = None
    readiness: dict[str, object] | None = None

    def to_dict(self, project_path: Path | None = None) -> dict[str, object]:
        return {
            "valid": self.valid,
            "project_path": str(project_path) if project_path else None,
            "issues": [issue.to_dict() for issue in self.issues],
            "counts": self.counts or {},
            "readiness": self.readiness or {},
        }


def validate_project(project_path: Path) -> ValidationReport:
    issues: list[ValidationIssue] = []
    manifest_path = project_path / "manifest.json"
    project_json_path = project_path / "project.json"
    if not manifest_path.exists():
        return ValidationReport(False, (ValidationIssue("missing_manifest", "manifest.json is missing", path="manifest.json"),), counts={}, readiness={})
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    project = json.loads(project_json_path.read_text(encoding="utf-8")) if project_json_path.exists() else {}

    source = project.get("source_path")
    source_path = Path(source) if source else None
    if source_path is not None:
        if not source_path.is_file():
            issues.append(ValidationIssue("missing_source", "original source file is missing", path=str(source_path)))
        elif _sha256(source_path) != manifest.get("source_sha256"):
            actual = _sha256(source_path)
            issues.append(ValidationIssue("source_hash_mismatch", "source hash does not match manifest", path=str(source_path), expected_sha256=manifest.get("source_sha256"), actual_sha256=actual, file_size=source_path.stat().st_size))
    if not project.get("units"):
            issues.append(ValidationIssue("missing_units", "project units are not visible", path="project.json"))

    for relative, meta in manifest.get("files", {}).items():
        path = project_path / relative
        if not path.exists():
            issues.append(ValidationIssue("missing_file", relative, path=relative))
        elif _sha256(path) != meta.get("sha256"):
            actual = _sha256(path)
            issues.append(ValidationIssue("hash_mismatch", relative, path=relative, expected_sha256=meta.get("sha256"), actual_sha256=actual, file_size=path.stat().st_size))

    for relative in manifest.get("dxf_files", ()):
        try:
            ezdxf.readfile(project_path / relative)
        except Exception as exc:
            issues.append(ValidationIssue("invalid_dxf", f"{relative}: {exc}"))

    sqlite_path = project_path / "project.sqlite"
    db_counts: dict[str, int] = {}
    if sqlite_path.exists():
        engine = create_project_database(sqlite_path)
        if foreign_key_violations(engine):
            issues.append(ValidationIssue("foreign_key_violation", "SQLite foreign keys are inconsistent"))
        with Session(engine) as session:
            ids = [row.station_id for row in session.scalars(select(Station)).all()]
            db_counts = {
                "stations": session.query(Station).count(),
                "composite_flowers": session.query(CompositeFlower).count(),
                "composite_passes": session.query(CompositeFlowerPass).count(),
                "feature_sets": session.query(PassFeatureSetRow).count(),
            }
        if len(ids) != len(set(ids)):
            issues.append(ValidationIssue("duplicate_station", "station identifiers are not unique"))

    issues.extend(_validate_features(project_path, manifest, db_counts))

    stations = tuple(project.get("stations", ()))
    multi_sequence = len({int((station.get("evidence") or {}).get("sequence_id") or 1) for station in stations}) > 1
    expected_dirs = {
        _station_dir_name(station, multi_sequence)
        for station in stations
    }
    actual_dirs = {path.name for path in (project_path / "stations").iterdir() if path.is_dir()} if (project_path / "stations").exists() else set()
    if expected_dirs != actual_dirs:
        issues.append(ValidationIssue("station_tree_mismatch", "station folders do not match project stations"))
    report = _readiness_report(project_path, project, manifest, issues, db_counts)
    return ValidationReport(not issues, tuple(issues), counts=report["counts"], readiness=report["readiness"])


def _validate_features(project_path: Path, manifest: dict, db_counts: dict[str, int] | None = None) -> list[ValidationIssue]:
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
        issues.append(ValidationIssue("feature_pass_count", f"{len(feature_passes)} feature sets for {len(passes)} composite passes", path="report_data.json"))
    full_lengths = set()
    scalar_lengths = set()
    shape_lengths = set()
    for item in feature_passes:
        feature = item["features"]
        comparison_fields = set((feature.get("scalar_vector") or {}).get("field_names", ()))
        comparison_fields.update((feature.get("shape_vector") or {}).get("field_names", ()))
        forbidden = sorted(comparison_fields & FORBIDDEN_COMPARISON_FIELDS)
        if forbidden:
            issues.append(ValidationIssue("forbidden_comparison_field", f"{item.get('pass_id', 'unknown')}: {', '.join(forbidden)}", path="report_data.json"))
        if feature.get("schema_version") != PASS_FEATURE_SCHEMA_VERSION:
            issues.append(ValidationIssue("unsupported_feature_schema", str(feature.get("schema_version")), path="report_data.json"))
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
    if db_counts and db_counts.get("feature_sets") != len(feature_passes):
        issues.append(ValidationIssue("database_feature_count", f"database has {db_counts.get('feature_sets')} feature sets but report has {len(feature_passes)}", path="project.sqlite"))
    return issues


def _readiness_report(project_path: Path, project: dict, manifest: dict, issues: list[ValidationIssue], db_counts: dict[str, int]) -> dict[str, object]:
    report_data = {}
    report_path = project_path / "report_data.json"
    if report_path.exists():
        try:
            report_data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    flowers = report_data.get("composite_flowers", ())
    passes = [item for flower in flowers for item in flower.get("passes", ())]
    units = (project.get("configuration_snapshot") or project.get("configuration") or {}).get("units", {})
    project_units = project.get("units") if isinstance(project.get("units"), dict) else {}
    units_confirmed = bool(units.get("confirmed") or project_units.get("confirmed"))
    order_confirmed = all(item.get("engineer_confirmed_order") is not None for item in passes) if passes else False
    counts = {
        "stations": len(project.get("stations", ())),
        "sequences": len({int((station.get("evidence") or {}).get("sequence_id") or 1) for station in project.get("stations", ())}),
        "composite_flowers": len(flowers),
        "composite_passes": len(passes),
        "feature_sets": sum(1 for item in passes if item.get("features")),
        "database_composite_flowers": db_counts.get("composite_flowers", 0),
        "database_composite_passes": db_counts.get("composite_passes", 0),
        "database_feature_sets": db_counts.get("feature_sets", 0),
    }
    determinism_path = project_path / "determinism_summary.json"
    determinism = _load_optional_json(determinism_path)
    readiness = {
        "units_confirmed": units_confirmed,
        "order_confirmed": order_confirmed,
        "deterministic": bool(determinism.get("equal", False)),
        "eligible_for_corpus_import": False,
    }
    return {"counts": counts, "readiness": readiness}


def _load_optional_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


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
