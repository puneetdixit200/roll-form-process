from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Iterable

from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord


@dataclass(frozen=True)
class Provenance:
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float


@dataclass(frozen=True)
class BendFeature:
    radius_mm: float
    angle_deg: float
    source_handle: str


@dataclass(frozen=True)
class ProfileFeatures:
    width_mm: float
    height_mm: float
    developed_length_mm: float
    segment_lengths_mm: tuple[float, ...]
    bends: tuple[BendFeature, ...]
    bbox: BBox
    center: tuple[float, float]
    symmetry: str
    sampled_points: tuple[tuple[float, float, float], ...]
    provenance: dict[str, Provenance]


@dataclass(frozen=True)
class GeometryFingerprint:
    digest: str
    mirrored: bool
    payload: dict[str, Any]


def extract_profile_features(profile: ProfileRecord, config_hash: str) -> ProfileFeatures:
    primitives = tuple(profile.features.get("normalized_primitives", ()))
    sampled_points = tuple(profile.features.get("sampled_points", ()))
    chains = _chains(primitives)
    selected = max(chains, key=lambda chain: sum(primitive_length(item) for item in chain), default=primitives)
    lengths = tuple(primitive_length(primitive) for primitive in selected)
    source_handles = tuple(primitive.source_handle for primitive in selected)
    points = _points(sampled_points, selected)
    bbox = _bbox(points)
    developed = float(profile.features.get("exact_length", sum(lengths)))
    if "exact_length" not in profile.features:
        developed = sum(lengths)
    provenance = {
        "developed_length_mm": Provenance(source_handles, "exact_primitives", config_hash, profile.confidence),
        "width_mm": Provenance(source_handles, "normalized_bbox", config_hash, profile.confidence),
        "height_mm": Provenance(source_handles, "normalized_bbox", config_hash, profile.confidence),
    }
    return ProfileFeatures(
        width_mm=bbox.max_x - bbox.min_x,
        height_mm=bbox.max_y - bbox.min_y,
        developed_length_mm=developed,
        segment_lengths_mm=lengths,
        bends=tuple(_bend(primitive) for primitive in selected if primitive.kind in {"ARC", "ELLIPSE_ARC"}),
        bbox=bbox,
        center=((bbox.min_x + bbox.max_x) / 2, (bbox.min_y + bbox.max_y) / 2),
        symmetry=_symmetry(points),
        sampled_points=points,
        provenance=provenance,
    )


def fingerprint_profile(features: ProfileFeatures, sampled_points, mirrored: bool = False) -> GeometryFingerprint:
    points = [(-x, y, z) if mirrored else (x, y, z) for x, y, z in sampled_points]
    canonical_points = _canonical_points(points)
    payload = {
        "developed_length_mm": round(features.developed_length_mm, 3),
        "width_mm": round(features.width_mm, 3),
        "height_mm": round(features.height_mm, 3),
        "bend_radii_mm": tuple(round(bend.radius_mm, 3) for bend in features.bends),
        "points": canonical_points,
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return GeometryFingerprint(digest=digest, mirrored=mirrored, payload=payload)


def primitive_length(primitive: CadPrimitive) -> float:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        return _distance(attrs["start"], attrs["end"])
    if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = tuple(vertex["point"] if isinstance(vertex, dict) else vertex for vertex in attrs.get("vertices", attrs.get("points", ())))
        total = sum(_distance(start, end) for start, end in zip(points, points[1:]))
        if attrs.get("closed") and len(points) > 1:
            total += _distance(points[-1], points[0])
        return total
    if primitive.kind == "ARC":
        sweep = _sweep_degrees(float(attrs["start_angle"]), float(attrs["end_angle"]))
        return abs(math.radians(sweep) * float(attrs["radius"]))
    if primitive.kind == "CIRCLE":
        return 2 * math.pi * float(attrs["radius"])
    points = _primitive_points(primitive)
    return sum(_distance(start, end) for start, end in zip(points, points[1:]))


def _chains(primitives: tuple[CadPrimitive, ...]) -> tuple[tuple[CadPrimitive, ...], ...]:
    remaining = list(primitives)
    chains = []
    while remaining:
        chain = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            ends = _chain_endpoints(chain)
            for primitive in list(remaining):
                primitive_ends = _endpoints(primitive)
                if any(_distance(a, b) <= 0.05 for a in ends for b in primitive_ends):
                    chain.append(primitive)
                    remaining.remove(primitive)
                    changed = True
        chains.append(tuple(chain))
    return tuple(chains)


def _chain_endpoints(chain):
    points = [point for primitive in chain for point in _endpoints(primitive)]
    return tuple(points)


def _endpoints(primitive: CadPrimitive):
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        return (_point(attrs["start"]), _point(attrs["end"]))
    if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = tuple(vertex["point"] if isinstance(vertex, dict) else vertex for vertex in attrs.get("vertices", attrs.get("points", ())))
        return tuple(_point(point) for point in points[:1] + points[-1:])
    if primitive.kind == "ARC":
        center = _point(attrs["center"])
        radius = float(attrs["radius"])
        return (
            _angle_point(center, radius, float(attrs["start_angle"])),
            _angle_point(center, radius, float(attrs["end_angle"])),
        )
    return _primitive_points(primitive)[:2]


def _bend(primitive: CadPrimitive) -> BendFeature:
    attrs = primitive.attributes
    return BendFeature(
        radius_mm=float(attrs.get("radius", 0.0)),
        angle_deg=_sweep_degrees(float(attrs.get("start_angle", 0.0)), float(attrs.get("end_angle", 0.0))),
        source_handle=primitive.source_handle,
    )


def _points(sampled_points, primitives):
    if sampled_points:
        return tuple(_point(point) for point in sampled_points)
    return tuple(point for primitive in primitives for point in _primitive_points(primitive))


def _primitive_points(primitive: CadPrimitive):
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        return (_point(attrs["start"]), _point(attrs["end"]))
    if primitive.kind == "ARC":
        return _endpoints(primitive)
    if "points" in attrs:
        return tuple(_point(point) for point in attrs["points"])
    return tuple(_point(value) for key, value in attrs.items() if key in {"point", "center", "insert", "start", "end"})


def _bbox(points) -> BBox:
    xs = [point[0] for point in points] or [0.0]
    ys = [point[1] for point in points] or [0.0]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def _canonical_points(points: Iterable[tuple[float, float, float]]):
    raw = tuple(_point(point) for point in points)
    if not raw:
        return ()
    min_x = min(point[0] for point in raw)
    min_y = min(point[1] for point in raw)
    normalized = tuple((round(x - min_x, 3), round(y - min_y, 3)) for x, y, _ in raw)
    reversed_points = tuple(reversed(normalized))
    return min(normalized, reversed_points)


def _symmetry(points) -> str:
    if not points:
        return "unknown"
    cx = (min(point[0] for point in points) + max(point[0] for point in points)) / 2
    mirrored = {round(2 * cx - point[0], 3) for point in points}
    xs = {round(point[0], 3) for point in points}
    return "vertical" if xs == mirrored else "none"


def _sweep_degrees(start: float, end: float) -> float:
    sweep = end - start
    if sweep <= 0:
        sweep += 360.0
    return sweep


def _angle_point(center, radius: float, angle: float):
    return (
        center[0] + radius * math.cos(math.radians(angle)),
        center[1] + radius * math.sin(math.radians(angle)),
        center[2],
    )


def _distance(left, right) -> float:
    return math.dist(_point(left), _point(right))


def _point(value) -> tuple[float, float, float]:
    values = tuple(value)
    if len(values) == 2:
        return (float(values[0]), float(values[1]), 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))
