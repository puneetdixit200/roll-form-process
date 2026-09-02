"""Redacted, deterministic navigation records for historical flower evidence.

This module exposes derived geometry and provenance identifiers only.  It never
returns source CAD paths, bytes, or physical roller assignments.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping


HISTORICAL_SOURCE_TRACEABILITY_VERSION = "historical-source-traceability-v1"


def source_reference_id(
    dataset_hash: str,
    flower_id: str,
    pass_id: str,
    role: str,
    design_id: str,
    geometry_revision_id: str | None = None,
) -> str:
    """Return a stable opaque reference for one evidence origin."""
    payload = {
        "dataset_hash": dataset_hash,
        "flower_id": flower_id,
        "pass_id": pass_id,
        "role": role,
        "design_id": design_id,
        "geometry_revision_id": geometry_revision_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "hsr-" + sha256(encoded).hexdigest()[:24]


def safe_historical_flower(flower: Mapping[str, Any], *, include_geometry: bool = False, dataset_hash: str | None = None) -> dict[str, Any]:
    """Build a browser-safe flower record with stable pass ordering."""
    result = {
        "flower_id": flower.get("flower_id"),
        "source_classification": flower.get("source_classification"),
        "source_entity_count": flower.get("source_entity_count"),
        "station_count": len(flower.get("passes") or []),
        "topology": flower.get("topology"),
        "quality_flags": sorted(set(flower.get("quality_flags") or [])),
        "passes": [],
        "private_paths_redacted": True,
        "dataset_hash": dataset_hash,
    }
    for item in sorted(flower.get("passes") or [], key=lambda p: (int(p.get("inferred_order", 0)), str(p.get("pass_id", "")))):
        record = {
            "pass_id": item.get("pass_id"),
            "source_handle": item.get("source_handle"),
            "inferred_order": item.get("inferred_order"),
            "width": item.get("width"),
            "height": item.get("height"),
            "developed_length": item.get("developed_length"),
            "topology": item.get("topology"),
            "bend_count": len(item.get("bend_angles") or []),
            "quality_flags": sorted(set(item.get("quality_flags") or [])),
        }
        if include_geometry:
            record["points"] = item.get("points") or item.get("normalized_points") or []
            record["shape_vector"] = item.get("shape_vector") or []
        result["passes"].append(record)
    return result


def historical_flower_detail(dataset: Mapping[str, Any], flower_id: str) -> dict[str, Any] | None:
    for flower in dataset.get("flowers", []):
        if flower.get("flower_id") == flower_id:
            return safe_historical_flower(flower, include_geometry=True, dataset_hash=str(dataset.get("dataset_hash") or "UNCONFIGURED"))
    return None


def historical_pass_detail(dataset: Mapping[str, Any], flower_id: str, pass_id: str) -> dict[str, Any] | None:
    flower = historical_flower_detail(dataset, flower_id)
    if flower is None:
        return None
    result = next((item for item in flower["passes"] if item.get("pass_id") == pass_id), None)
    if result is None:
        return None
    evidence = []
    for item in dataset.get("roller_station_evidence", []) or dataset.get("historical_roller_station_evidence", []):
        if item.get("flower_id") != flower_id or item.get("pass_id") != pass_id or not item.get("design_id"):
            continue
        role = str(item.get("role") or "UNKNOWN")
        revision = item.get("geometry_revision_id")
        evidence.append({
            "role": role, "design_id": item.get("design_id"),
            "geometry_revision_id": revision,
            "confirmation_status": item.get("confirmation_status"),
            "recognition_status": item.get("recognition_status"),
            "recognition_score": item.get("recognition_score"),
            "evidence_coverage": item.get("evidence_coverage"),
            "source_reference_id": source_reference_id(str(dataset.get("dataset_hash") or "UNCONFIGURED"), flower_id, pass_id, role, str(item.get("design_id")), revision),
        })
    result["display_order"] = int(result.get("inferred_order", 0)) + 1
    result["geometry"] = {"points": result.get("points") or result.get("normalized_points") or [], "shape_vector": result.get("shape_vector") or []}
    result["roller_roles"] = [{"role": role, "designs": sorted([row for row in evidence if row["role"] == role], key=lambda row: (str(row["design_id"]), str(row["geometry_revision_id"] or "")))} for role in sorted({row["role"] for row in evidence})]
    result["manufacturing_approval"] = "NOT_APPROVED"
    result["physical_asset_assignment"] = False
    return result
