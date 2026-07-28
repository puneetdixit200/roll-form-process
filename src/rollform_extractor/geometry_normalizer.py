from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Iterable

import numpy as np

from rollform_extractor.models import CadPrimitive, NormalizedGeometry


def compose_insert_matrix(insert, parent_matrix) -> np.ndarray:
    dxf = insert.dxf
    x, y, z = _point(getattr(dxf, "insert", (0, 0, 0)))
    rotation = math.radians(float(getattr(dxf, "rotation", 0.0) or 0.0))
    sx = float(getattr(dxf, "xscale", 1.0) or 1.0)
    sy = float(getattr(dxf, "yscale", 1.0) or 1.0)
    sz = float(getattr(dxf, "zscale", 1.0) or 1.0)
    local = np.array(
        [
            [math.cos(rotation) * sx, -math.sin(rotation) * sy, 0.0, x],
            [math.sin(rotation) * sx, math.cos(rotation) * sy, 0.0, y],
            [0.0, 0.0, sz, z],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    return np.asarray(parent_matrix, dtype=float) @ local


def normalize_primitives(
    primitives: Iterable[CadPrimitive],
    transform,
    unit_factor: float,
    spacing: float,
    join_tolerance: float = 0.0,
) -> NormalizedGeometry:
    matrix = np.asarray(transform, dtype=float)
    normalized: list[CadPrimitive] = []
    sampled: list[tuple[float, float, float]] = []
    for primitive in primitives:
        new_primitive = _normalize_primitive(primitive, matrix, unit_factor)
        normalized.append(new_primitive)
        for point in _sample(new_primitive, spacing):
            if sampled and _distance(sampled[-1], point) <= join_tolerance:
                sampled.append(sampled[-1])
            else:
                sampled.append(point)
    return NormalizedGeometry(tuple(normalized), tuple(sampled))


def _normalize_primitive(
    primitive: CadPrimitive, matrix: np.ndarray, unit_factor: float
) -> CadPrimitive:
    attrs = dict(primitive.attributes)
    kind = primitive.kind
    if kind in {"CIRCLE", "ARC"} and not _uniform_xy_scale(matrix):
        center = _transform_point(attrs["center"], matrix, unit_factor)
        radius = float(attrs["radius"])
        attrs = {
            **attrs,
            "center": center,
            "major_axis": _transform_vector((radius, 0.0, 0.0), matrix, unit_factor),
            "minor_axis": _transform_vector((0.0, radius, 0.0), matrix, unit_factor),
            "source_kind": kind,
            "transform_warning": "non_uniform_scale",
        }
        kind = "ELLIPSE" if kind == "CIRCLE" else "ELLIPSE_ARC"
        return CadPrimitive(kind=kind, attributes=attrs, source_handle=primitive.source_handle)
    for key in ("start", "end", "center", "location", "point", "insert"):
        if key in attrs:
            attrs[key] = _transform_point(attrs[key], matrix, unit_factor)
    for key in ("points", "control_points", "fit_points"):
        if key in attrs:
            attrs[key] = tuple(_transform_point(point, matrix, unit_factor) for point in attrs[key])
    if "vertices" in attrs:
        attrs["vertices"] = tuple(_transform_vertex(vertex, matrix, unit_factor) for vertex in attrs["vertices"])
    if "radius" in attrs:
        attrs["radius"] = float(attrs["radius"]) * _scale_factor(matrix) * unit_factor
    if "major_axis" in attrs:
        attrs["major_axis"] = _transform_vector(attrs["major_axis"], matrix, unit_factor)
    if kind == "ELLIPSE" and "minor_axis" not in attrs:
        major = primitive.attributes["major_axis"]
        ratio = float(primitive.attributes["ratio"])
        attrs["minor_axis"] = _transform_vector((-major[1] * ratio, major[0] * ratio, 0.0), matrix, unit_factor)
    return CadPrimitive(kind=kind, attributes=attrs, source_handle=primitive.source_handle)


def _sample(
    primitive: CadPrimitive, spacing: float
) -> tuple[tuple[float, float, float], ...]:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        return _sample_segment(attrs["start"], attrs["end"], spacing)
    if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = attrs.get("points") or attrs.get("vertices") or ()
        out: list[tuple[float, float, float]] = []
        for start, end in zip(points, points[1:]):
            segment = _sample_segment(start, end, spacing)
            out.extend(segment if not out else segment[1:])
        return tuple(out)
    if primitive.kind == "CIRCLE":
        center = attrs["center"]
        radius = float(attrs["radius"])
        steps = max(8, math.ceil((2 * math.pi * radius) / max(spacing, 0.001)))
        return tuple(
            (
                center[0] + radius * math.cos(2 * math.pi * i / steps),
                center[1] + radius * math.sin(2 * math.pi * i / steps),
                center[2],
            )
            for i in range(steps)
        )
    if primitive.kind == "ARC":
        return _sample_arc(
            attrs["center"],
            float(attrs["radius"]),
            float(attrs["start_angle"]),
            float(attrs["end_angle"]),
            spacing,
        )
    if primitive.kind in {"ELLIPSE", "ELLIPSE_ARC"}:
        return _sample_ellipse(
            attrs["center"],
            attrs["major_axis"],
            attrs.get("minor_axis"),
            float(attrs.get("ratio", 1.0)),
            float(attrs.get("start_param", 0.0)),
            float(attrs.get("end_param", 2 * math.pi)),
            spacing,
        )
    if primitive.kind == "SPLINE":
        points = attrs.get("fit_points") or attrs.get("control_points") or ()
        out: list[tuple[float, float, float]] = []
        for start, end in zip(points, points[1:]):
            segment = _sample_segment(start, end, spacing)
            out.extend(segment if not out else segment[1:])
        return tuple(out)
    return tuple(
        point
        for key in ("point", "location", "center", "insert")
        for point in ([attrs[key]] if key in attrs else [])
    )


def _sample_segment(start, end, spacing: float) -> tuple[tuple[float, float, float], ...]:
    a = _point(start)
    b = _point(end)
    length = _distance(a, b)
    steps = max(1, math.ceil(length / max(spacing, 0.001)))
    return tuple(
        (
            a[0] + (b[0] - a[0]) * i / steps,
            a[1] + (b[1] - a[1]) * i / steps,
            a[2] + (b[2] - a[2]) * i / steps,
        )
        for i in range(steps + 1)
    )


def _sample_arc(
    center, radius: float, start_angle: float, end_angle: float, spacing: float
) -> tuple[tuple[float, float, float], ...]:
    center = _point(center)
    sweep = end_angle - start_angle
    if sweep <= 0:
        sweep += 360.0
    length = abs(math.radians(sweep) * radius)
    steps = max(1, math.ceil(length / max(spacing, 0.001)))
    return tuple(
        (
            center[0] + radius * math.cos(math.radians(start_angle + sweep * i / steps)),
            center[1] + radius * math.sin(math.radians(start_angle + sweep * i / steps)),
            center[2],
        )
        for i in range(steps + 1)
    )


def _sample_ellipse(
    center,
    major_axis,
    minor_axis,
    ratio: float,
    start_param: float,
    end_param: float,
    spacing: float,
) -> tuple[tuple[float, float, float], ...]:
    center = _point(center)
    major = _point(major_axis)
    minor = _point(minor_axis) if minor_axis is not None else (-major[1] * ratio, major[0] * ratio, 0.0)
    sweep = end_param - start_param
    if sweep <= 0:
        sweep += 2 * math.pi
    radius = max(math.dist((0, 0, 0), major), math.dist((0, 0, 0), minor))
    steps = max(1, math.ceil(abs(sweep) * radius / max(spacing, 0.001)))
    return tuple(
        (
            center[0] + major[0] * math.cos(start_param + sweep * i / steps) + minor[0] * math.sin(start_param + sweep * i / steps),
            center[1] + major[1] * math.cos(start_param + sweep * i / steps) + minor[1] * math.sin(start_param + sweep * i / steps),
            center[2] + major[2] * math.cos(start_param + sweep * i / steps) + minor[2] * math.sin(start_param + sweep * i / steps),
        )
        for i in range(steps + 1)
    )


def _transform_point(point, matrix: np.ndarray, unit_factor: float) -> tuple[float, float, float]:
    x, y, z = _point(point)
    out = matrix @ np.array([x, y, z, 1.0])
    return (float(out[0] * unit_factor), float(out[1] * unit_factor), float(out[2] * unit_factor))


def _transform_vector(vector, matrix: np.ndarray, unit_factor: float) -> tuple[float, float, float]:
    x, y, z = _point(vector)
    out = matrix @ np.array([x, y, z, 0.0])
    return (float(out[0] * unit_factor), float(out[1] * unit_factor), float(out[2] * unit_factor))


def _transform_vertex(vertex, matrix: np.ndarray, unit_factor: float) -> dict:
    if isinstance(vertex, Mapping):
        return {**vertex, "point": _transform_point(vertex["point"], matrix, unit_factor)}
    return {"point": _transform_point(vertex, matrix, unit_factor)}


def _point(value) -> tuple[float, float, float]:
    if hasattr(value, "xyz"):
        value = value.xyz
    values = tuple(value)
    if len(values) == 2:
        return (float(values[0]), float(values[1]), 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))


def _scale_factor(matrix: np.ndarray) -> float:
    return float(np.linalg.norm(matrix[:3, 0]))


def _uniform_xy_scale(matrix: np.ndarray) -> bool:
    return math.isclose(
        float(np.linalg.norm(matrix[:3, 0])),
        float(np.linalg.norm(matrix[:3, 1])),
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def _distance(a, b) -> float:
    return math.dist(_point(a), _point(b))
