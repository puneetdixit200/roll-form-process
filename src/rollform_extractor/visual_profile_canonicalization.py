"""Deterministic visual-only canonicalization and arclength sampling."""

from __future__ import annotations

from hashlib import sha256
import math
from typing import Any

from rollform_extractor.visual_profile_schema import VisualProfile


def canonicalize_profile(profile: VisualProfile, *, samples: int = 256, scale_normalized: bool = True) -> dict[str, Any]:
    raw = _profile_points(profile)
    if profile.topology == "CLOSED_CONTOUR" and raw and _distance(raw[0], raw[-1]) > 1e-8:
        raw = raw + (raw[0],)
    sampled = _resample(raw, samples, closed=profile.topology == "CLOSED_CONTOUR")
    centered = _center(sampled)
    scale = _rms_radius(centered) or 1.0
    normalized = tuple((round(x / scale, 8), round(y / scale, 8)) for x, y in centered) if scale_normalized else tuple((round(x, 8), round(y, 8)) for x, y in centered)
    if profile.topology == "OPEN_PATH":
        reverse = tuple(reversed(normalized))
        normalized = min(normalized, reverse)
    else:
        normalized = _canonical_closed(normalized)
    width = max((p[0] for p in sampled), default=0.0) - min((p[0] for p in sampled), default=0.0)
    height = max((p[1] for p in sampled), default=0.0) - min((p[1] for p in sampled), default=0.0)
    signature = {"points": [list(point) for point in normalized], "topology": profile.topology, "width": round(width, 8), "height": round(height, 8), "aspect_ratio": round(width / height, 8) if height else None}
    signature["input_hash"] = sha256(str(signature).encode()).hexdigest()
    return signature


def _profile_points(profile: VisualProfile) -> tuple[tuple[float, float], ...]:
    vertices = {item["vertex_id"]: (float(item["x"]), float(item["y"])) for item in profile.vertices}
    points: list[tuple[float, float]] = []
    for segment in profile.segments:
        start = vertices[segment["start_vertex_id"]]
        end = vertices[segment["end_vertex_id"]]
        if not points:
            points.append(start)
        if segment["type"] == "LINE":
            points.append(end)
            continue
        center = segment["center"]
        cx, cy, radius = float(center["x"]), float(center["y"]), float(segment["radius"])
        start_angle = math.atan2(start[1] - cy, start[0] - cx)
        end_angle = math.atan2(end[1] - cy, end[0] - cx)
        clockwise = bool(segment.get("clockwise", False))
        sweep = end_angle - start_angle
        if clockwise and sweep > 0:
            sweep -= 2 * math.pi
        if not clockwise and sweep < 0:
            sweep += 2 * math.pi
        count = max(4, int(abs(sweep * radius) / 2.0))
        points.extend((cx + radius * math.cos(start_angle + sweep * i / count), cy + radius * math.sin(start_angle + sweep * i / count)) for i in range(1, count + 1))
    return tuple(points)


def _resample(points: tuple[tuple[float, float], ...], samples: int, *, closed: bool) -> tuple[tuple[float, float], ...]:
    if not points or samples < 2:
        return points
    base = points[:-1] if closed and _distance(points[0], points[-1]) < 1e-8 else points
    edges = list(zip(base, base[1:] + (base[0],) if closed else base[1:]))
    lengths = [_distance(a, b) for a, b in edges]
    total = sum(lengths)
    if total <= 1e-9:
        return tuple(base[0] for _ in range(samples))
    output = []
    for index in range(samples):
        target = total * index / (samples if closed else samples - 1)
        distance = 0.0
        for edge_index, length in enumerate(lengths):
            if distance + length >= target or edge_index == len(lengths) - 1:
                ratio = (target - distance) / length if length else 0.0
                a, b = edges[edge_index]
                output.append((a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])))
                break
            distance += length
    return tuple(output)


def _center(points):
    cx = sum(p[0] for p in points) / max(1, len(points))
    cy = sum(p[1] for p in points) / max(1, len(points))
    return tuple((p[0] - cx, p[1] - cy) for p in points)


def _canonical_closed(points):
    if not points:
        return points
    variants = []
    for sequence in (points, tuple(reversed(points))):
        for index in range(len(sequence)):
            variants.append(sequence[index:] + sequence[:index])
    return min(variants)


def _rms_radius(points):
    return math.sqrt(sum(x * x + y * y for x, y in points) / max(1, len(points)))


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])
