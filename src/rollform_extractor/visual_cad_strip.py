"""Conservative interpretation of closed CAD strip outlines.

The importer keeps the source boundary as-is.  This module only creates a
second, explicitly derived centerline candidate when independent geometric
signals suggest that the closed boundary is a constant-width strip rather
than a section that should be manufactured as a closed loop.
"""
from __future__ import annotations

from math import hypot
from typing import Any

from shapely.geometry import Polygon


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _ring_points(profile: dict[str, Any]) -> list[tuple[float, float]]:
    vertices = {item["vertex_id"]: item for item in profile.get("vertices", [])}
    points: list[tuple[float, float]] = []
    for segment in profile.get("segments", []):
        point = vertices.get(segment.get("start_vertex_id"))
        if point is not None:
            points.append((float(point["x"]), float(point["y"])))
    return points


def _length(points: list[tuple[float, float]]) -> float:
    return sum(_distance(left, right) for left, right in zip(points, points[1:]))


def _interpolate(points: list[tuple[float, float]], count: int) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points[:]
    total = _length(points)
    if total <= 1e-12:
        return [points[0]] * count
    targets = [total * index / (count - 1) for index in range(count)]
    result: list[tuple[float, float]] = []
    travelled = 0.0
    segment_index = 0
    for target in targets:
        while segment_index < len(points) - 2 and travelled + _distance(points[segment_index], points[segment_index + 1]) < target:
            travelled += _distance(points[segment_index], points[segment_index + 1])
            segment_index += 1
        left, right = points[segment_index], points[segment_index + 1]
        span = _distance(left, right)
        fraction = 0.0 if span <= 1e-12 else (target - travelled) / span
        result.append((left[0] + (right[0] - left[0]) * fraction, left[1] + (right[1] - left[1]) * fraction))
    return result


def _split_ring(points: list[tuple[float, float]], first: int, second: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if first > second:
        first, second = second, first
    forward = points[first : second + 1]
    backward = points[second:] + points[: first + 1]
    return forward, backward


def _centerline(points: list[tuple[float, float]], thickness: float | None = None) -> list[tuple[float, float]]:
    # Boundary edges close to the inferred strip width are stable cap
    # anchors for elongated constant-width outlines. Averaging equal-
    # arclength samples on the two boundary chains is translation invariant
    # and does not depend on a drawing-specific handle or filename.
    edge_lengths = [_distance(points[index], points[(index + 1) % len(points)]) for index in range(len(points))]
    cap_limit = max((thickness or 0.0) * 1.75, max(edge_lengths) * 0.08)
    caps = [index for index, value in enumerate(edge_lengths) if value <= cap_limit]
    if len(caps) < 2:
        caps = list(range(len(points)))
    reference_width = thickness or (sum(edge_lengths) / max(len(edge_lengths), 1))
    pair = min(((abs(edge_lengths[i] - reference_width) + abs(edge_lengths[j] - reference_width), abs(edge_lengths[i] - edge_lengths[j]), -_distance(((points[i][0] + points[(i + 1) % len(points)][0]) / 2, (points[i][1] + points[(i + 1) % len(points)][1]) / 2),
                           ((points[j][0] + points[(j + 1) % len(points)][0]) / 2, (points[j][1] + points[(j + 1) % len(points)][1]) / 2)), i, j)
                for i in caps for j in caps if i < j), default=(0.0, 0.0, 0.0, 0, max(1, len(points) - 1)))
    _, _, _, first, second = pair
    first_mid = ((points[first][0] + points[(first + 1) % len(points)][0]) / 2, (points[first][1] + points[(first + 1) % len(points)][1]) / 2)
    second_mid = ((points[second][0] + points[(second + 1) % len(points)][0]) / 2, (points[second][1] + points[(second + 1) % len(points)][1]) / 2)
    chain_a = [first_mid] + points[first + 1 : second + 1] + [second_mid]
    chain_b = [first_mid] + list(reversed(points[: first + 1])) + list(reversed(points[second + 1 :])) + [second_mid]
    chain_b = [chain_b[0]] + [point for index, point in enumerate(chain_b[1:-1], start=1) if point != chain_b[index - 1]] + [chain_b[-1]]
    count = max(8, min(96, max(len(chain_a), len(chain_b)) * 2))
    samples_a = _interpolate(chain_a, count)
    samples_b = _interpolate(chain_b, count)
    return [((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0) for left, right in zip(samples_a, samples_b)]


def classify_closed_profile(profile: dict[str, Any]) -> dict[str, Any]:
    points = _ring_points(profile)
    result: dict[str, Any] = {
        "representation": "GENERIC_CLOSED_CONTOUR",
        "classification_confidence": "LOW",
        "thickness_estimate": None,
        "classification_reasons": [],
    }
    if not profile.get("closed") or len(points) < 4:
        result["representation"] = "CENTERLINE_PATH" if not profile.get("closed") else "GENERIC_CLOSED_CONTOUR"
        return result
    polygon = Polygon(points)
    perimeter = polygon.length
    area = abs(polygon.area)
    min_x, min_y, max_x, max_y = polygon.bounds
    extent = max(max_x - min_x, max_y - min_y, 1e-9)
    thickness = 2.0 * area / perimeter if perimeter > 1e-12 else None
    ratio = (thickness / extent) if thickness is not None else 1.0
    valid = polygon.is_valid and area > 1e-9 and perimeter > 1e-9
    if valid and thickness is not None and 0.01 <= ratio <= 0.20:
        result.update({
            "representation": "STRIP_OUTLINE",
            "classification_confidence": "MEDIUM",
            "thickness_estimate": round(thickness, 8),
            "classification_reasons": ["elongated_valid_closed_boundary", "constant_width_strip_signal"],
        })
    elif valid:
        result.update({"representation": "CLOSED_SECTION_BOUNDARY", "classification_confidence": "MEDIUM", "classification_reasons": ["valid_closed_boundary"]})
    else:
        result["representation"] = "AMBIGUOUS"
        result["classification_reasons"] = ["invalid_or_degenerate_closed_boundary"]
    return result


def derive_centerline_candidate(profile_candidate: dict[str, Any]) -> dict[str, Any] | None:
    classification = classify_closed_profile(profile_candidate["profile"])
    if classification["representation"] != "STRIP_OUTLINE":
        return None
    points = _centerline(_ring_points(profile_candidate["profile"]), classification["thickness_estimate"])
    if len(points) < 2:
        return None
    profile_id = f"{profile_candidate['profile_id']}-centerline"
    vertices = [{"vertex_id": f"{profile_id}-v-{index + 1:04d}", "x": round(point[0], 8), "y": round(point[1], 8)} for index, point in enumerate(points)]
    segments = [{"segment_id": f"{profile_id}-s-{index + 1:04d}", "type": "LINE", "start_vertex_id": vertices[index]["vertex_id"], "end_vertex_id": vertices[index + 1]["vertex_id"]} for index in range(len(vertices) - 1)]
    source = profile_candidate["profile"]
    profile = {
        "schema_version": source["schema_version"],
        "profile_id": profile_id,
        "name": f"Derived centerline for {profile_candidate['profile_id']}",
        "topology": "OPEN_PATH",
        "closed": False,
        "computational_seam_vertex_id": None,
        "vertices": vertices,
        "segments": segments,
        "metadata": {
            "source": "DERIVED_CAD_STRIP_CENTERLINE",
            "visual_only": True,
            "representation": "CENTERLINE_PATH",
            "derived_from_profile_id": profile_candidate["profile_id"],
            "source_handles": source["metadata"].get("source_handles", []),
            "source_layers": source["metadata"].get("source_layers", []),
            "source_units": source["metadata"].get("source_units"),
            "unit_status": source["metadata"].get("unit_status", "UNKNOWN"),
            "thickness_estimate": classification["thickness_estimate"],
            "derivation_method": "WIDTH_MATCHED_CAP_ANCHORS_ARCLENGTH_MIDPOINTS",
            "derivation_status": "ESTIMATED_REVIEW_REQUIRED",
            "warnings": ["DERIVED_CENTERLINE_ESTIMATE_REQUIRES_ENGINEER_REVIEW"],
        },
    }
    candidate = dict(profile_candidate)
    candidate.update({
        "profile_id": profile_id,
        "candidate_id": profile_id,
        "profile": profile,
        "open_closed": "OPEN_PATH",
        "entity_count": profile_candidate["entity_count"],
        "candidate_kind": "DERIVED_CENTERLINE",
        "representation": "CENTERLINE_PATH",
        "derived_from_profile_id": profile_candidate["profile_id"],
        "classification_confidence": classification["classification_confidence"],
        "classification_reasons": classification["classification_reasons"],
        "thickness_estimate": classification["thickness_estimate"],
        "warnings": sorted(set(profile_candidate.get("warnings", []) + ["DERIVED_CENTERLINE_ESTIMATE_REQUIRES_ENGINEER_REVIEW"])),
    })
    from rollform_extractor.visual_cad_profile_detection import thumbnail_svg
    candidate["thumbnail_svg"] = thumbnail_svg(profile)
    return candidate
