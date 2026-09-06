"""Conservative interpretation of closed CAD strip outlines.

The importer keeps the source boundary as-is.  This module only creates a
second, explicitly derived centerline candidate when independent geometric
signals suggest that the closed boundary is a constant-width strip rather
than a section that should be manufactured as a closed loop.
"""
from __future__ import annotations

from math import acos, atan2, cos, hypot, isfinite, pi, sin, sqrt
from statistics import median
from typing import Any

from shapely.geometry import LineString, Point, Polygon


STRIP_CENTERLINE_DERIVATION_VERSION = "strip-outline-centerline-v2"


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


def _arc_sweep(segment: dict[str, Any]) -> float:
    start = segment["start"]
    end = segment["end"]
    center = segment["center"]
    a0 = atan2(start[1] - center["y"], start[0] - center["x"])
    a1 = atan2(end[1] - center["y"], end[0] - center["x"])
    raw = a0 - a1 if segment.get("clockwise") else a1 - a0
    return (raw % (2 * pi)) if not segment.get("clockwise") else (raw % (2 * pi))


def _segment_length(segment: dict[str, Any]) -> float:
    if segment["type"] == "LINE":
        return _distance(segment["start"], segment["end"])
    return float(segment["radius"]) * abs(_arc_sweep(segment))


def _boundary_segments(profile: dict[str, Any]) -> list[dict[str, Any]]:
    vertices = {item["vertex_id"]: item for item in profile.get("vertices", [])}
    output: list[dict[str, Any]] = []
    for item in profile.get("segments", []):
        start_vertex = vertices[item["start_vertex_id"]]
        end_vertex = vertices[item["end_vertex_id"]]
        segment = {"type": item["type"], "start": (float(start_vertex["x"]), float(start_vertex["y"])), "end": (float(end_vertex["x"]), float(end_vertex["y"]))}
        if item["type"] == "ARC":
            segment.update({"center": {"x": float(item["center"]["x"]), "y": float(item["center"]["y"])}, "radius": float(item["radius"]), "clockwise": bool(item.get("clockwise", False))})
        segment["length"] = _segment_length(segment)
        output.append(segment)
    return output


def _cap_pair(segments: list[dict[str, Any]], thickness: float | None) -> tuple[int, int]:
    lengths = [float(item["length"]) for item in segments]
    limit = max((thickness or 0.0) * 1.75, max(lengths) * 0.08)
    candidates = [index for index, value in enumerate(lengths) if value <= limit]
    if len(candidates) < 2:
        candidates = list(range(len(segments)))
    reference = thickness or sum(lengths) / max(len(lengths), 1)
    def midpoint(index: int) -> tuple[float, float]:
        item = segments[index]
        return ((item["start"][0] + item["end"][0]) / 2, (item["start"][1] + item["end"][1]) / 2)
    return min(((abs(lengths[i] - reference) + abs(lengths[j] - reference), abs(lengths[i] - lengths[j]), -_distance(midpoint(i), midpoint(j)), i, j) for i in candidates for j in candidates if i < j), default=(0, 0, 0, 0, max(1, len(segments) - 1)))[-2:]


def _reverse_segment(segment: dict[str, Any]) -> dict[str, Any]:
    result = dict(segment)
    result["start"], result["end"] = segment["end"], segment["start"]
    if result["type"] == "ARC":
        result["clockwise"] = not bool(segment.get("clockwise", False))
    return result


def _boundary_chains(segments: list[dict[str, Any]], first: int, second: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if first > second:
        first, second = second, first
    first_mid = ((segments[first]["start"][0] + segments[first]["end"][0]) / 2, (segments[first]["start"][1] + segments[first]["end"][1]) / 2)
    second_mid = ((segments[second]["start"][0] + segments[second]["end"][0]) / 2, (segments[second]["start"][1] + segments[second]["end"][1]) / 2)
    forward = [dict(item) for item in segments[first + 1 : second]]
    backward = [_reverse_segment(segments[index]) for index in list(range(first - 1, -1, -1)) + list(range(len(segments) - 1, second, -1))]
    if forward:
        forward[0]["cap_side_start"] = forward[0]["start"]
        forward[-1]["cap_side_end"] = forward[-1]["end"]
        forward[0]["start"] = first_mid
        forward[-1]["end"] = second_mid
    if backward:
        backward[0]["cap_side_start"] = backward[0]["start"]
        backward[-1]["cap_side_end"] = backward[-1]["end"]
        backward[0]["start"] = first_mid
        backward[-1]["end"] = second_mid
    return forward, backward


def _chain_position(chain: list[dict[str, Any]], value: float) -> dict[str, Any] | None:
    total = sum(float(item["length"]) for item in chain)
    if total <= 1e-12:
        return None
    cursor = 0.0
    for item in chain:
        span = float(item["length"]) / total
        if value <= cursor + span + 1e-12:
            return item
        cursor += span
    return chain[-1]


def _point_on_arc(segment: dict[str, Any], angle: float) -> tuple[float, float]:
    center = segment["center"]
    return (center["x"] + segment["radius"] * cos(angle), center["y"] + segment["radius"] * sin(angle))


def _point_on_segment(segment: dict[str, Any], fraction: float) -> tuple[float, float]:
    fraction = max(0.0, min(1.0, fraction))
    if segment["type"] == "LINE":
        return (
            segment["start"][0] + (segment["end"][0] - segment["start"][0]) * fraction,
            segment["start"][1] + (segment["end"][1] - segment["start"][1]) * fraction,
        )
    center = segment["center"]
    start_angle = atan2(segment["start"][1] - center["y"], segment["start"][0] - center["x"])
    sweep = _arc_sweep(segment)
    angle = start_angle + (-sweep if segment.get("clockwise") else sweep) * fraction
    return _point_on_arc(segment, angle)


def _segment_tangent(segment: dict[str, Any], fraction: float) -> tuple[float, float]:
    if segment["type"] == "LINE":
        dx = segment["end"][0] - segment["start"][0]
        dy = segment["end"][1] - segment["start"][1]
    else:
        point = _point_on_segment(segment, fraction)
        center = segment["center"]
        radial_x = point[0] - center["x"]
        radial_y = point[1] - center["y"]
        dx, dy = (radial_y, -radial_x) if segment.get("clockwise") else (-radial_y, radial_x)
    length = hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-12 else (0.0, 0.0)


def _chain_sample(chain: list[dict[str, Any]], normalized_position: float) -> dict[str, Any] | None:
    """Return an arclength sample, including its local segment position."""
    if not chain:
        return None
    total = sum(float(item["length"]) for item in chain)
    if total <= 1e-12:
        return None
    target = max(0.0, min(1.0, normalized_position)) * total
    travelled = 0.0
    for index, item in enumerate(chain):
        length = float(item["length"])
        if target <= travelled + length + 1e-10 or index == len(chain) - 1:
            local_fraction = 0.0 if length <= 1e-12 else (target - travelled) / length
            local_fraction = max(0.0, min(1.0, local_fraction))
            return {
                "segment": item,
                "segment_index": index,
                "local_fraction": local_fraction,
                "point": _point_on_segment(item, local_fraction),
                "tangent": _segment_tangent(item, local_fraction),
            }
        travelled += length
    return None


def _midpoint(left: tuple[float, float], right: tuple[float, float]) -> tuple[float, float]:
    return ((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0)


def _tangents_compatible(left: tuple[float, float], right: tuple[float, float], tolerance: float = 0.08) -> bool:
    return abs(left[0] * right[0] + left[1] * right[1]) >= 1.0 - tolerance


def _analytic_centerline(chain: list[dict[str, Any]], opposite: list[dict[str, Any]], thickness: float) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    """Build a centerline from paired arclength samples.

    Straight portions are midpoint lines between both source boundaries. An
    arc is promoted only when both boundaries provide compatible arc evidence
    over the same interval. Any remaining segment is still a midpoint
    approximation, never a copy of one source boundary.
    """
    if not chain or not opposite:
        return [], []
    total = sum(float(item["length"]) for item in chain)
    output: list[dict[str, Any]] = []
    cursor = 0.0
    for source in chain:
        start_position = cursor / max(total, 1e-12)
        end_position = (cursor + float(source["length"])) / max(total, 1e-12)
        counterpart_start = _chain_sample(opposite, start_position)
        counterpart_end = _chain_sample(opposite, end_position)
        counterpart_mid = _chain_sample(opposite, (start_position + end_position) / 2.0)
        if not counterpart_start or not counterpart_end or not counterpart_mid:
            cursor += float(source["length"])
            continue
        start = _midpoint(source["start"], counterpart_start["point"])
        end = _midpoint(source["end"], counterpart_end["point"])
        compatible = _tangents_compatible(_segment_tangent(source, 0.5), counterpart_mid["tangent"])
        counterpart_segment = counterpart_mid["segment"]
        if source["type"] == "ARC" and counterpart_segment["type"] == "ARC" and compatible:
            center = {
                "x": (source["center"]["x"] + counterpart_segment["center"]["x"]) / 2.0,
                "y": (source["center"]["y"] + counterpart_segment["center"]["y"]) / 2.0,
            }
            radius = (float(source["radius"]) + float(counterpart_segment["radius"])) / 2.0
            source_start_angle = atan2(source["start"][1] - source["center"]["y"], source["start"][0] - source["center"]["x"])
            start_angle = source_start_angle
            start = _point_on_arc({"center": center, "radius": radius}, start_angle)
            source_sweep = _arc_sweep(source)
            end = _point_on_arc({"center": center, "radius": radius}, start_angle + (-source_sweep if source.get("clockwise") else source_sweep))
            output.append({
                "type": "ARC",
                "start": start,
                "end": end,
                "center": center,
                "radius": radius,
                "clockwise": bool(source.get("clockwise", False)),
                "approximated": False,
            })
        else:
            output.append({"type": "LINE", "start": start, "end": end, "approximated": not compatible})
        cursor += float(source["length"])
    if not output:
        return [], []
    # Keep the derived path topologically connected.  The averaged arc center
    # can move an endpoint by floating-point/offset tolerance; preserve the
    # analytic arc and make the following segment start at that exact point.
    for index in range(1, len(output)):
        if output[index]["type"] == "ARC":
            output[index - 1]["end"] = output[index]["start"]
        else:
            output[index]["start"] = output[index - 1]["end"]
    points = [output[0]["start"]] + [item["end"] for item in output]
    return output, points


def _sample_segments(segments: list[dict[str, Any]], max_chord_error: float = 0.02) -> list[tuple[float, float]]:
    """Sample analytic LINE/ARC segments without replacing their definitions."""
    points: list[tuple[float, float]] = []
    for segment in segments:
        if segment["type"] == "LINE":
            count = 1
        else:
            radius = max(float(segment["radius"]), 1e-12)
            sweep = _arc_sweep(segment)
            if radius <= max_chord_error:
                count = max(2, int(sweep / (pi / 12.0)) + 1)
            else:
                cosine = max(-1.0, min(1.0, 1.0 - max_chord_error / radius))
                step = max(1e-3, 2.0 * acos(cosine))
                count = max(2, int(sweep / step) + 1)
        for index in range(count + 1):
            if points and index == 0:
                continue
            points.append(_point_on_segment(segment, index / count))
    return points


def _sample_chain(chain: list[dict[str, Any]], count: int = 101) -> list[tuple[float, float]]:
    return [(_chain_sample(chain, index / (count - 1)) or {"point": (0.0, 0.0)})["point"] for index in range(count)]


def _chain_thickness_diagnostics(chain_a: list[dict[str, Any]], chain_b: list[dict[str, Any]]) -> dict[str, Any]:
    samples: list[float] = []
    compatible_count = 0
    for index in range(1, 100):
        position = index / 100.0
        left = _chain_sample(chain_a, position)
        right = _chain_sample(chain_b, position)
        if not left or not right or not _tangents_compatible(left["tangent"], right["tangent"]):
            continue
        difference = (right["point"][0] - left["point"][0], right["point"][1] - left["point"][1])
        tangent = left["tangent"]
        normal = (-tangent[1], tangent[0])
        value = abs(difference[0] * normal[0] + difference[1] * normal[1])
        if isfinite(value) and value > 1e-9:
            samples.append(value)
            compatible_count += 1
    if not samples:
        return {"samples": [], "sample_count": 0, "compatible_sample_count": 0, "median": None, "minimum": None, "maximum": None, "robust_minimum": None, "robust_maximum": None, "robust_relative_spread": None, "relative_spread": None}
    middle = float(median(samples))
    ordered = sorted(samples)
    trim = max(1, int(len(ordered) * 0.10))
    robust = ordered[trim:-trim] if len(ordered) > trim * 2 else ordered
    robust_minimum = min(robust)
    robust_maximum = max(robust)
    return {
        "samples": [round(value, 8) for value in samples],
        "sample_count": len(samples),
        "compatible_sample_count": compatible_count,
        "median": round(middle, 8),
        "minimum": round(min(samples), 8),
        "maximum": round(max(samples), 8),
        "robust_minimum": round(robust_minimum, 8),
        "robust_maximum": round(robust_maximum, 8),
        "robust_relative_spread": round((robust_maximum - robust_minimum) / max(middle, 1e-9), 8),
        "relative_spread": round((max(samples) - min(samples)) / max(middle, 1e-9), 8),
    }


def _reconstruction_metrics(source_segments: list[dict[str, Any]], derived_segments: list[dict[str, Any]], thickness: float) -> dict[str, float | None]:
    source_points = _sample_segments(source_segments)
    centerline_points = _sample_segments(derived_segments)
    if len(source_points) < 2 or len(centerline_points) < 2:
        return {"rms": None, "maximum_deviation": None, "coverage": 0.0}
    reconstructed = LineString(centerline_points).buffer(thickness / 2.0, quad_segs=32)
    source_boundary = LineString(source_points)
    if reconstructed.is_empty:
        return {"rms": None, "maximum_deviation": None, "coverage": 0.0}
    source_distances = [Point(point).distance(reconstructed.boundary) for point in source_points]
    reconstructed_points = _sample_segments([{"type": "LINE", "start": point, "end": next_point, "length": _distance(point, next_point)} for point, next_point in zip(centerline_points, centerline_points[1:])])
    reverse_distances = [Point(point).distance(source_boundary) for point in reconstructed_points]
    distances = source_distances + reverse_distances
    tolerance = max(0.05, thickness * 0.10)
    return {
        "rms": sqrt(sum(value * value for value in distances) / max(len(distances), 1)),
        "maximum_deviation": max(distances) if distances else None,
        "coverage": sum(value <= tolerance for value in distances) / max(len(distances), 1),
    }


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
    segments = _boundary_segments(profile)
    result: dict[str, Any] = {
        "representation": "GENERIC_CLOSED_CONTOUR",
        "classification_confidence": "LOW",
        "thickness_estimate": None,
        "coarse_width_hint": None,
        "median_thickness": None,
        "minimum_thickness": None,
        "maximum_thickness": None,
        "relative_spread": None,
        "cap_diagnostics": {},
        "classification_confidence_detail": {"score": 0.0, "band": "LOW", "non_calibrated": True},
        "classification_reasons": [],
    }
    if not profile.get("closed") or len(points) < 4:
        result["representation"] = "CENTERLINE_PATH" if not profile.get("closed") else "GENERIC_CLOSED_CONTOUR"
        return result
    polygon = Polygon(points)
    perimeter = sum(item["length"] for item in segments)
    area = abs(polygon.area)
    min_x, min_y, max_x, max_y = polygon.bounds
    extent = max(max_x - min_x, max_y - min_y, 1e-9)
    thickness = 2.0 * area / perimeter if perimeter > 1e-12 else None
    ratio = (thickness / extent) if thickness is not None else 1.0
    valid = polygon.is_valid and area > 1e-9 and perimeter > 1e-9
    coarse_width_hint = thickness
    nonzero_arcs = sum(1 for item in segments if item["type"] == "ARC")
    cap_1, cap_2 = _cap_pair(segments, thickness)
    cap_lengths = [segments[cap_1]["length"], segments[cap_2]["length"]]
    paired_thickness = sum(cap_lengths) / 2
    cap_spread = abs(cap_lengths[0] - cap_lengths[1]) / max(paired_thickness, 1e-9)
    chain_a, chain_b = _boundary_chains(segments, cap_1, cap_2)
    chain_lengths = [sum(item["length"] for item in chain) for chain in (chain_a, chain_b)]
    chain_spread = abs(chain_lengths[0] - chain_lengths[1]) / max(max(chain_lengths), 1e-9)
    thickness_diagnostics = _chain_thickness_diagnostics(chain_a, chain_b)
    has_curvature_support = nonzero_arcs >= 1
    thickness_samples_valid = thickness_diagnostics["sample_count"] >= 20
    # End-cap transitions are intentionally excluded from the robust spread;
    # the regression drawing contains long tangent changes near both caps.
    thickness_spread_valid = (thickness_diagnostics["robust_relative_spread"] is not None and thickness_diagnostics["robust_relative_spread"] <= 0.80)
    signals = [valid, thickness_samples_valid, thickness_spread_valid, cap_spread <= 0.08, chain_spread <= 0.18, paired_thickness / extent <= 0.20, has_curvature_support]
    score = sum(1 for value in signals if value) / len(signals)
    if valid and all(signals):
        result.update({
            "representation": "STRIP_OUTLINE",
            "classification_confidence": "MEDIUM" if score < 1.0 else "HIGH",
            "thickness_estimate": thickness_diagnostics["median"],
            "coarse_width_hint": round(coarse_width_hint, 8) if coarse_width_hint is not None else None,
            "median_thickness": thickness_diagnostics["median"],
            "minimum_thickness": thickness_diagnostics["minimum"],
            "maximum_thickness": thickness_diagnostics["maximum"],
            "relative_spread": thickness_diagnostics["robust_relative_spread"],
            "cap_diagnostics": {"cap_1_segment": cap_1, "cap_2_segment": cap_2, "cap_length_1": cap_lengths[0], "cap_length_2": cap_lengths[1], "cap_thickness_hint": paired_thickness, "chain_length_1": chain_lengths[0], "chain_length_2": chain_lengths[1], "thickness_samples": thickness_diagnostics},
            "classification_confidence_detail": {"score": score, "band": "HIGH" if score >= 0.9 else "MEDIUM", "non_calibrated": True},
            "classification_reasons": ["valid_simple_closed_boundary", "sampled_constant_thickness", "consistent_end_caps", "comparable_boundary_chain_lengths", "source_curvature_support"],
        })
    elif valid:
        reason = "insufficient_independent_strip_signals"
        if not has_curvature_support:
            reason = "straight_closed_boundary_is_ambiguous_without_context"
        result.update({"representation": "CLOSED_SECTION_BOUNDARY", "classification_confidence": "MEDIUM", "classification_confidence_detail": {"score": score, "band": "MEDIUM", "non_calibrated": True}, "classification_reasons": ["valid_closed_boundary", reason], "median_thickness": thickness_diagnostics["median"], "minimum_thickness": thickness_diagnostics["minimum"], "maximum_thickness": thickness_diagnostics["maximum"], "relative_spread": thickness_diagnostics["robust_relative_spread"], "cap_diagnostics": {"cap_1_segment": cap_1, "cap_2_segment": cap_2, "cap_length_1": cap_lengths[0], "cap_length_2": cap_lengths[1], "cap_thickness_hint": paired_thickness, "chain_length_1": chain_lengths[0], "chain_length_2": chain_lengths[1], "thickness_samples": thickness_diagnostics}})
    else:
        result["representation"] = "AMBIGUOUS"
        result["classification_reasons"] = ["invalid_or_degenerate_closed_boundary"]
    return result


def derive_centerline_candidate(profile_candidate: dict[str, Any]) -> dict[str, Any] | None:
    classification = classify_closed_profile(profile_candidate["profile"])
    if classification["representation"] != "STRIP_OUTLINE":
        return None
    boundaries = _boundary_segments(profile_candidate["profile"])
    cap_1 = classification["cap_diagnostics"]["cap_1_segment"]
    cap_2 = classification["cap_diagnostics"]["cap_2_segment"]
    chain_a, chain_b = _boundary_chains(boundaries, cap_1, cap_2)
    derived_segments, points = _analytic_centerline(chain_a, chain_b, float(classification["median_thickness"]))
    if len(points) < 2 or not derived_segments:
        return None
    profile_id = f"{profile_candidate['profile_id']}-centerline"
    vertices = [{"vertex_id": f"{profile_id}-v-{index + 1:04d}", "x": round(point[0], 8), "y": round(point[1], 8)} for index, point in enumerate(points)]
    segments = []
    for index, item in enumerate(derived_segments):
        segment = {"segment_id": f"{profile_id}-s-{index + 1:04d}", "type": item["type"], "start_vertex_id": vertices[index]["vertex_id"], "end_vertex_id": vertices[index + 1]["vertex_id"]}
        if item["type"] == "ARC":
            segment.update({"center": {"x": round(item["center"]["x"], 8), "y": round(item["center"]["y"], 8)}, "radius": round(item["radius"], 8), "clockwise": item["clockwise"]})
        segments.append(segment)
    geometric_centerline_length = sum(_segment_length(item) for item in derived_segments)
    chain_lengths = [sum(float(item["length"]) for item in chain) for chain in (chain_a, chain_b)]
    paired_boundary_length = sum(chain_lengths) / 2.0
    source = profile_candidate["profile"]
    reconstruction = _reconstruction_metrics(boundaries, derived_segments, float(classification["median_thickness"]))
    approximated_sections = sum(1 for item in derived_segments if item.get("approximated"))
    analytic_line_count = sum(1 for item in derived_segments if item["type"] == "LINE" and not item.get("approximated"))
    analytic_arc_count = sum(1 for item in derived_segments if item["type"] == "ARC" and not item.get("approximated"))
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
            "median_thickness": classification["median_thickness"],
            "minimum_thickness": classification["minimum_thickness"],
            "maximum_thickness": classification["maximum_thickness"],
            "relative_spread": classification["relative_spread"],
            "cap_diagnostics": classification["cap_diagnostics"],
            "derivation_method": "ANALYTIC_OFFSET_ARCS_WITH_ARCLENGTH_CHAIN_ALIGNMENT",
            "derivation_version": STRIP_CENTERLINE_DERIVATION_VERSION,
            "developed_length": round(paired_boundary_length, 8),
            "geometric_centerline_length": round(geometric_centerline_length, 8),
            "developed_length_method": "PAIRED_BOUNDARY_ANALYTIC_ARCLENGTH_AVERAGE",
            "boundary_reconstruction_rms": round(float(reconstruction["rms"]), 8) if reconstruction["rms"] is not None else None,
            "boundary_reconstruction_maximum_deviation": round(float(reconstruction["maximum_deviation"]), 8) if reconstruction["maximum_deviation"] is not None else None,
            "boundary_reconstruction_coverage": round(float(reconstruction["coverage"]), 8),
            "analytic_line_count": analytic_line_count,
            "analytic_arc_count": analytic_arc_count,
            "approximated_section_count": approximated_sections,
            "derivation_status": "ESTIMATED_REVIEW_REQUIRED",
            "warnings": ["DERIVED_CENTERLINE_ESTIMATE_REQUIRES_ENGINEER_REVIEW"] + (["DERIVED_CENTERLINE_APPROXIMATED_LOCALLY"] if approximated_sections else []),
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
        "median_thickness": classification["median_thickness"],
        "minimum_thickness": classification["minimum_thickness"],
        "maximum_thickness": classification["maximum_thickness"],
        "relative_spread": classification["relative_spread"],
        "thickness_sample_count": classification["cap_diagnostics"]["thickness_samples"].get("sample_count", 0),
        "cap_thickness_hint": classification["cap_diagnostics"].get("cap_thickness_hint"),
        "cap_diagnostics": classification["cap_diagnostics"],
        "derivation_version": STRIP_CENTERLINE_DERIVATION_VERSION,
        "developed_length": round(paired_boundary_length, 8),
        "geometric_centerline_length": round(geometric_centerline_length, 8),
        "analytic_line_count": analytic_line_count,
        "analytic_arc_count": analytic_arc_count,
        "approximated_section_count": approximated_sections,
        "classification_confidence_detail": classification["classification_confidence_detail"],
        "warnings": sorted(set(profile_candidate.get("warnings", []) + ["DERIVED_CENTERLINE_ESTIMATE_REQUIRES_ENGINEER_REVIEW"] + (["DERIVED_CENTERLINE_APPROXIMATED_LOCALLY"] if approximated_sections else []))),
    })
    from rollform_extractor.visual_cad_profile_detection import thumbnail_svg
    candidate["thumbnail_svg"] = thumbnail_svg(profile)
    return candidate
