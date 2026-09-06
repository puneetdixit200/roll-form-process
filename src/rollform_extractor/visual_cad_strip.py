"""Conservative interpretation of closed CAD strip outlines.

The importer keeps the source boundary as-is.  This module only creates a
second, explicitly derived centerline candidate when independent geometric
signals suggest that the closed boundary is a constant-width strip rather
than a section that should be manufactured as a closed loop.
"""
from __future__ import annotations

from math import atan2, cos, hypot, pi, sin
from typing import Any

from shapely.geometry import LineString, Polygon


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


def _analytic_centerline(chain: list[dict[str, Any]], opposite: list[dict[str, Any]], thickness: float) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    """Build a mostly analytic centerline from one boundary chain.

    Arc pairing is deliberately conservative.  A source arc is promoted only
    when an opposite arc occupies the same normalized chain position; other
    pieces remain exact source-chain lines and are marked by the caller.
    """
    if not chain:
        return [], []
    total = sum(item["length"] for item in chain)
    opposite_total = sum(item["length"] for item in opposite)
    output: list[dict[str, Any]] = []
    points: list[tuple[float, float]] = []
    cursor = 0.0
    current = chain[0]["start"]
    first_side = chain[0].get("cap_side_start")
    if first_side and first_side != current:
        output.append({"type": "LINE", "start": current, "end": first_side})
        points.append(current)
        current = first_side
    for index, source in enumerate(chain):
        midpoint_position = (cursor + float(source["length"]) / 2) / max(total, 1e-12)
        counterpart = _chain_position(opposite, midpoint_position)
        promote_arc = source["type"] == "ARC" and counterpart and counterpart["type"] == "ARC"
        if promote_arc:
            center = {"x": (source["center"]["x"] + counterpart["center"]["x"]) / 2, "y": (source["center"]["y"] + counterpart["center"]["y"]) / 2}
            radius = (float(source["radius"]) + float(counterpart["radius"])) / 2
            source_start_angle = atan2(source["start"][1] - source["center"]["y"], source["start"][0] - source["center"]["x"])
            start = _point_on_arc({"center": center, "radius": radius}, source_start_angle)
            if output:
                output[-1]["end"] = start
            current = start
            start_angle = source_start_angle
            sweep = _arc_sweep(source)
            end = _point_on_arc({"center": center, "radius": radius}, start_angle + (-sweep if source.get("clockwise") else sweep))
            item = {"type": "ARC", "start": current, "end": end, "center": center, "radius": radius, "clockwise": bool(source.get("clockwise", False))}
        else:
            end = source["end"]
            item = {"type": "LINE", "start": current, "end": end}
        output.append(item)
        points.append(item["start"])
        current = item["end"]
        cursor += float(source["length"])
    points.append(current)
    points = [output[0]["start"]] + [item["end"] for item in output]
    return output, points


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
    signals = [valid, nonzero_arcs >= 2, cap_spread <= 0.08, chain_spread <= 0.18, paired_thickness / extent <= 0.20]
    score = sum(1 for value in signals if value) / len(signals)
    if valid and all(signals):
        result.update({
            "representation": "STRIP_OUTLINE",
            "classification_confidence": "MEDIUM" if score < 1.0 else "HIGH",
            "thickness_estimate": round(paired_thickness, 8),
            "coarse_width_hint": round(coarse_width_hint, 8) if coarse_width_hint is not None else None,
            "median_thickness": round(paired_thickness, 8),
            "minimum_thickness": round(min(cap_lengths), 8),
            "maximum_thickness": round(max(cap_lengths), 8),
            "relative_spread": round(cap_spread, 8),
            "cap_diagnostics": {"cap_1_segment": cap_1, "cap_2_segment": cap_2, "cap_length_1": cap_lengths[0], "cap_length_2": cap_lengths[1], "chain_length_1": chain_lengths[0], "chain_length_2": chain_lengths[1]},
            "classification_confidence_detail": {"score": score, "band": "HIGH" if score >= 0.9 else "MEDIUM", "non_calibrated": True},
            "classification_reasons": ["valid_simple_closed_boundary", "consistent_end_caps", "comparable_boundary_chain_lengths", "source_arc_support"],
        })
    elif valid:
        result.update({"representation": "CLOSED_SECTION_BOUNDARY", "classification_confidence": "MEDIUM", "classification_confidence_detail": {"score": score, "band": "MEDIUM", "non_calibrated": True}, "classification_reasons": ["valid_closed_boundary", "insufficient_independent_strip_signals"]})
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
    centerline_length = sum(_segment_length(item) for item in derived_segments)
    source = profile_candidate["profile"]
    source_polygon = Polygon(_ring_points(source))
    line_points = points
    reconstructed = LineString(line_points).buffer(float(classification["median_thickness"]) / 2, quad_segs=32)
    boundary_rms = reconstructed.boundary.hausdorff_distance(source_polygon.boundary) if not reconstructed.is_empty else None
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
            "developed_length": round(centerline_length, 8),
            "boundary_reconstruction_rms": round(float(boundary_rms), 8) if boundary_rms is not None else None,
            "boundary_reconstruction_maximum_deviation": round(float(boundary_rms), 8) if boundary_rms is not None else None,
            "boundary_reconstruction_coverage": 1.0 if boundary_rms is not None else 0.0,
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
        "median_thickness": classification["median_thickness"],
        "minimum_thickness": classification["minimum_thickness"],
        "maximum_thickness": classification["maximum_thickness"],
        "relative_spread": classification["relative_spread"],
        "cap_diagnostics": classification["cap_diagnostics"],
        "derivation_version": STRIP_CENTERLINE_DERIVATION_VERSION,
        "developed_length": round(centerline_length, 8),
        "classification_confidence_detail": classification["classification_confidence_detail"],
        "warnings": sorted(set(profile_candidate.get("warnings", []) + ["DERIVED_CENTERLINE_ESTIMATE_REQUIRES_ENGINEER_REVIEW"])),
    })
    from rollform_extractor.visual_cad_profile_detection import thumbnail_svg
    candidate["thumbnail_svg"] = thumbnail_svg(profile)
    return candidate
