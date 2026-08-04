"""Offline DWG/DXF import adapter for the visual flower workflow.

This module deliberately reuses the repository converter and ezdxf reader. It
stores only redacted import metadata and derived profile JSON in the web
workspace; source CAD remains in the private staging directory.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import ezdxf

from rollform_extractor.converter import ConversionUnavailableError, stage_input
from rollform_extractor.dxf_reader import inspect_drawing


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _state_path(root: Path, import_id: str) -> Path:
    return root / "visual_imports" / import_id / "import.json"


def _profile_from_points(profile_id: str, points: list[tuple[float, float]], closed: bool, warnings: list[str], entity_type: str, handle: str) -> dict[str, Any] | None:
    if len(points) < 2:
        return None
    vertices = [{"vertex_id": f"{profile_id}-v-{index + 1:04d}", "x": round(float(x), 8), "y": round(float(y), 8)} for index, (x, y) in enumerate(points)]
    segments = [{"segment_id": f"{profile_id}-s-{index + 1:04d}", "type": "LINE", "start_vertex_id": vertices[index]["vertex_id"], "end_vertex_id": vertices[index + 1]["vertex_id"]} for index in range(len(vertices) - 1)]
    topology = "CLOSED_CONTOUR" if closed else "OPEN_PATH"
    if closed:
        segments.append({"segment_id": f"{profile_id}-s-{len(segments) + 1:04d}", "type": "LINE", "start_vertex_id": vertices[-1]["vertex_id"], "end_vertex_id": vertices[0]["vertex_id"]})
    return {"schema_version": 1, "profile_id": profile_id, "name": f"Imported profile {profile_id}", "topology": topology, "closed": closed, "computational_seam_vertex_id": vertices[0]["vertex_id"] if closed else None, "vertices": vertices, "segments": segments, "metadata": {"source": "OFFLINE_CAD_IMPORT", "visual_only": True, "entity_type": entity_type, "source_handle": handle, "warnings": sorted(set(warnings))}}


def _points(entity) -> list[tuple[float, float]]:
    if entity.dxftype() == "LWPOLYLINE":
        return [(float(point[0]), float(point[1])) for point in entity.get_points("xy")]
    if entity.dxftype() == "POLYLINE":
        return [(float(vertex.dxf.location.x), float(vertex.dxf.location.y)) for vertex in entity.vertices]
    if entity.dxftype() == "LINE":
        return [(float(entity.dxf.start.x), float(entity.dxf.start.y)), (float(entity.dxf.end.x), float(entity.dxf.end.y))]
    return []


def _profile_candidates(dxf_path: Path) -> list[dict[str, Any]]:
    document = ezdxf.readfile(dxf_path)
    candidates: list[dict[str, Any]] = []
    for index, entity in enumerate(document.modelspace(), start=1):
        if entity.dxftype() not in {"LWPOLYLINE", "POLYLINE", "LINE"}:
            continue
        points = _points(entity)
        warnings: list[str] = []
        if entity.dxftype() == "LWPOLYLINE" and any(abs(float(point[4] or 0.0)) > 1e-12 for point in entity.get_points("xyseb")):
            warnings.append("BULGE_ARC_APPROXIMATED_AS_POLYLINE")
        closed = bool(getattr(entity.dxf, "closed", False))
        if len(points) > 2 and (abs(points[0][0] - points[-1][0]) < 1e-8 and abs(points[0][1] - points[-1][1]) < 1e-8):
            closed = True
            points = points[:-1]
        profile = _profile_from_points(f"cad-profile-{index:04d}", points, closed, warnings, entity.dxftype(), str(entity.dxf.handle))
        if not profile:
            continue
        xs = [point["x"] for point in profile["vertices"]]; ys = [point["y"] for point in profile["vertices"]]
        width = max(xs) - min(xs); height = max(ys) - min(ys)
        profile["metadata"].update({"entity_count": 1, "width": width, "height": height, "aspect_ratio": width / height if height else None})
        candidates.append({"profile_id": profile["profile_id"], "profile": profile, "candidate_id": profile["profile_id"], "open_closed": profile["topology"], "entity_count": 1, "width": width, "height": height, "aspect_ratio": profile["metadata"]["aspect_ratio"], "warnings": profile["metadata"]["warnings"], "thumbnail_svg": thumbnail_svg(profile)})
    return candidates


def thumbnail_svg(profile: dict[str, Any]) -> str:
    points = profile.get("vertices", [])
    if not points:
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'></svg>"
    xs = [float(point["x"]) for point in points]; ys = [float(point["y"]) for point in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    width = max(max_x - min_x, 1e-6); height = max(max_y - min_y, 1e-6)
    coords = " ".join(f"{(float(point['x']) - min_x) / width * 100:.3f},{100 - (float(point['y']) - min_y) / height * 100:.3f}" for point in points)
    return f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100' role='img' aria-label='Imported profile'><polyline points='{coords}' fill='none' stroke='#155783' stroke-width='2' /></svg>"


def create_import(root: Path, filename: str, data: bytes) -> dict[str, Any]:
    safe_name = Path(filename or "profile.dxf").name
    if Path(safe_name).suffix.lower() not in {".dxf", ".dwg"}:
        raise ValueError("only .dxf and .dwg files are supported")
    import_id = "vimport-" + uuid4().hex[:16]
    directory = root / "visual_imports" / import_id
    source = directory / safe_name
    directory.mkdir(parents=True, exist_ok=False)
    source.write_bytes(data)
    try:
        staged = stage_input(source, directory / "staged")
        inspection = inspect_drawing(staged.converted_file).to_dict()
        profiles = _profile_candidates(staged.converted_file)
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "converter": staged.converter, "inspection": {"units": inspection.get("units"), "modelspace_entity_count": inspection.get("modelspace_entity_count"), "layers": sorted(inspection.get("layers", {})), "private_paths_redacted": True}, "status": "PROFILES_READY" if profiles else "NO_PROFILES", "profiles": profiles, "source_not_exported": True}
    except ConversionUnavailableError as exc:
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "status": "FAILED", "profiles": [], "error_code": "CONVERSION_UNAVAILABLE", "error": str(exc), "private_paths_redacted": True, "source_not_exported": True}
    except Exception:
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "status": "FAILED", "profiles": [], "error_code": "CAD_IMPORT_FAILED", "error": "offline CAD import failed; inspect server diagnostics without exposing source paths", "private_paths_redacted": True, "source_not_exported": True}
    _state_path(root, import_id).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return summary(state)


def summary(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "profiles"} | {"profile_count": len(state.get("profiles", []))}


def get_import(root: Path, import_id: str) -> dict[str, Any] | None:
    path = _state_path(root, import_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles(root: Path, import_id: str) -> list[dict[str, Any]] | None:
    state = get_import(root, import_id)
    return None if state is None else [{key: value for key, value in item.items() if key != "profile"} for item in state.get("profiles", [])]


def selected_profile(root: Path, import_id: str, profile_id: str) -> dict[str, Any] | None:
    state = get_import(root, import_id)
    if state is None:
        return None
    for item in state.get("profiles", []):
        if item.get("profile_id") == profile_id:
            return item["profile"]
    return None
