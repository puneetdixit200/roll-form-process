from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import html
import json
from pathlib import Path
import sqlite3
from typing import Any

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.pipeline import ExtractionRequest, extract_project
from rollform_extractor.validation import ValidationIssue, ValidationReport, validate_project


@dataclass(frozen=True)
class BatchRequest:
    source_root: Path
    output_root: Path
    resume: bool = False
    skip_unchanged: bool = False
    patterns: tuple[str, ...] = ("*.dxf", "*.dwg", "*.DXF", "*.DWG")


@dataclass(frozen=True)
class BatchSummary:
    total_files: int
    projects_succeeded: int
    projects_failed: int
    projects_skipped: int
    projects_reprocessed: int
    station_count: int
    profile_count: int
    roller_count: int
    warning_count: int
    master_database: Path
    ledger_path: Path
    report_path: Path


def batch_extract(request: BatchRequest) -> BatchSummary:
    request.output_root.mkdir(parents=True, exist_ok=True)
    ledger_path = request.output_root / "batch_ledger.json"
    ledger = _read_ledger(ledger_path)
    config_hash = _config_hash()
    entries: dict[str, dict[str, Any]] = {entry["source_path"]: entry for entry in ledger.get("files", ())}
    totals = {"success": 0, "failed": 0, "skipped": 0, "reprocessed": 0, "stations": 0, "profiles": 0, "rollers": 0, "warnings": 0}
    sources = _discover_sources(request)

    for source in sources:
        source_sha = _sha256(source)
        key = str(source.resolve())
        previous = entries.get(key)
        project_path = request.output_root / source.stem
        if _can_skip(request, previous, source_sha, config_hash, project_path):
            entry = dict(previous)
            entry["action"] = "skipped"
            totals["skipped"] += 1
        else:
            if previous is not None and request.resume:
                totals["reprocessed"] += 1
            entry = _extract_one(source, request.output_root, source_sha, config_hash)
        entries[key] = entry
        _add_totals(totals, entry)
        _write_ledger(ledger_path, entries, config_hash)

    master = aggregate_master(request.output_root)
    report = write_batch_report(request.output_root)
    return BatchSummary(
        total_files=len(sources),
        projects_succeeded=totals["success"],
        projects_failed=totals["failed"],
        projects_skipped=totals["skipped"],
        projects_reprocessed=totals["reprocessed"],
        station_count=totals["stations"],
        profile_count=totals["profiles"],
        roller_count=totals["rollers"],
        warning_count=totals["warnings"],
        master_database=master,
        ledger_path=ledger_path,
        report_path=report,
    )


def aggregate_master(output_root: Path) -> Path:
    master_dir = output_root / "master"
    master_dir.mkdir(parents=True, exist_ok=True)
    master_path = master_dir / "master_rollform.sqlite"
    with sqlite3.connect(master_path) as master:
        master.execute("pragma foreign_keys=on")
        _create_master_schema(master)
        for project_db in sorted(output_root.glob("*/project.sqlite")):
            _aggregate_project(master, project_db)
        master.commit()
    _write_master_csvs(output_root, master_path)
    return master_path


def validate_batch(output_root: Path) -> ValidationReport:
    issues: list[ValidationIssue] = []
    for project_json in sorted(output_root.glob("*/project.json")):
        report = validate_project(project_json.parent)
        issues.extend(ValidationIssue(issue.code, f"{project_json.parent.name}: {issue.message}") for issue in report.issues)
    if not (output_root / "master" / "master_rollform.sqlite").exists():
        issues.append(ValidationIssue("missing_master_database", "master/master_rollform.sqlite is missing"))
    return ValidationReport(not issues, tuple(issues))


def write_batch_report(output_root: Path) -> Path:
    master_path = output_root / "master" / "master_rollform.sqlite"
    if not master_path.exists():
        master_path = aggregate_master(output_root)
    with sqlite3.connect(master_path) as db:
        counts = {
            name: db.execute(f"select count(*) from {name}").fetchone()[0]
            for name in ("projects", "stations", "profiles", "rollers")
        }
    report = output_root / "master" / "extraction_dashboard.html"
    report.write_text(
        "<!doctype html><title>Batch Extraction</title>"
        "<h1>Batch Extraction</h1>"
        + "".join(f"<p>{html.escape(name)}={value}</p>" for name, value in counts.items()),
        encoding="utf-8",
    )
    return report


def _extract_one(source: Path, output_root: Path, source_sha: str, config_hash: str) -> dict[str, Any]:
    started = _now()
    try:
        summary = extract_project(ExtractionRequest(source, output_root))
        data = json.loads((summary.project_path / "project.json").read_text(encoding="utf-8"))
        return {
            "source_path": str(source.resolve()),
            "source_sha256": source_sha,
            "configuration_hash": config_hash,
            "project_path": str(summary.project_path),
            "project_database": str(summary.project_path / "project.sqlite"),
            "status": "success",
            "action": "processed",
            "stations": summary.station_count,
            "profiles": len(data.get("profiles", ())),
            "rollers": len(data.get("rollers", ())),
            "warnings": summary.warning_count,
            "started_at": started,
            "finished_at": _now(),
        }
    except Exception as exc:
        return {
            "source_path": str(source.resolve()),
            "source_sha256": source_sha,
            "configuration_hash": config_hash,
            "project_path": str(output_root / source.stem),
            "status": "failed",
            "action": "failed",
            "error": str(exc),
            "stations": 0,
            "profiles": 0,
            "rollers": 0,
            "warnings": 1,
            "started_at": started,
            "finished_at": _now(),
        }


def _can_skip(request: BatchRequest, previous: dict[str, Any] | None, source_sha: str, config_hash: str, project_path: Path) -> bool:
    return bool(
        request.resume
        and request.skip_unchanged
        and previous
        and previous.get("status") == "success"
        and previous.get("source_sha256") == source_sha
        and previous.get("configuration_hash") == config_hash
        and validate_project(project_path).valid
    )


def _discover_sources(request: BatchRequest) -> list[Path]:
    seen = {path.resolve() for pattern in request.patterns for path in request.source_root.rglob(pattern) if path.is_file()}
    return sorted(seen)


def _add_totals(totals: dict[str, int], entry: dict[str, Any]) -> None:
    if entry["action"] == "skipped":
        pass
    elif entry["status"] == "success":
        totals["success"] += 1
    else:
        totals["failed"] += 1
    totals["stations"] += int(entry.get("stations", 0))
    totals["profiles"] += int(entry.get("profiles", 0))
    totals["rollers"] += int(entry.get("rollers", 0))
    totals["warnings"] += int(entry.get("warnings", 0))


def _read_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_ledger(path: Path, entries: dict[str, dict[str, Any]], config_hash: str) -> None:
    payload = {"configuration_hash": config_hash, "files": [entries[key] for key in sorted(entries)]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _create_master_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        create table if not exists projects (
            id integer primary key,
            drawing_id text not null,
            source_path text not null,
            source_hash text not null,
            source_database text not null,
            source_project_id integer not null,
            configuration_hash text,
            unique(source_database, source_project_id)
        );
        create table if not exists stations (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            station_id text not null,
            sequence_index integer,
            confidence real,
            unique(project_id, station_id)
        );
        create table if not exists profiles (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            profile_id text not null,
            station_id text,
            confidence real,
            unique(project_id, profile_id)
        );
        create table if not exists rollers (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            occurrence_id text not null,
            station_id text,
            role text,
            confidence real,
            unique(project_id, occurrence_id)
        );
        create table if not exists geometry_fingerprints (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            owner_table text,
            owner_key text,
            fingerprint_hash text,
            fingerprint_json text,
            unique(project_id, owner_table, owner_key, fingerprint_hash)
        );
        create table if not exists assembly_templates (
            template_id text primary key,
            signature_hash text,
            template_json text
        );
        create table if not exists roller_catalog (
            id integer primary key,
            source_database text not null,
            source_catalog_id integer not null,
            factory_id text,
            bore real,
            width real,
            diameter real,
            availability text,
            unique(source_database, source_catalog_id)
        );
        create table if not exists project_roll_usage (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            source_usage_id integer not null,
            source_catalog_id integer,
            source_assembly_id integer,
            source_occurrence_id integer,
            unique(project_id, source_usage_id)
        );
        create table if not exists station_transitions (
            id integer primary key,
            project_id integer not null references projects(id) on delete cascade,
            source_transition_id integer not null,
            source_from_station_id integer,
            source_to_station_id integer,
            measurements_json text,
            unique(project_id, source_transition_id)
        );
        """
    )


def _aggregate_project(master: sqlite3.Connection, project_db: Path) -> None:
    with sqlite3.connect(project_db) as source:
        source.row_factory = sqlite3.Row
        project = source.execute(
            "select p.id, p.drawing_id, p.source_path, p.source_sha256, r.configuration_hash "
            "from projects p left join extraction_runs r on r.project_id = p.id "
            "order by r.id desc limit 1"
        ).fetchone()
        if project is None:
            return
        source_database = str(project_db.resolve())
        old_ids = [
            row[0]
            for row in master.execute(
                "select id from projects where source_database = ? and source_project_id = ?",
                (source_database, project["id"]),
            )
        ]
        for old_id in old_ids:
            for table in ("station_transitions", "project_roll_usage", "geometry_fingerprints", "rollers", "profiles", "stations"):
                master.execute(f"delete from {table} where project_id = ?", (old_id,))
        master.execute("delete from roller_catalog where source_database = ?", (source_database,))
        master.execute("delete from projects where source_database = ? and source_project_id = ?", (source_database, project["id"]))
        cursor = master.execute(
            "insert into projects (drawing_id, source_path, source_hash, source_database, source_project_id, configuration_hash) "
            "values (?, ?, ?, ?, ?, ?)",
            (project["drawing_id"], project["source_path"], project["source_sha256"], source_database, project["id"], project["configuration_hash"]),
        )
        project_id = cursor.lastrowid
        _copy_rows(source, master, "stations", project_id, ("station_id", "sequence_index", "confidence"))
        _copy_rows(source, master, "profiles", project_id, ("profile_id", "station_id", "confidence"))
        _copy_rows(source, master, "roller_occurrences", project_id, ("occurrence_id", "station_id", "role", "confidence"), target="rollers")
        _copy_fingerprints(source, master, project_id)
        _copy_templates(source, master)
        _copy_catalog(source, master, source_database)
        _copy_usage(source, master, project_id)
        _copy_transitions(source, master, project_id)


def _copy_rows(source: sqlite3.Connection, master: sqlite3.Connection, table: str, project_id: int, columns: tuple[str, ...], target: str | None = None) -> None:
    target = target or table
    col_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    for row in source.execute(f"select {col_list} from {table}"):
        master.execute(f"insert into {target} (project_id, {col_list}) values (?, {placeholders})", (project_id, *tuple(row)))


def _copy_fingerprints(source: sqlite3.Connection, master: sqlite3.Connection, project_id: int) -> None:
    for row in source.execute("select owner_table, owner_key, fingerprint_hash, fingerprint_json from geometry_fingerprints"):
        master.execute(
            "insert or ignore into geometry_fingerprints (project_id, owner_table, owner_key, fingerprint_hash, fingerprint_json) values (?, ?, ?, ?, ?)",
            (project_id, row[0], row[1], row[2], _json_text(row[3])),
        )


def _copy_templates(source: sqlite3.Connection, master: sqlite3.Connection) -> None:
    for row in source.execute("select template_id, signature_hash, template_json from assembly_templates"):
        master.execute(
            "insert or replace into assembly_templates (template_id, signature_hash, template_json) values (?, ?, ?)",
            (row[0], row[1], _json_text(row[2])),
        )


def _copy_catalog(source: sqlite3.Connection, master: sqlite3.Connection, source_database: str) -> None:
    for row in source.execute("select roller_catalog_id, factory_id, bore, width, diameter, availability from roller_catalog"):
        master.execute(
            "insert or replace into roller_catalog (source_database, source_catalog_id, factory_id, bore, width, diameter, availability) "
            "values (?, ?, ?, ?, ?, ?, ?)",
            (source_database, *tuple(row)),
        )


def _copy_usage(source: sqlite3.Connection, master: sqlite3.Connection, project_id: int) -> None:
    for row in source.execute("select id, roller_catalog_id, assembly_id, occurrence_id from project_roll_usage"):
        master.execute(
            "insert into project_roll_usage (project_id, source_usage_id, source_catalog_id, source_assembly_id, source_occurrence_id) "
            "values (?, ?, ?, ?, ?)",
            (project_id, *tuple(row)),
        )


def _copy_transitions(source: sqlite3.Connection, master: sqlite3.Connection, project_id: int) -> None:
    for row in source.execute("select id, from_station_id, to_station_id, measurements_json from station_transitions"):
        master.execute(
            "insert into station_transitions (project_id, source_transition_id, source_from_station_id, source_to_station_id, measurements_json) "
            "values (?, ?, ?, ?, ?)",
            (project_id, row[0], row[1], row[2], _json_text(row[3])),
        )


def _write_master_csvs(output_root: Path, master_path: Path) -> None:
    with sqlite3.connect(master_path) as db:
        db.row_factory = sqlite3.Row
        _write_csv(output_root / "master" / "projects.csv", [dict(row) for row in db.execute("select drawing_id, source_path, source_hash, source_database, source_project_id from projects order by drawing_id")])
        _write_csv(output_root / "master" / "rollers.csv", [dict(row) for row in db.execute("select p.drawing_id, r.occurrence_id, r.station_id, r.role, r.confidence from rollers r join projects p on p.id = r.project_id order by p.drawing_id, r.occurrence_id")])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = tuple(rows[0]) if rows else ("empty",)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _json_text(value: Any) -> str:
    if value is None:
        return "{}"
    return json.dumps(json.loads(value) if isinstance(value, str) else value, sort_keys=True)


def _config_hash() -> str:
    return sha256(repr(ExtractionConfig.load().snapshot()).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()
