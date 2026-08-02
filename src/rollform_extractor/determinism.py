"""Canonical semantic snapshots for reproducible project comparison."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def canonical_project_snapshot(project_path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for name in ("project.json", "report_data.json"):
        path = project_path / name
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            snapshot[name] = _strip_variable(value)
    db = project_path / "project.sqlite"
    if db.exists():
        snapshot["project.sqlite"] = _database_snapshot(db)
    return snapshot


def canonical_project_hash(project_path: Path) -> str:
    payload = json.dumps(canonical_project_snapshot(project_path), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_project_snapshots(left: Path, right: Path) -> dict[str, Any]:
    a = canonical_project_snapshot(left)
    b = canonical_project_snapshot(right)
    mismatches = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            mismatches.append(key)
    result = {"equal": not mismatches, "mismatches": mismatches, "left_hash": canonical_project_hash(left), "right_hash": canonical_project_hash(right)}
    return result


def write_determinism_summary(project_path: Path, result: dict[str, Any]) -> Path:
    path = project_path / "determinism_summary.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _database_snapshot(path: Path) -> dict[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(path)
    try:
        tables = [row[0] for row in connection.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        result = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f'pragma table_info("{table}")')]
            rows = connection.execute(f'select * from "{table}"').fetchall()
            result[table] = [
                dict(sorted((column, _strip_db_value(column, value)) for column, value in zip(columns, row)))
                for row in sorted(rows, key=lambda row: repr(row))
            ]
        return result
    finally:
        connection.close()


def _strip_variable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_variable(item) for key, item in sorted(value.items()) if key not in {"created_at", "updated_at", "generated_at", "timestamp", "source_path"}}
    if isinstance(value, list):
        return [_strip_variable(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_variable(item) for item in value]
    return value


def _strip_db_value(column: str, value: Any) -> Any:
    if column in {"created_at", "updated_at", "started_at", "finished_at", "timestamp", "source_path", "converted_path"}:
        return None
    return _strip_variable(value)
