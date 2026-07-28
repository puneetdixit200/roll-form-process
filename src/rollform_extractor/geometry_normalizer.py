from __future__ import annotations

import math
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
    for key in ("start", "end", "center", "location", "point", "insert"):
        if key in attrs:
            attrs[key] = _transform_point(attrs[key], matrix, unit_factor)
    for key in ("points", "control_points", "fit_points", "vertices"):
        if key in attrs:
            attrs[key] = tuple(_transform_point(point, matrix, unit_factor) for point in attrs[key])
    if "radius" in attrs:
        attrs["radius"] = float(attrs["radius"]) * _scale_factor(matrix) * unit_factor
    if "major_axis" in attrs:
        attrs["major_axis"] = _transform_vector(attrs["major_axis"], matrix, unit_factor)
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


def _transform_point(point, matrix: np.ndarray, unit_factor: float) -> tuple[float, float, float]:
    x, y, z = _point(point)
    out = matrix @ np.array([x, y, z, 1.0])
    return (float(out[0] * unit_factor), float(out[1] * unit_factor), float(out[2] * unit_factor))


def _transform_vector(vector, matrix: np.ndarray, unit_factor: float) -> tuple[float, float, float]:
    x, y, z = _point(vector)
    out = matrix @ np.array([x, y, z, 0.0])
    return (float(out[0] * unit_factor), float(out[1] * unit_factor), float(out[2] * unit_factor))


def _point(value) -> tuple[float, float, float]:
    if hasattr(value, "xyz"):
        value = value.xyz
    values = tuple(value)
    if len(values) == 2:
        return (float(values[0]), float(values[1]), 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))


def _scale_factor(matrix: np.ndarray) -> float:
    return float(np.linalg.norm(matrix[:3, 0]))


def _distance(a, b) -> float:
    return math.dist(_point(a), _point(b))
