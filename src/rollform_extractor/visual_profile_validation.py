"""Authoritative, visual-only geometry validation for target profiles."""
from __future__ import annotations

import math
from typing import Any

from rollform_extractor.visual_profile_schema import VisualProfileError, validate_profile


VISUAL_PROFILE_VALIDATION_VERSION = "visual-profile-validation-v1"


def validate_visual_profile(value: dict[str, Any]) -> dict[str, Any]:
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
        return {"valid": False, "blocking_errors": errors, "warnings": warnings, "checks": checks, "validation_version": VISUAL_PROFILE_VALIDATION_VERSION, "manufacturing_approval": "NOT_APPROVED"}
    segments = list(profile.segments)
    segment_ids = [str(item.get("segment_id")) for item in segments]
    checks["unique_segment_ids"] = len(segment_ids) == len(set(segment_ids))
    if not checks["unique_segment_ids"]:
        errors.append({"code": "DUPLICATE_SEGMENT_IDS", "message": "segment IDs must be unique"})
    points = {item["vertex_id"]: (float(item["x"]), float(item["y"])) for item in profile.vertices}
    adjacency = {key: set() for key in points}
    length = 0.0
    for segment in segments:
        start, end = points[segment["start_vertex_id"]], points[segment["end_vertex_id"]]
        adjacency[segment["start_vertex_id"]].add(segment["end_vertex_id"])
        adjacency[segment["end_vertex_id"]].add(segment["start_vertex_id"])
        if segment["type"] == "LINE":
            length += math.dist(start, end)
        else:
            center = segment.get("center")
            radius = float(segment.get("radius", 0))
            valid_arc = isinstance(center, dict) and radius > 0 and abs(math.dist(start, (float(center["x"]), float(center["y"]))) - radius) <= max(1e-5, radius * 1e-4) and abs(math.dist(end, (float(center["x"]), float(center["y"]))) - radius) <= max(1e-5, radius * 1e-4)
            if not valid_arc:
                errors.append({"code": "DEGENERATE_ARC", "message": f"arc {segment.get('segment_id')} center/radius does not match endpoints"})
            else:
                checks["arc_geometry"] = True
                length += radius * abs(math.atan2(end[1] - float(center["y"]), end[0] - float(center["x"])) - math.atan2(start[1] - float(center["y"]), start[0] - float(center["x"])))
    if not any(segment["type"] == "ARC" for segment in segments):
        checks["arc_geometry"] = True
    if len(profile.vertices) and all(len(value) <= 2 for value in adjacency.values()):
        seen: set[str] = set(); stack = [next(iter(points))]
        while stack:
            current = stack.pop()
            if current in seen: continue
            seen.add(current); stack.extend(adjacency[current] - seen)
        checks["path_connectivity"] = len(seen) == len(points)
    if not checks["path_connectivity"]:
        errors.append({"code": "DISCONNECTED_PROFILE", "message": "profile segments must form one connected path"})
    checks["nonzero_developed_length"] = length > 1e-9
    if not checks["nonzero_developed_length"]:
        errors.append({"code": "ZERO_DEVELOPED_LENGTH", "message": "profile developed length must be positive"})
    if profile.metadata.get("unit_status") == "UNKNOWN":
        warnings.append("UNKNOWN_DXF_UNITS")
    return {"valid": not errors, "blocking_errors": errors, "warnings": sorted(set(warnings)), "checks": checks, "normalized_profile": profile.to_dict(), "validation_version": VISUAL_PROFILE_VALIDATION_VERSION, "manufacturing_approval": "NOT_APPROVED"}
