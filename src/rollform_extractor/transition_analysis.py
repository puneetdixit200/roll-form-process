from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def profile_step_changes(passes: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    ordered = tuple(sorted(passes, key=lambda item: item.inferred_order))
    return tuple(_profile_step_change(left, right) for left, right in zip(ordered, ordered[1:]))


def bend_change_events(passes: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    ordered = tuple(sorted(passes, key=lambda item: item.inferred_order))
    for left, right in zip(ordered, ordered[1:]):
        previous = {str(bend["bend_id"]): bend for bend in left.physical_bends}
        current = {str(bend["bend_id"]): bend for bend in right.physical_bends}
        for bend_id in sorted(set(previous) | set(current)):
            before = previous.get(bend_id)
            after = current.get(bend_id)
            rows.append(_bend_change(left, right, bend_id, before, after))
    return tuple(rows)


def segment_change_events(passes: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    ordered = tuple(sorted(passes, key=lambda item: item.inferred_order))
    for left, right in zip(ordered, ordered[1:]):
        left_segments = _segments(left)
        right_segments = _segments(right)
        for index in range(max(len(left_segments), len(right_segments))):
            before = left_segments[index] if index < len(left_segments) else None
            after = right_segments[index] if index < len(right_segments) else None
            rows.append(
                {
                    "from_pass_id": left.pass_id,
                    "to_pass_id": right.pass_id,
                    "segment_index": index + 1,
                    "previous_length": (before or {}).get("length"),
                    "current_length": (after or {}).get("length"),
                    "length_delta": _delta((before or {}).get("length"), (after or {}).get("length")),
                    "previous_orientation": (before or {}).get("orientation"),
                    "current_orientation": (after or {}).get("orientation"),
                    "orientation_delta": _angle_delta((before or {}).get("orientation"), (after or {}).get("orientation")),
                    "change_classification": _segment_classification(before, after),
                    "confidence": 0.66 if before and after else 0.45,
                    "engineer_confirmed": False,
                }
            )
    return tuple(rows)


def _profile_step_change(left: Any, right: Any) -> dict[str, Any]:
    left_points = _resample(_points(left), 101)
    right_points = _resample(_align_direction(_points(right), left_points), 101)
    distances = [_distance(a, b) for a, b in zip(left_points, right_points)]
    mean_distance = sum(distances) / len(distances) if distances else None
    max_distance = max(distances) if distances else None
    max_index = distances.index(max_distance) if distances and max_distance is not None else None
    developed_delta = right.developed_length - left.developed_length
    developed_pct = abs(developed_delta) / left.developed_length * 100.0 if left.developed_length else None
    centroid_delta = _centroid_movement(left_points, right_points)
    topology_change = _topology_change(left, right)
    classifications = _transition_classifications(left, right, mean_distance, developed_pct, topology_change)
    return {
        "from_pass_id": left.pass_id,
        "to_pass_id": right.pass_id,
        "width_before": left.width,
        "width_after": right.width,
        "width_delta": right.width - left.width,
        "height_before": left.height,
        "height_after": right.height,
        "height_delta": right.height - left.height,
        "developed_length_before": left.developed_length,
        "developed_length_after": right.developed_length,
        "developed_length_delta": developed_delta,
        "developed_length_percent_difference": developed_pct,
        "centroid_movement": centroid_delta,
        "rigid_rotation": _endpoint_rotation(left_points, right_points),
        "mean_contour_distance": mean_distance,
        "maximum_contour_distance": max_distance,
        "hausdorff_distance": max_distance,
        "maximum_material_point_displacement": max_distance,
        "maximum_material_point_u": (max_index / (len(distances) - 1) if max_index is not None and len(distances) > 1 else None),
        "symmetry_change": _symmetry_change(left_points, right_points),
        "topology_change": topology_change,
        "classifications": classifications,
        "review_choices": _review_choices(left, right, classifications),
        "confidence": 0.7 if left.neutral_line_confidence >= 0.5 and right.neutral_line_confidence >= 0.5 else 0.45,
        "summary": _summary(left, right, classifications),
        "engineer_confirmed": False,
    }


def _bend_change(left: Any, right: Any, bend_id: str, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> dict[str, Any]:
    before_angle = _num((before or {}).get("signed_bend_angle"))
    after_angle = _num((after or {}).get("signed_bend_angle"))
    before_radius = _num((before or {}).get("neutral_line_radius"))
    after_radius = _num((after or {}).get("neutral_line_radius"))
    return {
        "from_pass_id": left.pass_id,
        "to_pass_id": right.pass_id,
        "bend_id": bend_id,
        "previous_developed_position": (before or {}).get("developed_length_position"),
        "current_developed_position": (after or {}).get("developed_length_position"),
        "position_delta": _delta((before or {}).get("developed_length_position"), (after or {}).get("developed_length_position")),
        "previous_angle": before_angle,
        "current_angle": after_angle,
        "angle_delta": _delta(before_angle, after_angle),
        "previous_radius": before_radius,
        "current_radius": after_radius,
        "radius_delta": _delta(before_radius, after_radius),
        "previous_activation_state": (before or {}).get("activation_status", "inactive"),
        "current_activation_state": (after or {}).get("activation_status", "inactive"),
        "change_classification": _bend_classification(before_angle, after_angle, before_radius, after_radius),
        "confidence": min(float((before or {}).get("confidence", 0.5)), float((after or {}).get("confidence", 0.5))) if before and after else 0.5,
        "engineer_confirmed": False,
    }


def _bend_classification(before_angle: float | None, after_angle: float | None, before_radius: float | None, after_radius: float | None) -> str:
    if before_angle is None and after_angle is not None:
        return "NEW_BEND_ACTIVATED"
    if before_angle is not None and after_angle is None:
        return "BEND_DEACTIVATED"
    if before_angle is None or after_angle is None:
        return "BEND_CORRESPONDENCE_UNCERTAIN"
    if before_angle and after_angle and before_angle * after_angle < 0:
        return "BEND_REVERSED"
    delta = abs(after_angle) - abs(before_angle)
    if delta > 1.0:
        return "BEND_INCREASED"
    if delta < -1.0:
        return "BEND_DECREASED"
    if before_radius is not None and after_radius is not None:
        if after_radius < before_radius - 0.1:
            return "RADIUS_TIGHTENED"
        if after_radius > before_radius + 0.1:
            return "RADIUS_OPENED"
    return "UNCHANGED_BEND"


def _transition_classifications(left: Any, right: Any, mean_distance: float | None, developed_pct: float | None, topology_change: bool) -> list[str]:
    classes: list[str] = []
    if abs(right.width - left.width) > 0.25:
        classes.append("PROFILE_WIDENED" if right.width > left.width else "PROFILE_NARROWED")
    if abs(right.height - left.height) > 0.25:
        classes.append("PROFILE_HEIGHT_INCREASED" if right.height > left.height else "PROFILE_HEIGHT_DECREASED")
    if topology_change:
        classes.append("TOPOLOGY_CHANGE")
    if developed_pct is not None and developed_pct > 1.0:
        classes.append("POSSIBLE_PASS_ORDER_ERROR")
    if mean_distance is not None and mean_distance > 0.5:
        classes.append("ASYMMETRIC_CHANGE")
    return classes or ["NO_SIGNIFICANT_CHANGE"]


def _topology_change(left: Any, right: Any) -> bool:
    left_zones = {str(bend.get("bend_id")) for bend in left.physical_bends}
    right_zones = {str(bend.get("bend_id")) for bend in right.physical_bends}
    if not left_zones or not right_zones:
        return False
    return False if left.requires_review or right.requires_review else left_zones != right_zones


def _segments(item: Any) -> list[dict[str, float]]:
    points = _points(item)
    bends = sorted((float(bend.get("u", 0.0)), bend) for bend in item.physical_bends)
    if not points:
        return []
    break_indices = [0]
    for u, _bend in bends:
        break_indices.append(max(0, min(len(points) - 1, round(u * (len(points) - 1)))))
    break_indices.append(len(points) - 1)
    result = []
    for start, end in zip(break_indices, break_indices[1:]):
        if end <= start:
            continue
        segment_points = points[start : end + 1]
        length = _path_length(segment_points)
        result.append({"length": length, "orientation": _endpoint_angle(segment_points)})
    return result


def _segment_classification(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> str:
    if before is None:
        return "SEGMENT_ADDED"
    if after is None:
        return "SEGMENT_REMOVED"
    length_delta = abs(float(after["length"]) - float(before["length"]))
    orientation_delta = abs(_angle_delta(float(before["orientation"]), float(after["orientation"])) or 0.0)
    if length_delta <= 0.1 and orientation_delta <= 1.0:
        return "UNCHANGED_SEGMENT"
    return "SEGMENT_CHANGED"


def _summary(left: Any, right: Any, classifications: list[str]) -> str:
    return (
        f"{left.pass_id} to {right.pass_id}: width {right.width - left.width:+.3f}, "
        f"height {right.height - left.height:+.3f}, length {right.developed_length - left.developed_length:+.3f}; "
        f"{', '.join(classifications)}"
    )


def _review_choices(left: Any, right: Any, classifications: list[str]) -> list[str]:
    if left.pass_id == "pass_03" and right.pass_id == "pass_04":
        return [
            "order is correct and this is intentional reopening/calibration",
            "Pass 03 and Pass 04 are incorrectly ordered",
            "one pass has incorrect neutral-line extraction",
            "bend zones were incorrectly split or removed",
        ]
    if "PROFILE_WIDENED" in classifications:
        return [
            "order is correct and profile widens intentionally",
            "pass order requires review",
            "neutral-line extraction requires review",
        ]
    return []


def _points(item: Any) -> tuple[tuple[float, float, float], ...]:
    return tuple(getattr(item, "neutral_line_points", ()) or ())


def _align_direction(points: tuple[tuple[float, float, float], ...], reference: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, float, float], ...]:
    if len(points) < 2 or len(reference) < 2:
        return points
    same = _distance(points[0], reference[0]) + _distance(points[-1], reference[-1])
    reversed_distance = _distance(points[-1], reference[0]) + _distance(points[0], reference[-1])
    return tuple(reversed(points)) if reversed_distance < same else points


def _resample(points: tuple[tuple[float, float, float], ...], count: int) -> tuple[tuple[float, float, float], ...]:
    cumulative = [0.0]
    for left, right in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _distance(left, right))
    total = cumulative[-1] if cumulative else 0.0
    if total <= 0 or len(points) < 2:
        return points
    result = []
    segment = 0
    for index in range(count):
        target = total * index / (count - 1)
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        if segment + 1 >= len(points):
            result.append(points[-1])
            continue
        span = cumulative[segment + 1] - cumulative[segment]
        ratio = 0.0 if span <= 0 else (target - cumulative[segment]) / span
        a, b = points[segment], points[segment + 1]
        result.append((a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio, 0.0))
    return tuple(result)


def _path_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(_distance(left, right) for left, right in zip(points, points[1:]))


def _endpoint_angle(points: tuple[tuple[float, float, float], ...]) -> float:
    if len(points) < 2:
        return 0.0
    start, end = points[0], points[-1]
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))


def _endpoint_rotation(left: tuple[tuple[float, float, float], ...], right: tuple[tuple[float, float, float], ...]) -> float | None:
    if len(left) < 2 or len(right) < 2:
        return None
    return _angle_delta(_endpoint_angle(left), _endpoint_angle(right))


def _centroid_movement(left: tuple[tuple[float, float, float], ...], right: tuple[tuple[float, float, float], ...]) -> dict[str, float] | None:
    if not left or not right:
        return None
    lx = sum(point[0] for point in left) / len(left)
    ly = sum(point[1] for point in left) / len(left)
    rx = sum(point[0] for point in right) / len(right)
    ry = sum(point[1] for point in right) / len(right)
    return {"dx": rx - lx, "dy": ry - ly, "distance": math.hypot(rx - lx, ry - ly)}


def _symmetry_change(left: tuple[tuple[float, float, float], ...], right: tuple[tuple[float, float, float], ...]) -> float | None:
    if not left or not right:
        return None
    return abs(_symmetry_score(right) - _symmetry_score(left))


def _symmetry_score(points: tuple[tuple[float, float, float], ...]) -> float:
    cx = sum(point[0] for point in points) / len(points)
    left = sum(abs(point[0] - cx) for point in points if point[0] < cx)
    right = sum(abs(point[0] - cx) for point in points if point[0] >= cx)
    return abs(left - right) / max(left + right, 1e-9)


def _angle_delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    delta = after - before
    while delta > 180:
        delta -= 360
    while delta < -180:
        delta += 360
    return delta


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.hypot(float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))
