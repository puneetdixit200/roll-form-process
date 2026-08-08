"""Constant centerline strip-length projection for visual flower candidates.

This module is deliberately geometry-only. It preserves the final target
centerline arc length in canonical visual space. It does not model strain,
neutral-axis movement, thinning, springback, tooling contact, or
manufacturability.
"""

from __future__ import annotations

import math
from typing import Any, Iterable


STRIP_LENGTH_CONSTRAINT_VERSION = "constant_centerline_length_v1"
STRIP_LENGTH_RELATIVE_TOLERANCE = 1e-6
_EPSILON = 1e-12


def _points(value: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    return [(float(item[0]), float(item[1])) for item in value]


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def centerline_length(points: Iterable[Iterable[float]], topology: str = "OPEN_PATH") -> float:
    """Return discrete centerline arc length in the supplied coordinate space."""
    value = _points(points)
    if len(value) < 2:
        return 0.0
    total = sum(_distance(left, right) for left, right in zip(value, value[1:]))
    if topology == "CLOSED_CONTOUR":
        total += _distance(value[-1], value[0])
    return float(total)


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return (0.0, 0.0)
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _resample(points: list[tuple[float, float]], count: int, *, closed: bool) -> list[tuple[float, float]]:
    """Deterministically resample by arclength, retaining closed-loop topology."""
    if count < 2 or len(points) < 2:
        return list(points)
    edges = list(zip(points, points[1:]))
    if closed:
        edges.append((points[-1], points[0]))
    lengths = [_distance(left, right) for left, right in edges]
    total = sum(lengths)
    if total <= _EPSILON:
        return [points[0] for _ in range(count)]

    samples: list[tuple[float, float]] = []
    denominator = count if closed else count - 1
    for index in range(count):
        target_distance = total * index / max(1, denominator)
        walked = 0.0
        for edge_index, length in enumerate(lengths):
            if walked + length >= target_distance or edge_index == len(edges) - 1:
                ratio = (target_distance - walked) / length if length > _EPSILON else 0.0
                left, right = edges[edge_index]
                samples.append(
                    (
                        left[0] + ratio * (right[0] - left[0]),
                        left[1] + ratio * (right[1] - left[1]),
                    )
                )
                break
            walked += length
    return samples


def _project_open_segment_lengths(
    predicted: list[tuple[float, float]],
    target: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Preserve target material-coordinate segment lengths and predicted tangents."""
    predicted = _resample(predicted, len(target), closed=False)
    target_lengths = [_distance(left, right) for left, right in zip(target, target[1:])]
    output = [predicted[0]]
    previous_direction = (1.0, 0.0)

    for index, target_length in enumerate(target_lengths):
        dx = predicted[index + 1][0] - predicted[index][0]
        dy = predicted[index + 1][1] - predicted[index][1]
        norm = math.hypot(dx, dy)
        if norm <= _EPSILON:
            tx = target[index + 1][0] - target[index][0]
            ty = target[index + 1][1] - target[index][1]
            target_norm = math.hypot(tx, ty)
            if target_norm > _EPSILON:
                direction = (tx / target_norm, ty / target_norm)
            else:
                direction = previous_direction
        else:
            direction = (dx / norm, dy / norm)
        previous_direction = direction
        output.append(
            (
                output[-1][0] + target_length * direction[0],
                output[-1][1] + target_length * direction[1],
            )
        )

    predicted_center = _centroid(predicted)
    output_center = _centroid(output)
    shift_x = predicted_center[0] - output_center[0]
    shift_y = predicted_center[1] - output_center[1]
    return [(point[0] + shift_x, point[1] + shift_y) for point in output]


def _project_closed_perimeter(
    predicted: list[tuple[float, float]],
    target: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Preserve closed-loop perimeter while retaining the predicted loop shape."""
    predicted = _resample(predicted, len(target), closed=True)
    target_length = centerline_length(target, "CLOSED_CONTOUR")
    current_length = centerline_length(predicted, "CLOSED_CONTOUR")
    if target_length <= _EPSILON:
        raise ValueError("target centerline has zero strip length")
    if current_length <= _EPSILON:
        return list(target)
    center = _centroid(predicted)
    scale = target_length / current_length
    return [
        (
            center[0] + (point[0] - center[0]) * scale,
            center[1] + (point[1] - center[1]) * scale,
        )
        for point in predicted
    ]


def project_constant_strip_length(
    points: Iterable[Iterable[float]],
    target_points: Iterable[Iterable[float]],
    topology: str,
    *,
    relative_tolerance: float = STRIP_LENGTH_RELATIVE_TOLERANCE,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Project one predicted stage onto the final-target centerline length.

    Open paths preserve each target material-coordinate segment length while
    retaining the predicted stage segment directions. Closed contours preserve
    total perimeter, because an open flat strip cannot be represented as a
    closed contour without a topology change.
    """
    predicted = _points(points)
    target = _points(target_points)
    if len(predicted) < 2 or len(target) < 2:
        raise ValueError("strip-length projection requires at least two points")
    if topology not in {"OPEN_PATH", "CLOSED_CONTOUR"}:
        raise ValueError("unsupported topology for strip-length projection")

    before_length = centerline_length(predicted, topology)
    target_length = centerline_length(target, topology)
    if target_length <= _EPSILON:
        raise ValueError("target centerline has zero strip length")

    if topology == "OPEN_PATH":
        projected = _project_open_segment_lengths(predicted, target)
        method = "OPEN_SEGMENT_LENGTH_TANGENT_PROJECTION"
        local_segment_lengths_preserved = True
    else:
        projected = _project_closed_perimeter(predicted, target)
        method = "CLOSED_PERIMETER_PROJECTION"
        local_segment_lengths_preserved = False

    rounded = [[round(point[0], 10), round(point[1], 10)] for point in projected]
    after_length = centerline_length(rounded, topology)
    relative_error = abs(after_length - target_length) / max(target_length, _EPSILON)

    comparison_predicted = _resample(predicted, len(rounded), closed=topology == "CLOSED_CONTOUR")
    projection_rms = math.sqrt(
        sum(
            (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2
            for left, right in zip(comparison_predicted, _points(rounded))
        )
        / max(1, len(rounded))
    )

    metadata = {
        "constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
        "enabled": True,
        "reference": "FINAL_TARGET_CENTERLINE",
        "coordinate_space": "CANONICAL_VISUAL_UNITS",
        "method": method,
        "target_length": round(target_length, 10),
        "before_length": round(before_length, 10),
        "actual_length": round(after_length, 10),
        "relative_error": round(relative_error, 12),
        "relative_tolerance": relative_tolerance,
        "satisfied": bool(relative_error <= relative_tolerance),
        "local_segment_lengths_preserved": local_segment_lengths_preserved,
        "projection_rms": round(projection_rms, 10),
        "visual_only": True,
    }
    return rounded, metadata


def closed_reference_loop(target_points: Iterable[Iterable[float]]) -> list[list[float]]:
    """Return a deterministic equal-perimeter circle for closed visual progression."""
    target = _points(target_points)
    if len(target) < 3:
        raise ValueError("closed reference loop requires at least three points")
    perimeter = centerline_length(target, "CLOSED_CONTOUR")
    radius = perimeter / (2.0 * math.pi)
    signed_area = 0.0
    for left, right in zip(target, target[1:] + target[:1]):
        signed_area += left[0] * right[1] - right[0] * left[1]
    direction = 1.0 if signed_area >= 0.0 else -1.0
    first_angle = math.atan2(target[0][1], target[0][0]) if math.hypot(*target[0]) > _EPSILON else 0.0
    output = [
        [
            round(radius * math.cos(first_angle + direction * 2.0 * math.pi * index / len(target)), 10),
            round(radius * math.sin(first_angle + direction * 2.0 * math.pi * index / len(target)), 10),
        ]
        for index in range(len(target))
    ]
    projected, _ = project_constant_strip_length(output, target, "CLOSED_CONTOUR")
    return projected


def candidate_constraint_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    """Build candidate-level invariant evidence from per-pass metadata."""
    rows = [
        item.get("generation", {}).get("strip_length_constraint")
        for item in candidate.get("passes", [])
    ]
    rows = [item for item in rows if isinstance(item, dict)]
    if not rows:
        return {
            "enabled": False,
            "constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
            "satisfied": False,
        }
    return {
        "enabled": True,
        "constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
        "reference": "FINAL_TARGET_CENTERLINE",
        "coordinate_space": "CANONICAL_VISUAL_UNITS",
        "target_length": rows[-1].get("target_length"),
        "maximum_relative_error": max(float(item.get("relative_error", 1.0)) for item in rows),
        "relative_tolerance": rows[-1].get("relative_tolerance", STRIP_LENGTH_RELATIVE_TOLERANCE),
        "satisfied": all(bool(item.get("satisfied")) for item in rows),
        "open_path_local_segment_lengths_preserved": all(
            bool(item.get("local_segment_lengths_preserved")) for item in rows
        ) if candidate.get("passes", [{}])[0].get("profile", {}).get("topology") == "OPEN_PATH" else False,
        "visual_only": True,
    }
