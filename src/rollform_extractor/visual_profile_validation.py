"""Authoritative, visual-only geometry validation for target profiles."""
from __future__ import annotations

import math
from hashlib import sha256
import json
from typing import Any

from rollform_extractor.visual_profile_schema import VisualProfileError, validate_profile


VISUAL_PROFILE_VALIDATION_VERSION = "visual-profile-validation-v1"


def _arc_sweep(start_angle: float, end_angle: float, clockwise: bool) -> float:
    return ((start_angle - end_angle) if clockwise else (end_angle - start_angle)) % (2 * math.pi)


def validate_visual_profile(value: dict[str, Any]) -> dict[str, Any]:
    profile_hash = sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()
    checks = {key: False for key in (
        "schema", "finite_coordinates", "unique_vertex_ids", "unique_segment_ids",
        "segment_references", "zero_length_segments", "path_connectivity", "topology",
        "computational_seam", "arc_geometry", "nonzero_developed_length",
    )}
    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    try:
        profile = validate_profile(value)
        checks["schema"] = True
        checks["finite_coordinates"] = True
        checks["unique_vertex_ids"] = True
        checks["segment_references"] = True
        checks["zero_length_segments"] = True
        checks["computational_seam"] = True
        checks["topology"] = True
    except VisualProfileError as exc:
        errors.append({"code": exc.code, "message": exc.message})
        return {"valid": False, "profile_hash": profile_hash, "blocking_errors": errors, "warnings": warnings, "checks": checks, "validation_version": VISUAL_PROFILE_VALIDATION_VERSION, "manufacturing_approval": "NOT_APPROVED"}
    segments = list(profile.segments)
    segment_ids = [str(item.get("segment_id")) for item in segments]
    checks["unique_segment_ids"] = len(segment_ids) == len(set(segment_ids)) and all(
        isinstance(item.get("segment_id"), str) and bool(item.get("segment_id", "").strip())
        for item in segments
    )
    if not checks["unique_segment_ids"]:
        errors.append({"code": "INVALID_SEGMENT_IDS", "message": "segment IDs must be unique non-empty strings"})
    points = {item["vertex_id"]: (float(item["x"]), float(item["y"])) for item in profile.vertices}
    adjacency = {key: set() for key in points}
    length = 0.0
    all_arcs_valid = True
    for segment in segments:
        start, end = points[segment["start_vertex_id"]], points[segment["end_vertex_id"]]
        adjacency[segment["start_vertex_id"]].add(segment["end_vertex_id"])
        adjacency[segment["end_vertex_id"]].add(segment["start_vertex_id"])
        if math.dist(start, end) <= 1e-9:
            checks["zero_length_segments"] = False
            errors.append({"code": "ZERO_LENGTH_SEGMENT", "message": f"segment {segment.get('segment_id')} has coincident endpoints"})
        if segment["type"] == "LINE":
            length += math.dist(start, end)
        else:
            center = segment.get("center")
            radius = float(segment.get("radius", 0))
            valid_arc = (isinstance(center, dict) and all(isinstance(center.get(key), (int, float)) and math.isfinite(float(center[key])) for key in ("x", "y")) and math.isfinite(radius) and radius > 0 and abs(math.dist(start, (float(center["x"]), float(center["y"]))) - radius) <= max(1e-5, radius * 1e-4) and abs(math.dist(end, (float(center["x"]), float(center["y"]))) - radius) <= max(1e-5, radius * 1e-4))
            if not valid_arc:
                all_arcs_valid = False
                errors.append({"code": "DEGENERATE_ARC", "message": f"arc {segment.get('segment_id')} center/radius does not match endpoints"})
            else:
                checks["arc_geometry"] = True
                length += radius * _arc_sweep(math.atan2(start[1] - float(center["y"]), start[0] - float(center["x"])), math.atan2(end[1] - float(center["y"]), end[0] - float(center["x"])), bool(segment.get("clockwise", False)))
    checks["arc_geometry"] = all_arcs_valid
    if len(profile.vertices) and all(len(value) <= 2 for value in adjacency.values()):
        seen: set[str] = set(); stack = [next(iter(points))]
        while stack:
            current = stack.pop()
            if current in seen: continue
            seen.add(current); stack.extend(adjacency[current] - seen)
        checks["path_connectivity"] = len(seen) == len(points)
    if not checks["path_connectivity"]:
        errors.append({"code": "DISCONNECTED_PROFILE", "message": "profile segments must form one connected path"})
    degrees = [len(value) for value in adjacency.values()]
    if profile.topology == "OPEN_PATH":
        checks["topology"] = checks["path_connectivity"] and degrees.count(1) == 2 and all(value in {1, 2} for value in degrees)
        if not checks["topology"]:
            errors.append({"code": "INVALID_OPEN_TOPOLOGY", "message": "open profiles require a connected non-branching path with two endpoints"})
    else:
        checks["topology"] = checks["path_connectivity"] and all(value == 2 for value in degrees)
        if not checks["topology"]:
            errors.append({"code": "INVALID_CLOSED_TOPOLOGY", "message": "closed contours require a connected cycle with no endpoints"})
    checks["nonzero_developed_length"] = length > 1e-9
    if not checks["nonzero_developed_length"]:
        errors.append({"code": "ZERO_DEVELOPED_LENGTH", "message": "profile developed length must be positive"})
    if profile.metadata.get("unit_status") == "UNKNOWN":
        warnings.append("UNKNOWN_DXF_UNITS")
    return {"valid": not errors, "profile_hash": profile_hash, "blocking_errors": errors, "warnings": sorted(set(warnings)), "checks": checks, "normalized_profile": profile.to_dict(), "validation_version": VISUAL_PROFILE_VALIDATION_VERSION, "manufacturing_approval": "NOT_APPROVED"}
