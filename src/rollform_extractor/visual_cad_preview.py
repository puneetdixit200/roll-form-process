"""Safe, vector-only preview data for an imported CAD drawing."""
from __future__ import annotations

from hashlib import sha256
import math
from pathlib import Path
from typing import Any

import ezdxf

from rollform_extractor.visual_cad_profile_detection import _entity_geometry


DXF_DRAWING_PREVIEW_VERSION = "visual-dxf-preview-v1"


def _point(value: Any) -> list[float]:
    return [round(float(value[0]), 8), round(float(value[1]), 8)]


def _arc_points(center: list[float], radius: float, start: list[float], end: list[float], clockwise: bool) -> list[list[float]]:
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    delta = a1 - a0
    if clockwise and delta > 0:
        delta -= 2 * math.pi
    if not clockwise and delta < 0:
        delta += 2 * math.pi
    values = [a0, a0 + delta]
    for candidate in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
        traveled = (candidate - a0) % (2 * math.pi) if not clockwise else (a0 - candidate) % (2 * math.pi)
        sweep = delta % (2 * math.pi) if not clockwise else (-delta) % (2 * math.pi)
        if traveled <= sweep + 1e-12:
            values.append(candidate)
    return [[round(center[0] + radius * math.cos(angle), 8), round(center[1] + radius * math.sin(angle), 8)] for angle in values]


def _bounds(primitives: list[dict[str, Any]]) -> dict[str, float]:
    points: list[list[float]] = []
    for item in primitives:
        if item["type"] in {"LINE", "ARC"}:
            points.extend([item["start"], item["end"]])
            if item["type"] == "ARC":
                points.extend(_arc_points(item["center"], item["radius"], item["start"], item["end"], item["clockwise"]))
        elif item["type"] == "CIRCLE":
            x, y = item["center"]
            r = item["radius"]
            points.extend([[x - r, y - r], [x + r, y + r]])
        elif item["type"] == "ELLIPSE":
            points.extend(item["bounds"])
        elif item["type"] == "POLYLINE":
            points.extend(item["points"])
    if not points:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0, "width": 1.0, "height": 1.0}
    xs, ys = zip(*points)
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    return {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y, "width": max(max_x - min_x, 1e-9), "height": max(max_y - min_y, 1e-9)}


def build_drawing_preview(path: Path, import_id: str, source_sha256: str) -> dict[str, Any]:
    document = ezdxf.readfile(path)
    units_code = int(document.header.get("$INSUNITS", 0) or 0)
    unit_names = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
    units = unit_names.get(units_code)
    entities = list(document.modelspace())
    primitives: list[dict[str, Any]] = []
    unsupported: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    for index, entity in enumerate(entities):
        kind = entity.dxftype()
        layer = str(getattr(entity.dxf, "layer", "0"))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        geometry = _entity_geometry(entity)
        primitive_id = f"primitive-{index + 1:06d}-{sha256(str(getattr(entity.dxf, 'handle', index)).encode()).hexdigest()[:10]}"
        if geometry and geometry["type"] in {"LINE", "ARC"}:
            item = {"primitive_id": primitive_id, "source_handle": geometry["handle"], "layer": layer, "type": geometry["type"], "start": list(geometry["start"]), "end": list(geometry["end"])}
            if geometry["type"] == "ARC":
                item.update({"center": [geometry["center"]["x"], geometry["center"]["y"]], "radius": geometry["radius"], "clockwise": geometry["clockwise"]})
            primitives.append(item)
        elif geometry and geometry["type"] == "POLYLINE":
            primitives.append({"primitive_id": primitive_id, "source_handle": geometry["handle"], "layer": layer, "type": "POLYLINE", "points": [list(item) for item in geometry["points"]], "bulges": geometry.get("bulges", []), "closed": geometry.get("closed", False)})
        elif kind == "CIRCLE":
            primitives.append({"primitive_id": primitive_id, "source_handle": str(getattr(entity.dxf, "handle", "")), "layer": layer, "type": "CIRCLE", "center": _point(entity.dxf.center), "radius": round(float(entity.dxf.radius), 8)})
        elif kind == "ELLIPSE":
            center = _point(entity.dxf.center)
            major = _point(entity.dxf.major_axis)
            rx = math.hypot(major[0], major[1])
            ry = abs(rx * float(entity.dxf.ratio))
            primitives.append({"primitive_id": primitive_id, "source_handle": str(getattr(entity.dxf, "handle", "")), "layer": layer, "type": "ELLIPSE", "center": center, "radius_x": rx, "radius_y": ry, "bounds": [[center[0] - rx, center[1] - ry], [center[0] + rx, center[1] + ry]]})
        else:
            unsupported[kind] = unsupported.get(kind, 0) + 1
    primitives.sort(key=lambda item: item["primitive_id"])
    warnings = [f"UNSUPPORTED_{kind}_ENTITIES" for kind in sorted(unsupported)]
    return {"schema_version": 1, "preview_version": DXF_DRAWING_PREVIEW_VERSION, "import_id": import_id, "source_sha256": source_sha256, "units": units, "unit_status": "CONFIRMED" if units else "UNKNOWN", "bounds": _bounds(primitives), "layers": [{"name": name, "visible_by_default": True, "entity_count": layer_counts[name]} for name in sorted(layer_counts)], "primitives": primitives, "unsupported_entity_counts": dict(sorted(unsupported.items())), "modelspace_entity_count": len(entities), "supported_primitive_count": len(primitives), "warnings": warnings, "private_paths_redacted": True, "source_cad_included": False}
