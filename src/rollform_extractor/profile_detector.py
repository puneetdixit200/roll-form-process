from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
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
    records = tuple(_drawing_entities(entities))
    by_handle = {handle: entity for entity in records for handle in (entity.source_handles or (entity.handle,))}
    profiles: list[ProfileRecord] = []
    warnings: list[WarningRecord] = []
    previous_length: float | None = None
    for station in stations:
        key = str(station.sequence_index or station.station_id.removeprefix("S"))
        manual = tuple(getattr(overrides, "profile_handles", {}).get(key, ())) if overrides is not None else ()
        if manual:
            manual_entities = tuple(by_handle[handle] for handle in manual if handle in by_handle)
            profiles.append(_profile(station, manual_entities, manual, "manual_override", config_hash, 1.0))
            previous_length = profiles[-1].features["exact_length"]
            continue

        candidates = _candidates(station, records, previous_length, config)
        if not candidates:
            warnings.append(_warning("profile_missing", "no profile candidate was detected", station.source_handles, config_hash, 0.0))
            continue
        best = candidates[0]
        margin = best.score - (candidates[1].score if len(candidates) > 1 else 0.0)
        review = best.score < config.profiles.minimum_confidence or margin < config.profiles.minimum_score_margin
        if len(best.entities) == 1 and len(_station_entities(station, records)) > 1:
            review = True
            warnings.append(_warning("broken_profile_contour", "profile contour is disconnected", best.handles, config_hash, best.score))
        if len(candidates) > 1 and margin < config.profiles.minimum_score_margin:
            handles = tuple(dict.fromkeys(best.handles + candidates[1].handles))
            warnings.append(_warning("profile_ambiguity", "multiple plausible profile candidates were detected", handles, config_hash, best.score))
        profiles.append(_profile(station, best.entities, best.handles, "profile_detector", config_hash, best.score))
        previous_length = best.length
    return ProfileDetectionResult(
        profiles=tuple(profiles),
        warnings=tuple(warnings),
        method="profile_detector",
        configuration_hash=config_hash,
        manual_review_required=bool(warnings) or any(profile.confidence < config.profiles.minimum_confidence for profile in profiles),
    )


def _drawing_entities(entities: Iterable[CadEntityRecord]):
    for entity in entities:
        if getattr(entity, "classification", "drawing_geometry") == "drawing_support":
            continue
        if entity.layout.lower() != "model" or entity.entity_type not in PROFILE_TYPES:
            continue
        yield entity


def _candidates(station: StationRecord, entities: tuple[CadEntityRecord, ...], previous_length: float | None, config) -> tuple[_Candidate, ...]:
    station_entities = _station_entities(station, entities)
    chains = _chains(station_entities, config.geometry.endpoint_join_tolerance_mm)
    lengths = [sum(_entity_length(entity) for entity in chain) for chain in chains]
    longest = max(lengths, default=1.0)
    candidates = []
    for chain, length in zip(chains, lengths):
        layer_score = sum(_profile_layer_score(entity) for entity in chain) / max(1, len(chain))
        length_score = length / longest if longest else 0.0
        continuity_score = 0.2 if len(chain) > 1 else 0.0
        consistency = _length_consistency(length, previous_length)
        score = min(1.0, 0.45 * length_score + 0.3 * layer_score + continuity_score + consistency)
        candidates.append(_Candidate(chain, length, score))
    return tuple(sorted(candidates, key=lambda candidate: (-candidate.score, -candidate.length, candidate.handles)))


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
            "evidence": {"entity_count": len(entities)},
        },
    )


def _entity_length(entity: CadEntityRecord) -> float:
    return sum(primitive_length(primitive) for primitive in entity.normalized_primitives)


def _profile_layer_score(entity: CadEntityRecord) -> float:
    text = f"{entity.layer} {entity.line_type or ''}".lower()
    if "profile" in text or "part" in text:
        return 1.0
    if "roller" in text or "tool" in text:
        return 0.1
    return 0.5


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
