from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping

from rollform_extractor.models import BBox, CadEntityRecord, ProfileRecord, RollerOccurrenceRecord, StationRecord, WarningRecord


SPECIAL_ROLES = ("guide", "support", "shaft", "spacer", "distance_ring", "ring")
IDENTIFIER_RE = re.compile(r"\b[A-Z]{1,4}\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class AssemblyRecord:
    assembly_id: str
    station_id: str
    sequence_index: int | None
    roller_occurrence_ids: tuple[str, ...]
    tooling_status: str
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class RollerDetectionResult:
    rollers: tuple[RollerOccurrenceRecord, ...]
    assemblies: tuple[AssemblyRecord, ...]
    warnings: tuple[WarningRecord, ...]
    method: str
    configuration_hash: str
    manual_review_required: bool


@dataclass(frozen=True)
class _Circle:
    entity: CadEntityRecord
    center: tuple[float, float]
    radius: float


@dataclass(frozen=True)
class _Candidate:
    station: StationRecord
    role: str | None
    handles: tuple[str, ...]
    center: tuple[float, float]
    outer_diameter: float
    bore_diameter: float | None
    keyway: bool
    annotations: tuple[str, ...]
    identifier: str | None
    confidence: float
    method: str


def detect_rollers(
    stations: Iterable[StationRecord],
    profiles: Iterable[ProfileRecord],
    entities: Iterable[CadEntityRecord],
    config,
    overrides=None,
) -> RollerDetectionResult:
    config_hash = config.hash_for("roller_detection")
    station_records = tuple(stations)
    entity_records = tuple(_drawing_entities(entities))
    profile_by_station = {profile.station_id: profile for profile in profiles}
    warnings: list[WarningRecord] = []
    rollers: list[RollerOccurrenceRecord] = []

    for station in station_records:
        used_handles: set[str] = set()
        manual = _manual_candidates(station, entity_records, config_hash, overrides)
        for candidate in manual:
            used_handles.update(candidate.handles)
            rollers.append(_roller(station, candidate, len(rollers) + 1, config_hash))

        profile = profile_by_station.get(station.station_id)
        auto = _auto_candidates(station, profile, entity_records, used_handles, config)
        for candidate in auto:
            rollers.append(_roller(station, candidate, len(rollers) + 1, config_hash))
            if candidate.role and "centre" in candidate.role and candidate.role not in SPECIAL_ROLES:
                warnings.append(_warning("weak_roller_role", "roller is near the profile centreline", candidate.handles, config_hash, candidate.confidence))

        if profile is not None and not manual and not auto:
            warnings.append(_warning("rollers_missing", "no roller tooling was detected for station", station.source_handles, config_hash, 0.0))

    identifiers = [str(roller.evidence["identifier"]) for roller in rollers if roller.evidence.get("identifier")]
    duplicate_ids = {identifier for identifier, count in Counter(identifiers).items() if count > 1}
    if duplicate_ids:
        handles = tuple(handle for roller in rollers if roller.evidence.get("identifier") in duplicate_ids for handle in roller.source_handles)
        warnings.append(_warning("duplicate_roller_identifier", "duplicate roller identifiers were detected", handles, config_hash, 0.5))

    assemblies = tuple(_assembly(station, tuple(roller for roller in rollers if roller.station_id == station.station_id), config_hash) for station in station_records)
    review_warnings = tuple(warning for warning in warnings if warning.code != "rollers_missing")
    return RollerDetectionResult(
        rollers=tuple(rollers),
        assemblies=assemblies,
        warnings=tuple(warnings),
        method="roller_detector",
        configuration_hash=config_hash,
        manual_review_required=bool(review_warnings) or any(roller.confidence < config.rollers.minimum_confidence for roller in rollers),
    )


def _manual_candidates(station: StationRecord, entities: tuple[CadEntityRecord, ...], config_hash: str, overrides) -> tuple[_Candidate, ...]:
    if overrides is None:
        return ()
    key = str(station.sequence_index or station.station_id.removeprefix("S"))
    role_map = getattr(overrides, "roller_handles", {}).get(key, {})
    by_handle = {handle: entity for entity in entities for handle in (entity.source_handles or (entity.handle,))}
    candidates = []
    for role, handles in role_map.items():
        selected = tuple(by_handle[handle] for handle in handles if handle in by_handle)
        circles = _circles(selected)
        center = _average(circle.center for circle in circles) if circles else _center(station.bbox)
        radii = tuple(circle.radius for circle in circles)
        annotations = _annotations(selected)
        candidates.append(
            _Candidate(
                station,
                _normal_role(role),
                tuple(handles),
                center,
                2 * max(radii) if radii else 0.0,
                2 * min(radii) if len(set(radii)) > 1 else None,
                _has_keyway(center, max(radii, default=0.0), selected),
                annotations,
                _identifier(annotations),
                1.0,
                "manual_override",
            )
        )
    return tuple(candidates)


def _auto_candidates(
    station: StationRecord,
    profile: ProfileRecord | None,
    entities: tuple[CadEntityRecord, ...],
    used_handles: set[str],
    config,
) -> tuple[_Candidate, ...]:
    station_entities = tuple(entity for entity in entities if entity.bbox and _contains(station.bbox, entity.bbox))
    profile_handles = set(profile.source_handles if profile else ())
    circles = tuple(
        circle
        for circle in _circles(station_entities)
        if circle.entity.handle not in used_handles and not profile_handles.intersection(circle.entity.source_handles or (circle.entity.handle,))
    )
    groups = _circle_groups(circles, config.geometry.duplicate_tolerance_mm)
    lines = tuple(entity for entity in station_entities if entity.entity_type == "LINE" and entity.handle not in used_handles)
    texts = tuple(entity for entity in station_entities if entity.entity_type in {"TEXT", "MTEXT"})
    candidates = []
    for group in groups:
        radii = sorted({round(circle.radius, 6) for circle in group})
        outer = max(circle.radius for circle in group)
        center = _average(circle.center for circle in group)
        handles = tuple(dict.fromkeys(circle.entity.handle for circle in group))
        nearby_text = tuple(_text(entity) for entity in texts if entity.handle not in used_handles and _distance(_center(entity.bbox), center) <= max(outer * 2.5, 15.0))
        role = _special_role(group) or _relative_role(center, profile, station)
        candidates.append(
            _Candidate(
                station,
                role,
                handles,
                center,
                round(2 * outer, 6),
                round(2 * radii[0], 6) if len(radii) > 1 else None,
                _has_keyway(center, outer, lines),
                nearby_text,
                _identifier(nearby_text),
                0.85 if len(radii) > 1 else 0.7,
                "roller_detector",
            )
        )
    return tuple(candidates)


def _roller(station: StationRecord, candidate: _Candidate, index: int, config_hash: str) -> RollerOccurrenceRecord:
    evidence = {
        "center": candidate.center,
        "outer_diameter_mm": candidate.outer_diameter,
        "bore_diameter_mm": candidate.bore_diameter,
        "keyway": candidate.keyway,
        "annotations": candidate.annotations,
    }
    if candidate.identifier:
        evidence["identifier"] = candidate.identifier
    return RollerOccurrenceRecord(
        occurrence_id=f"{station.station_id}-R{index}",
        station_id=station.station_id,
        role=candidate.role,
        source_handles=candidate.handles,
        method=candidate.method,
        configuration_hash=config_hash,
        confidence=candidate.confidence,
        evidence=evidence,
    )


def _assembly(station: StationRecord, rollers: tuple[RollerOccurrenceRecord, ...], config_hash: str) -> AssemblyRecord:
    status = "available" if rollers else "unavailable"
    return AssemblyRecord(
        assembly_id=f"{station.station_id}-A1",
        station_id=station.station_id,
        sequence_index=station.sequence_index,
        roller_occurrence_ids=tuple(roller.occurrence_id for roller in rollers),
        tooling_status=status,
        source_handles=tuple(dict.fromkeys(handle for roller in rollers for handle in roller.source_handles)),
        method="roller_detector",
        configuration_hash=config_hash,
        confidence=min((roller.confidence for roller in rollers), default=0.0),
        evidence={"roller_count": len(rollers)},
    )


def _drawing_entities(entities: Iterable[CadEntityRecord]):
    for entity in entities:
        if entity.layout.lower() == "model" and entity.bbox is not None:
            yield entity


def _circles(entities: Iterable[CadEntityRecord]) -> tuple[_Circle, ...]:
    result = []
    for entity in entities:
        for primitive in entity.normalized_primitives:
            if primitive.kind == "CIRCLE":
                result.append(_Circle(entity, _point2(primitive.attributes["center"]), float(primitive.attributes["radius"])))
    return tuple(result)


def _circle_groups(circles: tuple[_Circle, ...], tolerance: float) -> tuple[tuple[_Circle, ...], ...]:
    groups: list[list[_Circle]] = []
    for circle in circles:
        for group in groups:
            if _distance(circle.center, _average(item.center for item in group)) <= tolerance:
                group.append(circle)
                break
        else:
            groups.append([circle])
    return tuple(tuple(group) for group in groups)


def _relative_role(center: tuple[float, float], profile: ProfileRecord | None, station: StationRecord) -> str:
    box = profile.features.get("bbox") if profile else station.bbox
    if not isinstance(box, BBox):
        box = station.bbox
    cx, cy = _center(box)
    vertical = "upper" if center[1] >= cy else "lower"
    deadband = max((box.max_x - box.min_x) * 0.1, 1.0)
    if abs(center[0] - cx) <= deadband:
        horizontal = "centre"
    else:
        horizontal = "left" if center[0] < cx else "right"
    return f"{vertical}_{horizontal}"


def _special_role(group: tuple[_Circle, ...]) -> str | None:
    text = " ".join(f"{circle.entity.layer} {circle.entity.handle}" for circle in group).lower().replace("-", "_")
    for role in SPECIAL_ROLES:
        if role in text:
            return "distance_ring" if role == "ring" else role
    return None


def _normal_role(role: str) -> str:
    value = str(role).lower().replace("-", "_")
    return "centre" if value == "center" else value


def _has_keyway(center: tuple[float, float], radius: float, entities: Iterable[CadEntityRecord]) -> bool:
    if radius <= 0:
        return False
    for entity in entities:
        if entity.entity_type != "LINE":
            continue
        for primitive in entity.normalized_primitives:
            start = _point2(primitive.attributes["start"])
            end = _point2(primitive.attributes["end"])
            if _distance(start, center) <= radius and _distance(end, center) <= radius:
                return True
    return False


def _annotations(entities: Iterable[CadEntityRecord]) -> tuple[str, ...]:
    return tuple(_text(entity) for entity in entities if entity.entity_type in {"TEXT", "MTEXT"} and _text(entity))


def _identifier(annotations: tuple[str, ...]) -> str | None:
    for annotation in annotations:
        match = IDENTIFIER_RE.search(annotation)
        if match:
            return match.group(0).upper()
    return None


def _text(entity: CadEntityRecord) -> str:
    attrs = entity.original_primitive.attributes if entity.original_primitives else entity.normalized_primitives[0].attributes
    return str(attrs.get("text", attrs.get("plain_text", ""))).strip()


def _warning(code: str, message: str, handles: tuple[str, ...], config_hash: str, confidence: float) -> WarningRecord:
    return WarningRecord(code, message, handles, "roller_detector", config_hash, confidence)


def _contains(outer: BBox, inner: BBox) -> bool:
    return outer.min_x <= inner.min_x and outer.max_x >= inner.max_x and outer.min_y <= inner.min_y and outer.max_y >= inner.max_y


def _center(box: BBox) -> tuple[float, float]:
    return ((box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2)


def _average(points: Iterable[tuple[float, float]]) -> tuple[float, float]:
    items = tuple(points)
    return (sum(point[0] for point in items) / len(items), sum(point[1] for point in items) / len(items))


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _point2(value) -> tuple[float, float]:
    return (float(value[0]), float(value[1]))
