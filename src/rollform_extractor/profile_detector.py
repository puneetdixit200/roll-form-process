from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
from statistics import median
from typing import Iterable

from rollform_extractor.feature_extractor import primitive_length
from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive, ProfileRecord, StationRecord, WarningRecord


PROFILE_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}


@dataclass(frozen=True)
class ProfileDetectionResult:
    profiles: tuple[ProfileRecord, ...]
    warnings: tuple[WarningRecord, ...]
    method: str
    configuration_hash: str
    manual_review_required: bool


@dataclass(frozen=True)
class _Candidate:
    entities: tuple[CadEntityRecord, ...]
    length: float
    score: float

    @property
    def handles(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for entity in self.entities:
            for handle in entity.source_handles or (entity.handle,):
                seen.setdefault(handle, None)
        return tuple(seen)


def detect_profiles(
    stations: Iterable[StationRecord],
    entities: Iterable[CadEntityRecord],
    config,
    overrides=None,
) -> ProfileDetectionResult:
    config_hash = config.hash_for("profile_detection")
    station_records = tuple(stations)
    records = tuple(_drawing_entities(entities))
    by_handle = {handle: entity for entity in records for handle in (entity.source_handles or (entity.handle,))}
    profiles: list[ProfileRecord] = []
    warnings: list[WarningRecord] = []
    previous_length: float | None = None
    previous_entity_count: int | None = None
    for station in station_records:
        manual = _manual_handles(station, getattr(overrides, "profile_handles", {})) if overrides is not None else ()
        if manual:
            manual_entities = tuple(by_handle[handle] for handle in manual if handle in by_handle)
            profiles.append(_profile(station, manual_entities, manual, "manual_override", config_hash, 1.0))
            previous_length = profiles[-1].features["exact_length"]
            previous_entity_count = len(manual_entities)
            continue

        composite = _composite_flower_profiles(station, records, config, config_hash)
        if composite:
            profiles.extend(composite)
            previous_length = composite[-1].features["exact_length"]
            previous_entity_count = len(composite[-1].features.get("normalized_primitives", ()))
            continue

        candidates = _candidates(station, records, previous_length, previous_entity_count, config)
        if not candidates:
            warnings.append(_warning("profile_missing", "no profile candidate was detected", station.source_handles, config_hash, 0.0))
            continue
        best = candidates[0]
        margin = best.score - (candidates[1].score if len(candidates) > 1 else 0.0)
        if best.score < 0.6:
            warnings.append(
                _warning(
                    "profile_candidate_requires_review",
                    "best profile candidate is below the configured confidence threshold",
                    best.handles,
                    config_hash,
                    best.score,
                )
            )
            continue
        review = margin < config.profiles.minimum_score_margin
        if len(best.entities) == 1 and len(_station_entities(station, records)) > 1:
            review = True
            warnings.append(_warning("broken_profile_contour", "profile contour is disconnected", best.handles, config_hash, best.score))
        if len(candidates) > 1 and margin < config.profiles.minimum_score_margin:
            handles = tuple(dict.fromkeys(best.handles + candidates[1].handles))
            warnings.append(_warning("profile_ambiguity", "multiple plausible profile candidates were detected", handles, config_hash, best.score))
        profiles.append(_profile(station, best.entities, best.handles, "profile_detector", config_hash, best.score))
        previous_length = best.length
        previous_entity_count = len(best.entities)
    filtered_profiles, filter_warnings = _filter_sequence_profiles(tuple(profiles), station_records, config_hash)
    warnings.extend(filter_warnings)
    return ProfileDetectionResult(
        profiles=filtered_profiles,
        warnings=tuple(warnings),
        method="profile_detector",
        configuration_hash=config_hash,
        manual_review_required=bool(warnings) or any(profile.confidence < config.profiles.minimum_confidence for profile in filtered_profiles),
    )


def _drawing_entities(entities: Iterable[CadEntityRecord]):
    for entity in entities:
        if getattr(entity, "classification", "drawing_geometry") == "drawing_support":
            continue
        if entity.layout.lower() != "model" or entity.entity_type not in PROFILE_TYPES:
            continue
        yield entity


def _manual_handles(station: StationRecord, mapping) -> tuple[str, ...]:
    sequence_id = int(station.evidence.get("sequence_id") or 1)
    keys = (
        f"sequence_{sequence_id:02d}_stage_{station.sequence_index:02d}" if station.sequence_index else "",
        station.station_id,
        str(station.sequence_index or station.station_id.removeprefix("S")),
    )
    for key in keys:
        if key and key in mapping:
            return tuple(mapping[key])
    return ()


def _candidates(station: StationRecord, entities: tuple[CadEntityRecord, ...], previous_length: float | None, previous_entity_count: int | None, config) -> tuple[_Candidate, ...]:
    station_entities = _station_entities(station, entities)
    chains = _chains(station_entities, config.geometry.endpoint_join_tolerance_mm)
    lengths = [sum(_entity_length(entity) for entity in chain) for chain in chains]
    longest = max(lengths, default=1.0)
    candidates = []
    reference_candidates = []
    for chain, length in zip(chains, lengths):
        if _reference_chain(station, chain):
            reference_candidates.append(_Candidate(chain, length, 0.2))
            continue
        layer_score = sum(_profile_layer_score(entity) for entity in chain) / max(1, len(chain))
        length_score = length / longest if longest else 0.0
        continuity_score = 0.2 if len(chain) > 1 else 0.0
        contour_score = _thin_contour_score(station, chain)
        central_score = _central_gap_score(station, chain)
        explicit_score = 0.3 if layer_score >= 0.9 else 0.0
        topology_score = 0.1 if previous_entity_count is not None and len(chain) == previous_entity_count else 0.0
        consistency = _length_consistency(length, previous_length)
        penalty = _tooling_contour_penalty(station, chain)
        score = max(
            0.0,
            min(1.0, 0.15 * length_score + 0.2 * layer_score + 0.1 * continuity_score + contour_score + central_score + explicit_score + topology_score + consistency - penalty),
        )
        candidates.append(_Candidate(chain, length, score))
    selected = candidates or reference_candidates
    return tuple(sorted(selected, key=lambda candidate: (-candidate.score, -candidate.length, candidate.handles)))


def _station_entities(station: StationRecord, entities: tuple[CadEntityRecord, ...]) -> tuple[CadEntityRecord, ...]:
    handles = set(station.source_handles)
    return tuple(entity for entity in entities if handles.intersection(entity.source_handles or (entity.handle,)) or (entity.bbox and _contains(station.bbox, entity.bbox)))


def _chains(entities: tuple[CadEntityRecord, ...], tolerance: float) -> tuple[tuple[CadEntityRecord, ...], ...]:
    remaining = list(_dedupe(entities))
    chains = []
    while remaining:
        chain = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            chain_points = [point for entity in chain for point in _endpoints(entity)]
            for entity in list(remaining):
                if any(_distance(a, b) <= tolerance for a in chain_points for b in _endpoints(entity)):
                    chain.append(entity)
                    remaining.remove(entity)
                    changed = True
        chains.append(tuple(chain))
    return tuple(chains)


def _dedupe(entities):
    seen: set[str] = set()
    for entity in entities:
        key = "|".join(entity.source_handles or (entity.handle,))
        if key not in seen:
            seen.add(key)
            yield entity


def _profile(station: StationRecord, entities: tuple[CadEntityRecord, ...], handles: tuple[str, ...], method: str, config_hash: str, confidence: float) -> ProfileRecord:
    primitives = tuple(primitive for entity in entities for primitive in entity.normalized_primitives)
    sampled = tuple(point for entity in entities for point in entity.sampled_geometry)
    bbox = _union(tuple(entity.bbox for entity in entities if entity.bbox is not None))
    return ProfileRecord(
        profile_id=f"{station.station_id}-P1",
        station_id=station.station_id,
        source_handles=handles,
        method=method,
        configuration_hash=config_hash,
        confidence=confidence,
        features={
            "normalized_primitives": primitives,
            "sampled_points": sampled,
            "bbox": bbox,
            "exact_length": sum(primitive_length(primitive) for primitive in primitives),
            "developed_length_drawing_units": sum(primitive_length(primitive) for primitive in primitives),
            "profile_state": _profile_state(entities, primitives),
            "evidence": {"entity_count": len(entities), "measurement_units": "drawing_units"},
        },
    )


def _filter_sequence_profiles(
    profiles: tuple[ProfileRecord, ...],
    stations: tuple[StationRecord, ...],
    config_hash: str,
) -> tuple[tuple[ProfileRecord, ...], tuple[WarningRecord, ...]]:
    station_by_id = {station.station_id: station for station in stations}
    by_sequence: dict[int, list[ProfileRecord]] = {}
    for profile in profiles:
        station = station_by_id.get(profile.station_id)
        by_sequence.setdefault(_sequence_id(station), []).append(profile)

    accepted: list[ProfileRecord] = []
    warnings: list[WarningRecord] = []
    for sequence_profiles in by_sequence.values():
        ordered = sorted(sequence_profiles, key=lambda profile: station_by_id[profile.station_id].sequence_index or 0)
        lengths = [float(profile.features.get("exact_length", 0.0)) for profile in ordered if float(profile.features.get("exact_length", 0.0)) > 0]
        sequence_median = median(lengths) if lengths else 0.0
        for index, profile in enumerate(ordered):
            if profile.method == "composite_flower_detector":
                accepted.append(profile)
                continue
            length = float(profile.features.get("exact_length", 0.0))
            if sequence_median > 0 and length < sequence_median * 0.25:
                warnings.append(_warning("profile_rejected_short_outlier", "profile developed length is below 25 percent of the sequence median", profile.source_handles, config_hash, profile.confidence))
                continue
            if _tiny_isolated_profile(profile):
                warnings.append(_warning("profile_rejected_tiny_isolated_line", "profile consists only of one tiny isolated line", profile.source_handles, config_hash, profile.confidence))
                continue
            if not _has_neighbour_continuity(profile, ordered, index):
                warnings.append(_warning("profile_requires_review_no_neighbour_continuity", "profile has weak geometric continuity with adjacent profiles", profile.source_handles, config_hash, profile.confidence))
                continue
            evidence = {**dict(profile.features.get("evidence", {})), "sequence_median_developed_length": sequence_median}
            accepted.append(replace(profile, features={**dict(profile.features), "evidence": evidence}))
    return tuple(accepted), tuple(warnings)


def _composite_flower_profiles(
    station: StationRecord,
    entities: tuple[CadEntityRecord, ...],
    config,
    config_hash: str,
) -> tuple[ProfileRecord, ...]:
    station_entities = _station_entities(station, entities)
    chains = _chains(station_entities, config.geometry.endpoint_join_tolerance_mm)
    chain_rows = []
    for chain in chains:
        if len(chain) != 1 or chain[0].entity_type not in {"LWPOLYLINE", "POLYLINE"}:
            continue
        length = sum(_entity_length(entity) for entity in chain)
        bbox = _union(tuple(entity.bbox for entity in chain if entity.bbox is not None))
        if bbox is None or length < 50:
            continue
        if _primitive_closed(chain[0].normalized_primitives[0]):
            continue
        chain_rows.append((chain, length, bbox))
    if len(chain_rows) < 5:
        return ()
    lengths = [row[1] for row in chain_rows]
    length_median = median(lengths)
    similar = [row for row in chain_rows if length_median > 0 and abs(row[1] - length_median) / length_median <= 0.15]
    if len(similar) < 5 or _has_rotational_geometry(station_entities):
        return ()
    origins = [_origin(row[2]) for row in similar]
    origin_xs = [point[0] for point in origins]
    origin_ys = [point[1] for point in origins]
    if (max(origin_xs) - min(origin_xs) > 35) or (max(origin_ys) - min(origin_ys) > 3):
        return ()
    ordered = sorted(similar, key=lambda row: (_formed_height(row[2]), row[2].min_x))
    profiles = []
    for index, (chain, length, bbox) in enumerate(ordered, start=1):
        profile = _profile(station, chain, tuple(handle for entity in chain for handle in (entity.source_handles or (entity.handle,))), "composite_flower_detector", config_hash, 0.82)
        features = {
            **dict(profile.features),
            "composite_pass_index": index,
            "composite_pass_count": len(ordered),
            "profile_state": "MULTI_ENTITY_OPEN_PROFILE" if len(chain) > 1 else "CENTERLINE_PROFILE",
            "width_drawing_units": bbox.max_x - bbox.min_x,
            "height_drawing_units": bbox.max_y - bbox.min_y,
            "bend_angles": _bend_angles(chain),
            "evidence": {
                **dict(profile.features.get("evidence", {})),
                "composite_flower": True,
                "sequence_median_developed_length": length_median,
                "measurement_units": "drawing_units",
            },
        }
        profiles.append(replace(profile, profile_id=f"{station.station_id}-CF{index:02d}", features=features))
    return tuple(profiles)


def _origin(bbox: BBox) -> tuple[float, float]:
    return (bbox.min_x, bbox.min_y)


def _formed_height(bbox: BBox) -> float:
    return bbox.max_y - bbox.min_y


def _has_rotational_geometry(entities: tuple[CadEntityRecord, ...]) -> bool:
    for entity in entities:
        if entity.entity_type in {"CIRCLE", "ARC"}:
            return True
    return False


def _bend_angles(chain: tuple[CadEntityRecord, ...]) -> tuple[float, ...]:
    angles: list[float] = []
    points = tuple(point for entity in chain for point in _poly_points(entity))
    for left, center, right in zip(points, points[1:], points[2:]):
        a1 = math.atan2(center[1] - left[1], center[0] - left[0])
        a2 = math.atan2(right[1] - center[1], right[0] - center[0])
        delta = math.degrees(a2 - a1)
        while delta > 180:
            delta -= 360
        while delta < -180:
            delta += 360
        if abs(delta) > 1:
            angles.append(round(delta, 3))
    return tuple(angles)


def _poly_points(entity: CadEntityRecord) -> tuple[tuple[float, float, float], ...]:
    for primitive in entity.normalized_primitives:
        if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
            return tuple(_point(vertex["point"]) for vertex in primitive.attributes.get("vertices", ()))
    return tuple(_point(point) for point in entity.sampled_geometry)


def _tiny_isolated_profile(profile: ProfileRecord) -> bool:
    primitives = tuple(profile.features.get("normalized_primitives", ()))
    return len(primitives) == 1 and primitives[0].kind == "LINE" and float(profile.features.get("exact_length", 0.0)) <= 2.0


def _has_neighbour_continuity(profile: ProfileRecord, ordered: list[ProfileRecord], index: int) -> bool:
    if len(ordered) < 3:
        return True
    length = float(profile.features.get("exact_length", 0.0))
    neighbours = []
    if index > 0:
        neighbours.append(float(ordered[index - 1].features.get("exact_length", 0.0)))
    if index + 1 < len(ordered):
        neighbours.append(float(ordered[index + 1].features.get("exact_length", 0.0)))
    return any(other > 0 and abs(length - other) / other <= 0.75 for other in neighbours)


def _profile_state(entities: tuple[CadEntityRecord, ...], primitives: tuple[CadPrimitive, ...]) -> str:
    if any(_primitive_closed(primitive) for primitive in primitives):
        return "CLOSED_STRIP_PROFILE"
    if len(entities) > 1:
        return "MULTI_ENTITY_OPEN_PROFILE"
    if _parallel_surface_like(primitives):
        return "DOUBLE_BOUNDARY_PROFILE"
    return "CENTERLINE_PROFILE"


def _primitive_closed(primitive: CadPrimitive) -> bool:
    return bool(primitive.attributes.get("closed")) or primitive.kind in {"CIRCLE", "ELLIPSE"}


def _parallel_surface_like(primitives: tuple[CadPrimitive, ...]) -> bool:
    return len(primitives) == 2 and all(primitive.kind == "LINE" for primitive in primitives)


def _sequence_id(station: StationRecord | None) -> int:
    if station is None:
        return 1
    try:
        return int(station.evidence.get("sequence_id") or 1)
    except (TypeError, ValueError):
        return 1


def _entity_length(entity: CadEntityRecord) -> float:
    return sum(primitive_length(primitive) for primitive in entity.normalized_primitives)


def _profile_layer_score(entity: CadEntityRecord) -> float:
    text = f"{entity.layer} {entity.line_type or ''}".lower()
    if any(token in text for token in ("profile", "part", "strip", "material", "flower")):
        return 1.0
    if any(token in text for token in ("roller", "tool", "shaft", "baseline", "reference")):
        return 0.1
    return 0.5


def _reference_chain(station: StationRecord, chain: tuple[CadEntityRecord, ...]) -> bool:
    if len(chain) != 1:
        return False
    entity = chain[0]
    if not entity.bbox or not _is_single_horizontal_line(entity):
        return False
    station_width = max(station.bbox.max_x - station.bbox.min_x, 1.0)
    line_width = entity.bbox.max_x - entity.bbox.min_x
    if line_width < max(50.0, station_width * 0.55):
        return False
    return not _explicit_initial_flat_strip(station, entity)


def _explicit_initial_flat_strip(station: StationRecord, entity: CadEntityRecord) -> bool:
    text = f"{entity.layer} {entity.line_type or ''}".lower()
    if station.sequence_index not in (None, 0, 1):
        return False
    return any(token in text for token in ("flat_strip", "flat strip", "strip", "material", "profile"))


def _is_single_horizontal_line(entity: CadEntityRecord) -> bool:
    primitives = tuple(entity.normalized_primitives)
    if len(primitives) != 1 or primitives[0].kind != "LINE":
        return False
    start = _point(primitives[0].attributes["start"])
    end = _point(primitives[0].attributes["end"])
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    return dx > 0 and dy <= max(0.05, dx * 0.01)


def _thin_contour_score(station: StationRecord, chain: tuple[CadEntityRecord, ...]) -> float:
    bbox = _union(tuple(entity.bbox for entity in chain if entity.bbox is not None))
    if bbox is None:
        return 0.0
    width = max(bbox.max_x - bbox.min_x, 1e-9)
    height = max(bbox.max_y - bbox.min_y, 0.0)
    station_height = max(station.bbox.max_y - station.bbox.min_y, 1.0)
    thin = height <= max(station_height * 0.35, width * 0.25)
    has_shape = height > 0.02 or len(chain) > 1
    return 0.15 if thin and has_shape else 0.0


def _central_gap_score(station: StationRecord, chain: tuple[CadEntityRecord, ...]) -> float:
    bbox = _union(tuple(entity.bbox for entity in chain if entity.bbox is not None))
    if bbox is None:
        return 0.0
    station_center = (station.bbox.min_y + station.bbox.max_y) / 2.0
    chain_center = (bbox.min_y + bbox.max_y) / 2.0
    half_height = max((station.bbox.max_y - station.bbox.min_y) / 2.0, 1.0)
    return max(0.0, 0.35 * (1.0 - min(abs(chain_center - station_center) / half_height, 1.0)))


def _tooling_contour_penalty(station: StationRecord, chain: tuple[CadEntityRecord, ...]) -> float:
    bbox = _union(tuple(entity.bbox for entity in chain if entity.bbox is not None))
    if bbox is None:
        return 0.0
    width = bbox.max_x - bbox.min_x
    height = bbox.max_y - bbox.min_y
    station_height = max(station.bbox.max_y - station.bbox.min_y, 1.0)
    if len(chain) >= 4 and width > 30.0 and height > 5.0 and height < station_height * 0.25:
        return 0.25
    return 0.0


def _length_consistency(length: float, previous: float | None) -> float:
    if previous is None or previous <= 0:
        return 0.0
    return max(0.0, 0.15 * (1 - min(abs(length - previous) / previous, 1.0)))


def _endpoints(entity: CadEntityRecord):
    points = []
    for primitive in entity.normalized_primitives:
        attrs = primitive.attributes
        if primitive.kind == "LINE":
            points.extend((_point(attrs["start"]), _point(attrs["end"])))
        elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
            items = tuple(vertex["point"] if isinstance(vertex, Mapping) else vertex for vertex in attrs.get("vertices", attrs.get("points", ())))
            points.extend(_point(item) for item in items[:1] + items[-1:])
        elif primitive.kind == "ARC":
            center = _point(attrs["center"])
            radius = float(attrs["radius"])
            points.extend(
                (
                    _angle_point(center, radius, float(attrs["start_angle"])),
                    _angle_point(center, radius, float(attrs["end_angle"])),
                )
            )
    return tuple(points) or _first_last(tuple(_point(point) for point in entity.sampled_geometry))


def _contains(outer: BBox, inner: BBox) -> bool:
    return outer.min_x <= inner.min_x and outer.max_x >= inner.max_x and outer.min_y <= inner.min_y and outer.max_y >= inner.max_y


def _union(boxes: tuple[BBox, ...]) -> BBox | None:
    if not boxes:
        return None
    return BBox(min(box.min_x for box in boxes), min(box.min_y for box in boxes), max(box.max_x for box in boxes), max(box.max_y for box in boxes))


def _warning(code: str, message: str, handles: tuple[str, ...], config_hash: str, confidence: float) -> WarningRecord:
    return WarningRecord(code, message, handles, "profile_detector", config_hash, confidence)


def _distance(left, right) -> float:
    return sum((a - b) ** 2 for a, b in zip(_point(left), _point(right))) ** 0.5


def _angle_point(center, radius: float, angle: float):
    return (
        center[0] + radius * math.cos(math.radians(angle)),
        center[1] + radius * math.sin(math.radians(angle)),
        center[2],
    )


def _first_last(points):
    if len(points) <= 1:
        return points
    return (points[0], points[-1])


def _point(value) -> tuple[float, float, float]:
    values = tuple(value)
    if len(values) == 2:
        return (float(values[0]), float(values[1]), 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))
