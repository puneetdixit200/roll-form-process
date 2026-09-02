"""Versioned visual-only profile input contract."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


VISUAL_PROFILE_SCHEMA_VERSION = 1
VISUAL_ALGORITHM_VERSION = "visual_sketch_history_match_v2_constant_length"
TOPOLOGIES = {"OPEN_PATH", "CLOSED_CONTOUR"}


class VisualProfileError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VisualProfile:
    profile_id: str
    name: str
    topology: str
    vertices: tuple[dict[str, Any], ...]
    segments: tuple[dict[str, Any], ...]
    computational_seam_vertex_id: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VISUAL_PROFILE_SCHEMA_VERSION,
            "profile_id": self.profile_id,
            "name": self.name,
            "coordinate_system": {"x_axis": "right", "y_axis": "up", "units": "VISUAL_UNIT"},
            "topology": self.topology,
            "closed": self.topology == "CLOSED_CONTOUR",
            "computational_seam_vertex_id": self.computational_seam_vertex_id,
            "vertices": [dict(item) for item in self.vertices],
            "segments": [dict(item) for item in self.segments],
            "metadata": {**self.metadata, "visual_only": True},
        }


def validate_profile(value: dict[str, Any]) -> VisualProfile:
    if not isinstance(value, dict) or value.get("schema_version") != VISUAL_PROFILE_SCHEMA_VERSION:
        raise VisualProfileError("UNKNOWN_SCHEMA_VERSION", "profile schema_version must be 1")
    topology = value.get("topology")
    if topology not in TOPOLOGIES:
        raise VisualProfileError("INVALID_PROFILE", "topology must be OPEN_PATH or CLOSED_CONTOUR")
    vertices = tuple(value.get("vertices") or ())
    segments = tuple(value.get("segments") or ())
    if len(vertices) < 2 or len(segments) < 1:
        raise VisualProfileError("INVALID_PROFILE", "profile requires at least two vertices and one segment")
    vertex_ids = [item.get("vertex_id") for item in vertices]
    if any(not isinstance(item, str) for item in vertex_ids) or len(set(vertex_ids)) != len(vertex_ids):
        raise VisualProfileError("INVALID_PROFILE", "vertex IDs must be unique strings")
    for vertex in vertices:
        if not all(isinstance(vertex.get(key), (int, float)) and math.isfinite(float(vertex[key])) for key in ("x", "y")):
            raise VisualProfileError("INVALID_PROFILE", "vertex coordinates must be finite numbers")
    for segment in segments:
        segment_id = segment.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise VisualProfileError("INVALID_SEGMENT_ID", "segment_id must be a non-empty string")
        if segment.get("start_vertex_id") not in vertex_ids or segment.get("end_vertex_id") not in vertex_ids:
            raise VisualProfileError("INVALID_SEGMENT_REFERENCE", "segment references an unknown vertex")
        if segment.get("start_vertex_id") == segment.get("end_vertex_id"):
            raise VisualProfileError("ZERO_LENGTH_SEGMENT", "a segment cannot start and end at the same vertex")
        if segment.get("type") not in {"LINE", "ARC"}:
            raise VisualProfileError("INVALID_PROFILE", "segment type must be LINE or ARC")
        if segment.get("type") == "ARC":
            center = segment.get("center")
            radius = segment.get("radius")
            if (not isinstance(center, dict) or not all(isinstance(center.get(key), (int, float)) and math.isfinite(float(center[key])) for key in ("x", "y")) or not isinstance(radius, (int, float)) or not math.isfinite(float(radius)) or float(radius) <= 0):
                raise VisualProfileError("DEGENERATE_ARC", "arc requires a positive radius and center")
    seam = value.get("computational_seam_vertex_id")
    if topology == "CLOSED_CONTOUR" and seam not in vertex_ids:
        raise VisualProfileError("SEAM_REQUIRED", "closed contours require a computational seam vertex")
    return VisualProfile(
        profile_id=str(value.get("profile_id") or "visual-target"),
        name=str(value.get("name") or "Visual target"),
        topology=topology,
        vertices=tuple({"vertex_id": str(item["vertex_id"]), "x": round(float(item["x"]), 8), "y": round(float(item["y"]), 8)} for item in vertices),
        segments=tuple(dict(item) for item in segments),
        computational_seam_vertex_id=seam,
        metadata=dict(value.get("metadata") or {}),
    )


def stable_profile_json(profile: VisualProfile) -> str:
    return json.dumps(profile.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
