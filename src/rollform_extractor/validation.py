from __future__ import annotations

import json
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
    if source_path is not None and source_path.is_file() and _sha256(source_path) != manifest.get("source_sha256"):
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

    expected_dirs = {f"station_{station['sequence_index']:02d}" for station in project.get("stations", ())}
    actual_dirs = {path.name for path in (project_path / "stations").iterdir() if path.is_dir()} if (project_path / "stations").exists() else set()
    if expected_dirs != actual_dirs:
        issues.append(ValidationIssue("station_tree_mismatch", "station folders do not match project stations"))
    return ValidationReport(not issues, tuple(issues))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
