"""Shared structural validation for historical flower dataset payloads."""
from __future__ import annotations

import math
from typing import Any, Mapping


def validate_flower_prototype_dataset(payload: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    flowers = list(payload.get("flowers") or [])
    flower_ids = [str(item.get("flower_id") or "") for item in flowers]
    if int(payload.get("schema_version", 0)) not in {1, 2}:
        issues.append({"code": "UNSUPPORTED_SCHEMA", "message": "dataset schema must be v1 or v2"})
    if not payload.get("dataset_id") or not payload.get("dataset_hash"):
        issues.append({"code": "MISSING_DATASET_IDENTITY", "message": "dataset_id and dataset_hash are required"})
    if len(set(flower_ids)) != len(flower_ids) or any(not value for value in flower_ids):
        issues.append({"code": "DUPLICATE_FLOWER_ID", "message": "flower IDs must be non-empty and unique"})
    pass_keys: set[str] = set()
    for flower in flowers:
        passes = list(flower.get("passes") or [])
        if len(passes) <= 1:
            issues.append({"code": "FLOWER_TOO_FEW_PASSES", "message": f"{flower.get('flower_id')} must have more than one pass"})
        local_ids: set[str] = set()
        for item in passes:
            pass_id = str(item.get("pass_id") or "")
            key = f"{flower.get('flower_id')}::{pass_id}"
            if not pass_id or pass_id in local_ids or key in pass_keys:
                issues.append({"code": "DUPLICATE_PASS_ID", "message": f"duplicate or empty pass ID: {key}"})
            local_ids.add(pass_id); pass_keys.add(key)
            vector = item.get("shape_vector") or []
            if not vector or len(vector) % 2 or not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector):
                issues.append({"code": "INVALID_SHAPE_VECTOR", "message": f"invalid shape vector: {key}"})
    evidence_keys: set[tuple[str, str, str, str, str]] = set()
    for item in payload.get("roller_station_evidence", []) or payload.get("historical_roller_station_evidence", []):
        key = (str(item.get("flower_id") or ""), str(item.get("pass_id") or ""), str(item.get("role") or ""), str(item.get("design_id") or ""), str(item.get("geometry_revision_id") or ""))
        if key in evidence_keys:
            issues.append({"code": "DUPLICATE_STATION_EVIDENCE", "message": "duplicate station evidence identity"})
        evidence_keys.add(key)
        if key[0] not in flower_ids or f"{key[0]}::{key[1]}" not in pass_keys:
            issues.append({"code": "ORPHAN_STATION_EVIDENCE", "message": "station evidence references an unknown flower/pass"})
        if not key[2]:
            issues.append({"code": "EMPTY_EVIDENCE_ROLE", "message": "station evidence role is required"})
        if not key[3]:
            issues.append({"code": "EMPTY_EVIDENCE_DESIGN", "message": "station evidence design_id is required"})
    return {"valid": not issues, "issues": issues, "flower_count": len(flowers), "pass_count": sum(len(item.get("passes") or []) for item in flowers), "roller_station_evidence_count": len(payload.get("roller_station_evidence", []) or payload.get("historical_roller_station_evidence", []))}
