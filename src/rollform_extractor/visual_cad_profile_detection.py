"""Deterministic connected-profile discovery for visual CAD imports.

This deliberately sits between DXF parsing and the visual-profile contract.
It groups connected source entities; it does not attempt to reinterpret title
blocks or manufacture geometry from disconnected drawing fragments.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import math
from pathlib import Path
from typing import Any

import ezdxf


DXF_PROFILE_DETECTOR_VERSION = "visual-cad-profile-v2"


def _point(value: Any) -> tuple[float, float]:
    return (round(float(value[0]), 8), round(float(value[1]), 8))


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _units(document: Any) -> tuple[str | None, str]:
    value = int(document.header.get("$INSUNITS", 0) or 0)
    names = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
    return names.get(value), "CONFIRMED" if value in names else "UNKNOWN"


def _entity_geometry(entity: Any) -> dict[str, Any] | None:
    kind = entity.dxftype()
    handle = str(getattr(entity.dxf, "handle", ""))
    layer = str(getattr(entity.dxf, "layer", "0"))
    if kind == "LINE":
        return {"type": "LINE", "start": _point(entity.dxf.start), "end": _point(entity.dxf.end), "handle": handle, "layer": layer}
    if kind == "ARC":
        center = _point(entity.dxf.center)
        radius = round(float(entity.dxf.radius), 8)
        start = math.radians(float(entity.dxf.start_angle))
        end = math.radians(float(entity.dxf.end_angle))
        return {
            "type": "ARC",
            "start": (round(center[0] + radius * math.cos(start), 8), round(center[1] + radius * math.sin(start), 8)),
            "end": (round(center[0] + radius * math.cos(end), 8), round(center[1] + radius * math.sin(end), 8)),
            "center": {"x": center[0], "y": center[1]},
            "radius": radius,
            "clockwise": False,
            "handle": handle,
            "layer": layer,
        }
    if kind in {"LWPOLYLINE", "POLYLINE"}:
        if kind == "LWPOLYLINE":
            points = [_point(item) for item in entity.get_points("xy")]
            bulges = [float(item[4] or 0.0) for item in entity.get_points("xyseb")]
            closed = bool(entity.closed)
        else:
            points = [_point(vertex.dxf.location) for vertex in entity.vertices]
            bulges = [float(getattr(vertex.dxf, "bulge", 0.0) or 0.0) for vertex in entity.vertices]
            closed = bool(getattr(entity, "is_closed", False))
        if len(points) < 2:
            return None
        return {
            "type": "POLYLINE",
            "start": points[0],
            "end": points[0] if closed else points[-1],
            "points": points,
            "closed": closed,
            "bulges": bulges,
            "handle": handle,
            "layer": layer,
        }
    return None


def _connection_tolerance(entities: list[dict[str, Any]]) -> float:
    points = [point for item in entities for point in (item["start"], item["end"])]
    if not points:
        return 1e-6
    width = max(point[0] for point in points) - min(point[0] for point in points)
    height = max(point[1] for point in points) - min(point[1] for point in points)
    return max(1e-6, max(width, height, 1.0) * 1e-6)


def _endpoint_nodes(entities: list[dict[str, Any]], tolerance: float) -> list[tuple[int, int]]:
    """Cluster endpoints by real Euclidean distance, not quantization equality."""
    endpoints: list[tuple[float, float]] = []
    for entity in entities:
        endpoints.extend((entity["start"], entity["end"]))
    parent = list(range(len(endpoints)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, point in enumerate(endpoints):
        cell = (math.floor(point[0] / tolerance), math.floor(point[1] / tolerance))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cell[0] + dx, cell[1] + dy), []):
                    if _distance(point, endpoints[other]) <= tolerance:
                        union(index, other)
        buckets[cell].append(index)

    return [(find(2 * index), find(2 * index + 1)) for index in range(len(entities))]


def _components(entities: list[dict[str, Any]], tolerance: float) -> list[list[dict[str, Any]]]:
    nodes = _endpoint_nodes(entities, tolerance)
    node_entities: dict[int, list[int]] = defaultdict(list)
    for index, (start_node, end_node) in enumerate(nodes):
        node_entities[start_node].append(index)
        node_entities[end_node].append(index)
    parent = list(range(len(entities)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    for indexes in node_entities.values():
        for index in indexes[1:]:
            union(indexes[0], index)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, entity in enumerate(entities):
        grouped[find(index)].append(entity)
    return [sorted(items, key=lambda item: (item["handle"], item["type"])) for _, items in sorted(grouped.items())]


def _ordered(component: list[dict[str, Any]], tolerance: float) -> tuple[list[tuple[dict[str, Any], bool]], bool, bool]:
    """Return entities with reversal flags, branched state, and closed state."""
    nodes = _endpoint_nodes(component, tolerance)
    adjacency: dict[int, list[int]] = defaultdict(list)
    for index, (start_node, end_node) in enumerate(nodes):
        adjacency[start_node].append(index)
        adjacency[end_node].append(index)
    degree = {key: len(value) for key, value in adjacency.items()}
    branched = any(value > 2 for value in degree.values())
    start = next((key for key, value in sorted(degree.items()) if value == 1), min(degree))
    closed = not branched and all(value == 2 for value in degree.values())
    output: list[tuple[dict[str, Any], bool]] = []
    used: set[int] = set()
    node = start
    while len(used) < len(component):
        choices = [index for index in adjacency[node] if index not in used]
        if not choices:
            choices = [index for index in range(len(component)) if index not in used]
            if not choices:
                break
            node = nodes[choices[0]][0]
        index = min(choices, key=lambda value: (component[value]["handle"], component[value]["type"]))
        item = component[index]
        start_node, end_node = nodes[index]
        reversed_item = end_node == node and start_node != node
        output.append((item, reversed_item))
        used.add(index)
        node = start_node if reversed_item else end_node
    return output, branched, closed


def _bulge_arc(start: tuple[float, float], end: tuple[float, float], bulge: float) -> dict[str, Any]:
    """Convert a DXF bulge segment exactly into the visual ARC contract."""
    chord = _distance(start, end)
    if chord <= 1e-12 or abs(bulge) <= 1e-12:
        raise ValueError("degenerate bulge arc")
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    dx, dy = end[0] - start[0], end[1] - start[1]
    left_normal = (-dy / chord, dx / chord)
    center_offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge)
    center = (
        midpoint[0] + left_normal[0] * center_offset,
        midpoint[1] + left_normal[1] * center_offset,
    )
    radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    return {
        "center": {"x": round(center[0], 8), "y": round(center[1], 8)},
        "radius": round(radius, 8),
        "clockwise": bulge < 0,
    }


def _polyline_segments(entity: dict[str, Any], reversed_item: bool) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    points = list(entity["points"])
    bulges = list(entity.get("bulges") or [])
    if len(bulges) < len(points):
        bulges.extend([0.0] * (len(points) - len(bulges)))
    segments = [(points[index], points[index + 1], bulges[index]) for index in range(len(points) - 1)]
    if entity.get("closed"):
        segments.append((points[-1], points[0], bulges[-1]))
    if reversed_item:
        segments = [(end, start, -bulge) for start, end, bulge in reversed(segments)]
    return segments


def _profile(component: list[dict[str, Any]], tolerance: float, units: str | None, unit_status: str) -> dict[str, Any]:
    ordered, branched, closed = _ordered(component, tolerance)
    identity = sha256("|".join(item["handle"] for item, _ in ordered).encode()).hexdigest()[:16]
    profile_id = f"cad-profile-{identity}"
    vertices: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    warnings: list[str] = []
    source_handles = [item["handle"] for item, _ in ordered]
    source_layers = sorted({item["layer"] for item, _ in ordered})

    def vertex(point: tuple[float, float]) -> str:
        vertex_id = f"{profile_id}-v-{len(vertices) + 1:04d}"
        vertices.append({"vertex_id": vertex_id, "x": point[0], "y": point[1]})
        return vertex_id

    def connected_vertex(point: tuple[float, float], previous: str | None) -> str:
        if previous is not None:
            prior = vertices[-1]
            if _distance((float(prior["x"]), float(prior["y"])), point) <= tolerance:
                return previous
        return vertex(point)

    previous: str | None = None
    for entity, reversed_item in ordered:
        if entity["type"] == "POLYLINE":
            for start, end, bulge in _polyline_segments(entity, reversed_item):
                start_id = connected_vertex(start, previous)
                end_id = vertex(end)
                segment = {
                    "segment_id": f"{profile_id}-s-{len(segments) + 1:04d}",
                    "type": "LINE" if abs(bulge) <= 1e-12 else "ARC",
                    "start_vertex_id": start_id,
                    "end_vertex_id": end_id,
                }
                if abs(bulge) > 1e-12:
                    segment.update(_bulge_arc(start, end, bulge))
                segments.append(segment)
                previous = end_id
            continue
        start, end = (entity["end"], entity["start"]) if reversed_item else (entity["start"], entity["end"])
        start_id = connected_vertex(start, previous)
        end_id = vertex(end)
        segment = {
            "segment_id": f"{profile_id}-s-{len(segments) + 1:04d}",
            "type": entity["type"],
            "start_vertex_id": start_id,
            "end_vertex_id": end_id,
        }
        if entity["type"] == "ARC":
            segment.update({"center": entity["center"], "radius": entity["radius"], "clockwise": bool(entity["clockwise"]) ^ reversed_item})
        segments.append(segment)
        previous = end_id

    if closed and vertices and segments:
        first_id = vertices[0]["vertex_id"]
        last_id = segments[-1]["end_vertex_id"]
        first_point = (float(vertices[0]["x"]), float(vertices[0]["y"]))
        last_vertex = next(item for item in vertices if item["vertex_id"] == last_id)
        last_point = (float(last_vertex["x"]), float(last_vertex["y"]))
        if last_id != first_id and _distance(last_point, first_point) <= tolerance:
            segments[-1]["end_vertex_id"] = first_id
            if last_id == vertices[-1]["vertex_id"]:
                vertices.pop()
        elif last_id != first_id:
            segments.append({
                "segment_id": f"{profile_id}-s-{len(segments) + 1:04d}",
                "type": "LINE",
                "start_vertex_id": last_id,
                "end_vertex_id": first_id,
            })
    if branched:
        warnings.append("BRANCHED_PROFILE_REVIEW_REQUIRED")
    if unit_status == "UNKNOWN":
        warnings.append("UNKNOWN_DXF_UNITS")
    xs, ys = [item["x"] for item in vertices], [item["y"] for item in vertices]
    width, height = (max(xs) - min(xs), max(ys) - min(ys)) if vertices else (0.0, 0.0)
    profile = {
        "schema_version": 1,
        "profile_id": profile_id,
        "name": f"Imported profile {profile_id}",
        "topology": "CLOSED_CONTOUR" if closed else "OPEN_PATH",
        "closed": closed,
        "computational_seam_vertex_id": vertices[0]["vertex_id"] if closed and vertices else None,
        "vertices": vertices,
        "segments": segments,
        "metadata": {
            "source": "OFFLINE_CAD_IMPORT",
            "visual_only": True,
            "entity_count": len(component),
            "source_handles": source_handles,
            "source_layers": source_layers,
            "source_units": units,
            "unit_status": unit_status,
            "connection_tolerance": tolerance,
            "warnings": sorted(set(warnings)),
            "detector_version": DXF_PROFILE_DETECTOR_VERSION,
        },
    }
    score = len(component) * 10 + min(len(segments), 20) - (100 if branched else 0)
    return {
        "profile_id": profile_id,
        "candidate_id": profile_id,
        "profile": profile,
        "open_closed": profile["topology"],
        "entity_count": len(component),
        "width": width,
        "height": height,
        "aspect_ratio": width / height if height else None,
        "source_layers": source_layers,
        "source_handles": source_handles,
        "source_units": units,
        "unit_status": unit_status,
        "candidate_score": score,
        "warnings": profile["metadata"]["warnings"],
        "thumbnail_svg": thumbnail_svg(profile),
    }


def detect_profiles(dxf_path: Path) -> list[dict[str, Any]]:
    document = ezdxf.readfile(dxf_path)
    entities = [item for entity in document.modelspace() if (item := _entity_geometry(entity)) is not None]
    tolerance = _connection_tolerance(entities)
    units, unit_status = _units(document)
    candidates = [_profile(component, tolerance, units, unit_status) for component in _components(entities, tolerance)]
    return sorted(candidates, key=lambda item: (-item["candidate_score"], item["profile_id"]))


def _arc_sweep(start: tuple[float, float], end: tuple[float, float], center: dict[str, Any], clockwise: bool) -> float:
    start_angle = math.atan2(start[1] - float(center["y"]), start[0] - float(center["x"]))
    end_angle = math.atan2(end[1] - float(center["y"]), end[0] - float(center["x"]))
    sweep = end_angle - start_angle
    if clockwise and sweep > 0:
        sweep -= 2 * math.pi
    if not clockwise and sweep < 0:
        sweep += 2 * math.pi
    return sweep


def thumbnail_svg(profile: dict[str, Any]) -> str:
    vertices = {item["vertex_id"]: item for item in profile.get("vertices", [])}
    if not vertices:
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'></svg>"
    xs, ys = [float(item["x"]) for item in vertices.values()], [float(item["y"]) for item in vertices.values()]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    scale = min(90 / max(max_x - min_x, 1e-9), 90 / max(max_y - min_y, 1e-9))

    def xy(vertex_id: str) -> tuple[float, float]:
        item = vertices[vertex_id]
        return (5 + (float(item["x"]) - min_x) * scale, 95 - (float(item["y"]) - min_y) * scale)

    parts: list[str] = []
    for index, segment in enumerate(profile.get("segments", [])):
        sx, sy = xy(segment["start_vertex_id"])
        ex, ey = xy(segment["end_vertex_id"])
        if index == 0:
            parts.append(f"M {sx:.3f} {sy:.3f}")
        if segment.get("type") == "ARC":
            radius = float(segment.get("radius", 1)) * scale
            start_original = (float(vertices[segment["start_vertex_id"]]["x"]), float(vertices[segment["start_vertex_id"]]["y"]))
            end_original = (float(vertices[segment["end_vertex_id"]]["x"]), float(vertices[segment["end_vertex_id"]]["y"]))
            sweep = _arc_sweep(start_original, end_original, segment["center"], bool(segment.get("clockwise")))
            large_arc = 1 if abs(sweep) > math.pi else 0
            # SVG's screen Y axis points downward, so the sweep flag is inverted
            # relative to the application's mathematical Y-up clockwise flag.
            svg_sweep = 0 if segment.get("clockwise") else 1
            parts.append(f"A {radius:.3f} {radius:.3f} 0 {large_arc} {svg_sweep} {ex:.3f} {ey:.3f}")
        else:
            parts.append(f"L {ex:.3f} {ey:.3f}")
    return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100' role='img' aria-label='Imported profile'><path d='" + " ".join(parts) + "' fill='none' stroke='#155783' stroke-width='2'/></svg>"
