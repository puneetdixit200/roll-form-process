from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Iterable, Mapping

from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive, ProfileRecord, StationRecord


@dataclass(frozen=True)
class CompositeFlowerPass:
    pass_id: str
    composite_flower_id: str
    station_id: str
    profile_id: str
    inferred_order: int
    confirmed_order: int | None
    profile_type: str
    source_handles: tuple[str, ...]
    source_layers: tuple[str, ...]
    developed_length: float
    width: float
    height: float
    bend_count: int
    total_bend_angle: float
    raw_geometry_corner_count: int
    raw_total_turning_angle: float
    physical_forming_bend_count: int
    physical_total_bend_angle: float
    active_bend_count: int
    bend_signature: str
    vertex_turn_count: int
    physical_bends: tuple[Mapping[str, Any], ...]
    neutral_line_primitives: tuple[CadPrimitive, ...]
    neutral_line_points: tuple[tuple[float, float, float], ...]
    neutral_line_developed_length: float
    expected_neutral_length: float | None
    neutral_length_error: float | None
    neutral_length_error_percent: float | None
    sheet_thickness: float | None
    thickness_method: str
    thickness_sampling_count: int
    thickness_variation: float | None
    thickness_confidence: float
    engineer_confirmed_thickness: float | None
    neutral_line_method: str
    neutral_line_confidence: float
    confidence: float
    order_confidence: float
    duplicate_group_id: str | None
    requires_review: bool
    transform_matrix_4x4: tuple[tuple[float, ...], ...]
    profile: ProfileRecord
    duplicate_of: str | None = None
    similarity_score: float | None = None
    individual_profile_matches: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class CompositeFlowerRecord:
    composite_flower_id: str
    source_region_id: str
    pass_count: int
    sequence_confidence: float
    confirmed: bool
    source_bbox: BBox
    passes: tuple[CompositeFlowerPass, ...]


def build_composite_flowers(
    stations: Iterable[StationRecord],
    profiles: Iterable[ProfileRecord],
    entities: Iterable[CadEntityRecord],
) -> tuple[CompositeFlowerRecord, ...]:
    stations_by_id = {station.station_id: station for station in stations}
    entities_by_handle = {
        handle: entity
        for entity in entities
        for handle in (entity.source_handles or (entity.handle,))
    }
    individual = tuple(profile for profile in profiles if profile.method != "composite_flower_detector")
    groups: dict[str, list[ProfileRecord]] = {}
    for profile in profiles:
        if profile.method == "composite_flower_detector":
            groups.setdefault(profile.station_id, []).append(profile)
    records: list[CompositeFlowerRecord] = []
    for index, (station_id, group) in enumerate(sorted(groups.items()), start=1):
        station = stations_by_id[station_id]
        composite_id = f"composite_flower_{index:02d}"
        ordered = sorted(group, key=lambda item: int(item.features.get("composite_pass_index", 0)))
        duplicates = _duplicate_groups(ordered)
        passes = tuple(
            _pass_record(composite_id, profile, pass_index, entities_by_handle, duplicates, individual)
            for pass_index, profile in enumerate(ordered)
        )
        passes = _assign_canonical_bend_zones(passes)
        records.append(
            CompositeFlowerRecord(
                composite_flower_id=composite_id,
                source_region_id=station.station_id,
                pass_count=len(passes),
                sequence_confidence=min((item.order_confidence for item in passes), default=0.0),
                confirmed=bool(station.evidence.get("confirmed")),
                source_bbox=station.bbox,
                passes=passes,
            )
        )
    return tuple(records)


def _pass_record(
    composite_id: str,
    profile: ProfileRecord,
    zero_based_order: int,
    entities_by_handle: dict[str, CadEntityRecord],
    duplicates: dict[str, tuple[str | None, float | None, str | None]],
    individual_profiles: tuple[ProfileRecord, ...],
) -> CompositeFlowerPass:
    bbox = profile.features.get("bbox")
    width = float(bbox.max_x - bbox.min_x) if isinstance(bbox, BBox) else 0.0
    height = float(bbox.max_y - bbox.min_y) if isinstance(bbox, BBox) else 0.0
    raw_bend_angles = tuple(float(angle) for angle in profile.features.get("bend_angles", ()))
    neutral = _derive_neutral_line(profile, entities_by_handle)
    physical_bends = _bend_zones(neutral.points, profile.source_handles)
    neutral_length_error = neutral.developed_length - neutral.expected_length if neutral.expected_length else None
    canonical, similarity, group_id = duplicates.get(profile.profile_id, (None, None, None))
    source_layers = tuple(
        dict.fromkeys(
            entity.layer
            for handle in profile.source_handles
            if (entity := entities_by_handle.get(handle)) is not None
        )
    )
    return CompositeFlowerPass(
        pass_id=_pass_id(zero_based_order, len(individual_profiles), profile),
        composite_flower_id=composite_id,
        station_id=profile.station_id,
        profile_id=profile.profile_id,
        inferred_order=zero_based_order,
        confirmed_order=None,
        profile_type=_profile_representation(str(profile.features.get("profile_state", "INCOMPLETE_PROFILE"))),
        source_handles=profile.source_handles,
        source_layers=source_layers,
        developed_length=neutral.developed_length or float(profile.features.get("exact_length", 0.0)),
        width=width,
        height=height,
        bend_count=len(physical_bends),
        total_bend_angle=round(sum(float(bend["absolute_bend_angle"]) for bend in physical_bends), 3),
        raw_geometry_corner_count=len(raw_bend_angles),
        raw_total_turning_angle=sum(abs(angle) for angle in raw_bend_angles),
        physical_forming_bend_count=len(physical_bends),
        physical_total_bend_angle=round(sum(float(bend["absolute_bend_angle"]) for bend in physical_bends), 3),
        active_bend_count=sum(1 for bend in physical_bends if bend["activation_status"] != "inactive"),
        bend_signature=";".join(f"{bend['bend_id']}:{round(float(bend['signed_bend_angle']), 1)}" for bend in physical_bends),
        vertex_turn_count=sum(int(bend.get("contributing_vertex_count", 1)) for bend in physical_bends),
        physical_bends=tuple(physical_bends),
        neutral_line_primitives=neutral.primitives,
        neutral_line_points=neutral.points,
        neutral_line_developed_length=neutral.developed_length,
        expected_neutral_length=neutral.expected_length,
        neutral_length_error=neutral_length_error,
        neutral_length_error_percent=(neutral_length_error / neutral.expected_length * 100.0 if neutral.expected_length else None),
        sheet_thickness=neutral.thickness,
        thickness_method=neutral.thickness_method,
        thickness_sampling_count=neutral.thickness_sampling_count,
        thickness_variation=neutral.thickness_variation,
        thickness_confidence=neutral.thickness_confidence,
        engineer_confirmed_thickness=None,
        neutral_line_method=neutral.method,
        neutral_line_confidence=neutral.confidence,
        confidence=profile.confidence,
        order_confidence=0.72,
        duplicate_group_id=group_id,
        requires_review=True,
        transform_matrix_4x4=_translation_to_origin_matrix(bbox),
        profile=profile,
        duplicate_of=canonical,
        similarity_score=similarity,
        individual_profile_matches=_individual_matches(profile, individual_profiles),
    )


def _pass_id(index: int, _individual_count: int, profile: ProfileRecord) -> str:
    total = int(profile.features.get("composite_pass_count", 0))
    if index == 0:
        return "pass_00_flat"
    if total and index == total - 1:
        return f"pass_{index:02d}_final"
    return f"pass_{index:02d}"


def _profile_representation(state: str) -> str:
    if state in {"CENTERLINE_PROFILE", "MULTI_ENTITY_OPEN_PROFILE"}:
        return "SOURCE_STRIP_OUTLINE"
    if state == "DOUBLE_BOUNDARY_PROFILE":
        return "DOUBLE_BOUNDARY_PROFILE"
    if state == "CLOSED_STRIP_PROFILE":
        return "CLOSED_STRIP_PROFILE"
    if state == "TRUE_CENTERLINE_PROFILE":
        return "TRUE_CENTERLINE_PROFILE"
    return "INCOMPLETE_PROFILE"


def _duplicate_groups(profiles: tuple[ProfileRecord, ...]) -> dict[str, tuple[str | None, float | None, str | None]]:
    result: dict[str, tuple[str | None, float | None, str | None]] = {}
    groups = 0
    for index, profile in enumerate(profiles):
        if profile.profile_id in result:
            continue
        for other in profiles[index + 1 :]:
            score = _similarity(profile, other)
            if score >= 0.985:
                groups += 1
                group_id = f"duplicate_group_{groups:02d}"
                result.setdefault(profile.profile_id, (None, None, group_id))
                result[other.profile_id] = (profile.profile_id, score, group_id)
    return result


def _individual_matches(profile: ProfileRecord, individual_profiles: tuple[ProfileRecord, ...]) -> tuple[Mapping[str, Any], ...]:
    matches = []
    for other in individual_profiles:
        score = _similarity(profile, other)
        if score >= 0.94:
            matches.append(
                {
                    "individual_profile_id": other.profile_id,
                    "similarity_score": score,
                    "exact_match": score >= 0.995,
                    "mirrored_match": False,
                    "geometric_difference": round(1.0 - score, 6),
                    "confirmed_link": False,
                }
            )
    return tuple(matches)


@dataclass(frozen=True)
class _NeutralLine:
    primitives: tuple[CadPrimitive, ...]
    points: tuple[tuple[float, float, float], ...]
    developed_length: float
    expected_length: float | None
    thickness: float | None
    thickness_method: str
    thickness_sampling_count: int
    thickness_variation: float | None
    thickness_confidence: float
    method: str
    confidence: float


@dataclass(frozen=True)
class _OutlineSplit:
    boundary_a: tuple[tuple[float, float, float], ...]
    boundary_b: tuple[tuple[float, float, float], ...]
    cap_lengths: tuple[float, float]


def _bend_zones(points: tuple[tuple[float, float, float], ...], source_handles: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
    points = _merge_collinear(_dedupe_points(points), 5.0)
    if len(points) < 3:
        return ()
    turns = []
    cumulative = _cumulative_lengths(points)
    total = cumulative[-1] if cumulative else 0.0
    if total <= 0:
        return ()
    for vertex_index, (left, center, right, s) in enumerate(zip(points, points[1:], points[2:], cumulative[1:]), start=1):
        angle = _signed_turn(left, center, right)
        if abs(angle) < 7.5 or abs(angle) > 165.0:
            continue
        turns.append(
            {
                "developed_length_position": s,
                "u": s / total,
                "x": center[0],
                "y": center[1],
                "signed_turn_angle": angle,
                "vertex_index": vertex_index,
                "point": center,
            }
        )
    return tuple(_consolidated_zone(index, group, points, cumulative, total, source_handles) for index, group in enumerate(_turn_groups(turns, total), start=1))


def _turn_groups(turns: list[dict[str, Any]], total_length: float) -> list[list[dict[str, Any]]]:
    if not turns:
        return []
    groups: list[list[dict[str, Any]]] = [[turns[0]]]
    for turn in turns[1:]:
        previous = groups[-1][-1]
        gap = float(turn["developed_length_position"]) - float(previous["developed_length_position"])
        same_direction = float(turn["signed_turn_angle"]) * float(previous["signed_turn_angle"]) >= 0
        if same_direction and total_length > 0 and gap / total_length <= 0.09:
            groups[-1].append(turn)
        else:
            groups.append([turn])
    return groups


def _consolidated_zone(
    index: int,
    group: list[dict[str, Any]],
    points: tuple[tuple[float, float, float], ...],
    cumulative: tuple[float, ...],
    total_length: float,
    source_handles: tuple[str, ...],
) -> dict[str, Any]:
    start_s = float(group[0]["developed_length_position"])
    end_s = float(group[-1]["developed_length_position"])
    center_s = (start_s + end_s) / 2.0
    signed = sum(float(turn["signed_turn_angle"]) for turn in group)
    first_vertex = int(group[0]["vertex_index"])
    last_vertex = int(group[-1]["vertex_index"])
    incoming = _segment_angle(points[max(0, first_vertex - 1)], points[first_vertex])
    outgoing = _segment_angle(points[last_vertex], points[min(len(points) - 1, last_vertex + 1)])
    zone_length = end_s - start_s if len(group) > 1 else _local_zone_length(group, cumulative)
    radius = abs(zone_length / math.radians(signed)) if zone_length > 0 and abs(signed) > 1e-6 else None
    zone_id = f"BZ{index:02d}"
    return {
        "bend_id": zone_id,
        "bend_zone_id": zone_id,
        "developed_length_position": center_s,
        "start_developed_coordinate": start_s,
        "end_developed_coordinate": end_s,
        "centre_developed_coordinate": center_s,
        "u": center_s / total_length if total_length else 0.0,
        "x": sum(float(turn["x"]) for turn in group) / len(group),
        "y": sum(float(turn["y"]) for turn in group) / len(group),
        "signed_bend_angle": round(signed, 3),
        "absolute_bend_angle": round(abs(signed), 3),
        "total_signed_turning_angle": round(signed, 3),
        "total_absolute_turning_angle": round(sum(abs(float(turn["signed_turn_angle"])) for turn in group), 3),
        "bend_direction": "up" if signed >= 0 else "down",
        "zone_length": zone_length,
        "incoming_tangent": incoming,
        "outgoing_tangent": outgoing,
        "inside_radius": radius,
        "outside_radius": radius,
        "neutral_line_radius": radius,
        "estimated_radius": radius,
        "contributing_vertices": [
            {
                "vertex_index": int(turn["vertex_index"]),
                "developed_length_position": float(turn["developed_length_position"]),
                "u": float(turn["u"]),
                "signed_turn_angle": round(float(turn["signed_turn_angle"]), 3),
                "point": turn["point"],
            }
            for turn in group
        ],
        "contributing_vertex_count": len(group),
        "source_entity_handles": source_handles,
        "contributing_source_handles": source_handles,
        "confidence": 0.72 if len(group) == 1 else 0.78,
        "activation_status": "forming",
    }


def _assign_canonical_bend_zones(passes: tuple[CompositeFlowerPass, ...]) -> tuple[CompositeFlowerPass, ...]:
    tracks: list[dict[str, Any]] = []
    next_id = 1
    result: list[CompositeFlowerPass] = []
    for item in passes:
        assigned: set[str] = set()
        remapped = []
        for bend in sorted(item.physical_bends, key=lambda value: float(value.get("u", 0.0))):
            track = _best_bend_track(bend, tracks, assigned)
            if track is None:
                track = {"bend_id": f"BZ{next_id:02d}", "u": float(bend.get("u", 0.0)), "angle": float(bend.get("signed_bend_angle", 0.0))}
                tracks.append(track)
                next_id += 1
            else:
                track["u"] = (float(track["u"]) * 0.6) + (float(bend.get("u", 0.0)) * 0.4)
                track["angle"] = float(bend.get("signed_bend_angle", 0.0))
            assigned.add(str(track["bend_id"]))
            remapped.append({**dict(bend), "bend_id": str(track["bend_id"]), "bend_zone_id": str(track["bend_id"])})
        signature = ";".join(f"{bend['bend_id']}:{round(float(bend['signed_bend_angle']), 1)}" for bend in remapped)
        result.append(
            replace(
                item,
                physical_bends=tuple(remapped),
                bend_signature=signature,
                physical_forming_bend_count=len(remapped),
                bend_count=len(remapped),
                active_bend_count=sum(1 for bend in remapped if bend["activation_status"] != "inactive"),
                physical_total_bend_angle=round(sum(float(bend["absolute_bend_angle"]) for bend in remapped), 3),
                total_bend_angle=round(sum(float(bend["absolute_bend_angle"]) for bend in remapped), 3),
            )
        )
    return tuple(result)


def _best_bend_track(bend: Mapping[str, Any], tracks: list[dict[str, Any]], assigned: set[str]) -> dict[str, Any] | None:
    bend_u = float(bend.get("u", 0.0))
    bend_angle = float(bend.get("signed_bend_angle", 0.0))
    best = None
    best_cost = 999.0
    for track in tracks:
        if str(track["bend_id"]) in assigned:
            continue
        u_cost = abs(float(track["u"]) - bend_u)
        sign_cost = 0.03 if float(track.get("angle", 0.0)) * bend_angle < 0 else 0.0
        cost = u_cost + sign_cost
        if cost < best_cost:
            best = track
            best_cost = cost
    return best if best_cost <= 0.075 else None


def _derive_neutral_line(profile: ProfileRecord, entities_by_handle: dict[str, CadEntityRecord]) -> _NeutralLine:
    primitives = tuple(
        primitive
        for handle in profile.source_handles
        if (entity := entities_by_handle.get(handle)) is not None
        for primitive in (entity.normalized_primitives or entity.original_primitives)
    ) or tuple(profile.features.get("normalized_primitives", ()))
    for primitive in primitives:
        points = _polyline_vertices(primitive)
        if len(points) >= 4 and (primitive.attributes.get("closed") or _is_closed_path(points)):
            neutral_points, thickness_samples, expected_length = _neutral_from_closed_outline(points)
            if len(neutral_points) >= 2:
                thickness = _median(thickness_samples)
                variation = _variation(thickness_samples)
                return _neutral_result(
                    profile.profile_id,
                    neutral_points,
                    thickness,
                    "explicit_end_cap_distance" if len(thickness_samples) == 2 else "median_paired_boundary_distance",
                    len(thickness_samples),
                    variation,
                    0.78 if thickness is not None else 0.45,
                    "paired_boundary_midline",
                    0.74,
                    expected_length,
                )
    points = tuple(point for primitive in primitives for point in _primitive_points(primitive))
    if len(points) >= 2:
        return _neutral_result(profile.profile_id, points, None, "unavailable_open_geometry", 0, None, 0.2, "source_open_path", 0.35, None)
    bbox = profile.features.get("bbox")
    if isinstance(bbox, BBox):
        y = (bbox.min_y + bbox.max_y) / 2.0
        return _neutral_result(profile.profile_id, ((bbox.min_x, y, 0.0), (bbox.max_x, y, 0.0)), None, "bbox_fallback_no_thickness", 0, None, 0.1, "bbox_midline_fallback", 0.2, None)
    return _neutral_result(profile.profile_id, (), None, "unavailable", 0, None, 0.0, "unavailable", 0.0, None)


def _neutral_result(
    profile_id: str,
    points: tuple[tuple[float, float, float], ...],
    thickness: float | None,
    thickness_method: str,
    sampling_count: int,
    variation: float | None,
    thickness_confidence: float,
    method: str,
    confidence: float,
    expected_length: float | None,
) -> _NeutralLine:
    points = _orient_left_to_right(_dedupe_points(points))
    geometric_length = _path_length(points)
    primitive = CadPrimitive(
        "LWPOLYLINE",
        {"vertices": tuple({"point": point, "bulge": 0.0} for point in points), "closed": False},
        f"{profile_id}-neutral",
    ) if len(points) >= 2 else None
    return _NeutralLine(
        primitives=(primitive,) if primitive else (),
        points=points,
        developed_length=expected_length if expected_length is not None else geometric_length,
        expected_length=expected_length,
        thickness=thickness,
        thickness_method=thickness_method,
        thickness_sampling_count=sampling_count,
        thickness_variation=variation,
        thickness_confidence=thickness_confidence,
        method=method,
        confidence=confidence,
    )


def _neutral_from_closed_outline(points: tuple[tuple[float, float, float], ...]) -> tuple[tuple[tuple[float, float, float], ...], tuple[float, ...], float | None]:
    split = _split_outline(points)
    if split is None:
        return (), (), None
    boundary_a = _orient_left_to_right(split.boundary_a)
    boundary_b = _orient_left_to_right(split.boundary_b)
    expected_length = (_path_length(boundary_a) + _path_length(boundary_b)) / 2.0
    sample_us = sorted(set(_material_positions(boundary_a) + _material_positions(boundary_b)))
    if len(sample_us) < 2:
        return (), (), expected_length
    sampled_a = tuple(_point_at_u(boundary_a, u) for u in sample_us)
    sampled_b = tuple(_point_at_u(boundary_b, u) for u in sample_us)
    paired_samples = tuple(_distance(left, right) for left, right in zip(sampled_a, sampled_b))
    cap_lengths = split.cap_lengths
    thickness_samples = cap_lengths if _variation(cap_lengths) is not None and (_variation(cap_lengths) or 0.0) <= 0.1 else paired_samples
    neutral = tuple(((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0, 0.0) for left, right in zip(sampled_a, sampled_b))
    return neutral, thickness_samples, expected_length


def _split_outline(points: tuple[tuple[float, float, float], ...]) -> _OutlineSplit | None:
    open_points = points[:-1] if points and _distance(points[0], points[-1]) < 1e-9 else points
    n = len(open_points)
    if n < 4:
        return None
    edges = [(_distance(open_points[i], open_points[(i + 1) % n]), i) for i in range(n)]
    cap_indices = sorted(index for _length, index in sorted(edges)[:2])
    cap_lengths = tuple(length for length, _index in sorted(edges)[:2])
    a, b = cap_indices
    path1 = _cyclic_path(open_points, (a + 1) % n, b)
    path2 = _cyclic_path(open_points, (b + 1) % n, a)
    if len(path1) < 2 or len(path2) < 2:
        return None
    return _OutlineSplit(path1, path2, (float(cap_lengths[0]), float(cap_lengths[1])))


def _is_closed_path(points: tuple[tuple[float, float, float], ...]) -> bool:
    return len(points) >= 4 and _distance(points[0], points[-1]) <= 1e-5


def _sheet_thickness(width: float, height: float) -> float | None:
    if width <= 0 or height <= 0:
        return None
    return min(width, height)


def _polyline_vertices(primitive: CadPrimitive) -> tuple[tuple[float, float, float], ...]:
    if primitive.kind not in {"LWPOLYLINE", "POLYLINE"}:
        return ()
    return tuple(_point(vertex["point"]) for vertex in primitive.attributes.get("vertices", ()))


def _primitive_points(primitive: CadPrimitive) -> tuple[tuple[float, float, float], ...]:
    if primitive.kind == "LINE":
        return (_point(primitive.attributes["start"]), _point(primitive.attributes["end"]))
    if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        return _polyline_vertices(primitive)
    return ()


def _point(point) -> tuple[float, float, float]:
    return (float(point[0]), float(point[1]), float(point[2]) if len(point) > 2 else 0.0)


def _cyclic_path(points: tuple[tuple[float, float, float], ...], start: int, end_edge_start: int) -> tuple[tuple[float, float, float], ...]:
    result = [points[start]]
    index = start
    while index != end_edge_start:
        index = (index + 1) % len(points)
        result.append(points[index])
        if len(result) > len(points) + 1:
            break
    return tuple(result)


def _resample_path(points: tuple[tuple[float, float, float], ...], count: int) -> tuple[tuple[float, float, float], ...]:
    cumulative = _cumulative_lengths(points)
    total = cumulative[-1] if cumulative else 0.0
    if total <= 0 or count <= 1:
        return points
    result = []
    segment = 0
    for i in range(count):
        target = total * i / (count - 1)
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


def _material_positions(points: tuple[tuple[float, float, float], ...]) -> tuple[float, ...]:
    cumulative = _cumulative_lengths(points)
    total = cumulative[-1] if cumulative else 0.0
    if total <= 0:
        return ()
    return tuple(value / total for value in cumulative)


def _point_at_u(points: tuple[tuple[float, float, float], ...], u: float) -> tuple[float, float, float]:
    cumulative = _cumulative_lengths(points)
    total = cumulative[-1] if cumulative else 0.0
    if total <= 0:
        return points[0]
    target = total * u
    segment = 0
    while segment + 1 < len(cumulative) and cumulative[segment + 1] < target:
        segment += 1
    if segment + 1 >= len(points):
        return points[-1]
    span = cumulative[segment + 1] - cumulative[segment]
    ratio = 0.0 if span <= 0 else (target - cumulative[segment]) / span
    left, right = points[segment], points[segment + 1]
    return (left[0] + (right[0] - left[0]) * ratio, left[1] + (right[1] - left[1]) * ratio, 0.0)


def _cumulative_lengths(points: tuple[tuple[float, float, float], ...]) -> tuple[float, ...]:
    result = [0.0]
    for left, right in zip(points, points[1:]):
        result.append(result[-1] + _distance(left, right))
    return tuple(result)


def _path_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(_distance(left, right) for left, right in zip(points, points[1:]))


def _segment_angle(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.degrees(math.atan2(float(right[1]) - float(left[1]), float(right[0]) - float(left[0])))


def _local_zone_length(group: list[dict[str, Any]], cumulative: tuple[float, ...]) -> float:
    first = max(0, int(group[0]["vertex_index"]) - 1)
    last = min(len(cumulative) - 1, int(group[-1]["vertex_index"]) + 1)
    return max(0.0, cumulative[last] - cumulative[first])


def _dedupe_points(points: tuple[tuple[float, float, float], ...], tolerance: float = 1e-6) -> tuple[tuple[float, float, float], ...]:
    result = []
    for point in points:
        if not result or _distance(result[-1], point) > tolerance:
            result.append(point)
    return tuple(result)


def _merge_collinear(points: tuple[tuple[float, float, float], ...], angle_tolerance: float) -> tuple[tuple[float, float, float], ...]:
    if len(points) < 3:
        return points
    result = [points[0]]
    for left, center, right in zip(points, points[1:], points[2:]):
        if abs(_signed_turn(left, center, right)) >= angle_tolerance:
            result.append(center)
    result.append(points[-1])
    return tuple(result)


def _signed_turn(left, center, right) -> float:
    a1 = math.atan2(center[1] - left[1], center[0] - left[0])
    a2 = math.atan2(right[1] - center[1], right[0] - center[0])
    delta = math.degrees(a2 - a1)
    while delta > 180:
        delta -= 360
    while delta < -180:
        delta += 360
    return delta


def _distance(left, right) -> float:
    return math.hypot(float(right[0]) - float(left[0]), float(right[1]) - float(left[1]))


def _median(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _variation(values: tuple[float, ...]) -> float | None:
    center = _median(values)
    if center is None or center == 0:
        return None
    return (max(values) - min(values)) / center


def _orient_left_to_right(points: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, float, float], ...]:
    if len(points) >= 2 and points[0][0] > points[-1][0]:
        return tuple(reversed(points))
    return points


def _similarity(left: ProfileRecord, right: ProfileRecord) -> float:
    left_length = float(left.features.get("exact_length", 0.0))
    right_length = float(right.features.get("exact_length", 0.0))
    if left_length <= 0 or right_length <= 0:
        return 0.0
    length_score = 1.0 - min(abs(left_length - right_length) / max(left_length, right_length), 1.0)
    left_box = left.features.get("bbox")
    right_box = right.features.get("bbox")
    if not isinstance(left_box, BBox) or not isinstance(right_box, BBox):
        return length_score
    width_score = 1.0 - min(abs((left_box.max_x - left_box.min_x) - (right_box.max_x - right_box.min_x)) / max(left_box.max_x - left_box.min_x, right_box.max_x - right_box.min_x, 1.0), 1.0)
    height_score = 1.0 - min(abs((left_box.max_y - left_box.min_y) - (right_box.max_y - right_box.min_y)) / max(left_box.max_y - left_box.min_y, right_box.max_y - right_box.min_y, 1.0), 1.0)
    return round((length_score * 0.5) + (width_score * 0.25) + (height_score * 0.25), 6)


def _translation_to_origin_matrix(bbox) -> tuple[tuple[float, ...], ...]:
    if not isinstance(bbox, BBox):
        return ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
    return ((1.0, 0.0, 0.0, -bbox.min_x), (0.0, 1.0, 0.0, -bbox.min_y), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0))
