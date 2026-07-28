from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

import networkx as nx

from rollform_extractor.models import BBox, CadEntityRecord, StationRecord, WarningRecord
from rollform_extractor.review import apply_station_overrides


_LABEL_RE = re.compile(r"\b(?:STATION|STN|STA|ST)\s*[-#: ]?\s*0*(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DetectedStation:
    record: StationRecord
    drawing_label: str
    manual_review_required: bool

    def __getattr__(self, name: str) -> Any:
        return getattr(self.record, name)


@dataclass(frozen=True)
class StationDetectionResult:
    stations: tuple[DetectedStation, ...]
    warnings: tuple[WarningRecord, ...]
    method: str
    configuration_hash: str
    manual_review_required: bool


@dataclass(frozen=True)
class _Candidate:
    bbox: BBox
    source_handles: tuple[str, ...]
    method: str


@dataclass(frozen=True)
class _Label:
    number: int
    text: str
    bbox: BBox
    handle: str


def detect_stations(
    entities: Iterable[CadEntityRecord],
    inspection,
    config,
    overrides=None,
) -> StationDetectionResult:
    config_hash = config.hash_for("station_detection")
    if overrides is not None and getattr(overrides, "station_boxes", ()):
        stations = tuple(
            DetectedStation(station, station.station_id, False)
            for station in apply_station_overrides(entities, overrides)
        )
        return StationDetectionResult(stations, (), "station_detector", config_hash, False)

    records = tuple(_drawing_entities(entities))
    labels = _labels(records)
    geometry_candidates = _geometry_candidates(records, config.stations.cluster_gap_factor)
    block_candidates = _block_candidates(records)
    candidates = _choose_candidates(labels, block_candidates, geometry_candidates)
    labelled, warnings = _attach_labels(candidates, labels, config.stations.label_search_radius_mm, config_hash)
    ordered = _order(labelled)
    sequences = _sequences(ordered)
    stations = tuple(
        _station(sequence, fallback, candidate, label, conflict, config, config_hash)
        for fallback, (sequence, (candidate, label, conflict)) in enumerate(zip(sequences, ordered), start=1)
    )
    return StationDetectionResult(
        stations=stations,
        warnings=warnings,
        method="station_detector",
        configuration_hash=config_hash,
        manual_review_required=any(station.manual_review_required for station in stations) or bool(warnings),
    )


def _drawing_entities(entities: Iterable[CadEntityRecord]):
    for entity in entities:
        if getattr(entity, "classification", "drawing_geometry") == "drawing_support":
            continue
        if entity.layout.lower() != "model" or entity.bbox is None:
            continue
        yield entity


def _labels(entities: tuple[CadEntityRecord, ...]) -> tuple[_Label, ...]:
    labels: list[_Label] = []
    for entity in entities:
        if entity.entity_type not in {"TEXT", "MTEXT"} or entity.bbox is None:
            continue
        text = _text(entity)
        match = _LABEL_RE.search(text)
        if match:
            labels.append(_Label(int(match.group(1)), match.group(0).replace(" ", ""), entity.bbox, entity.handle))
    return tuple(labels)


def _block_candidates(entities: tuple[CadEntityRecord, ...]) -> tuple[_Candidate, ...]:
    groups: dict[str, list[CadEntityRecord]] = {}
    for entity in entities:
        if entity.entity_type == "INSERT" and entity.bbox is not None:
            name = str(entity.original_primitive.attributes.get("name", ""))
            groups.setdefault(name, []).append(entity)
    repeated = [group for group in groups.values() if len(group) > 1]
    if not repeated:
        return ()
    inserts = max(repeated, key=len)
    return tuple(_Candidate(entity.bbox, (entity.handle,), "block_repetition") for entity in inserts)


def _choose_candidates(
    labels: tuple[_Label, ...],
    block_candidates: tuple[_Candidate, ...],
    geometry_candidates: tuple[_Candidate, ...],
) -> tuple[_Candidate, ...]:
    if labels:
        return block_candidates if len(block_candidates) == len(labels) else geometry_candidates
    return block_candidates or geometry_candidates


def _geometry_candidates(entities: tuple[CadEntityRecord, ...], gap_factor: float) -> tuple[_Candidate, ...]:
    parts = tuple(
        entity
        for entity in entities
        if entity.entity_type not in {"TEXT", "MTEXT", "DIMENSION", "INSERT"} and entity.bbox is not None
    )
    if not parts:
        return ()
    graph = nx.Graph()
    graph.add_nodes_from(range(len(parts)))
    gap = _adaptive_gap(tuple(entity.bbox for entity in parts if entity.bbox is not None), gap_factor)
    for left in range(len(parts)):
        for right in range(left + 1, len(parts)):
            if _box_distance(parts[left].bbox, parts[right].bbox) < gap:
                graph.add_edge(left, right)
    candidates = []
    for component in nx.connected_components(graph):
        group = tuple(parts[index] for index in component)
        candidates.append(
            _Candidate(
                _union(entity.bbox for entity in group if entity.bbox is not None),
                tuple(entity.handle for entity in group),
                "geometry_cluster",
            )
        )
    return tuple(candidates)


def _adaptive_gap(boxes: tuple[BBox, ...], gap_factor: float) -> float:
    sizes = sorted(max(box.max_x - box.min_x, box.max_y - box.min_y) for box in boxes)
    if not sizes:
        return 0.0
    return sizes[len(sizes) // 4] * gap_factor


def _attach_labels(
    candidates: tuple[_Candidate, ...],
    labels: tuple[_Label, ...],
    radius: float,
    config_hash: str,
) -> tuple[tuple[tuple[_Candidate, _Label | None, bool], ...], tuple[WarningRecord, ...]]:
    assigned: list[tuple[_Candidate, _Label | None, bool]] = []
    used: set[str] = set()
    numbers: dict[int, str] = {}
    duplicate_handles: list[str] = []
    conflict = False
    for candidate in candidates:
        nearby = sorted(
            (label for label in labels if label.handle not in used),
            key=lambda label: _box_distance(candidate.bbox, label.bbox),
        )
        label = nearby[0] if nearby and _box_distance(candidate.bbox, nearby[0].bbox) <= radius else None
        label_conflict = False
        if label is not None:
            used.add(label.handle)
            previous = numbers.setdefault(label.number, label.handle)
            label_conflict = previous != label.handle
            if label_conflict:
                duplicate_handles.extend((previous, label.handle))
            conflict = conflict or label_conflict
        assigned.append((candidate, label, label_conflict))
    warnings = ()
    if conflict:
        warnings = (
            WarningRecord(
                code="conflicting_station_labels",
                message="duplicate station label numbers were detected",
                source_handles=tuple(dict.fromkeys(duplicate_handles)),
                method="station_detector",
                configuration_hash=config_hash,
                confidence=0.5,
            ),
        )
    return tuple(assigned), warnings


def _order(labelled: tuple[tuple[_Candidate, _Label | None, bool], ...]):
    if labelled and all(label is not None for _, label, _ in labelled):
        return tuple(sorted(labelled, key=lambda item: (item[1].number, _center(item[0].bbox)[0])))  # type: ignore[union-attr]
    centers = [_center(candidate.bbox) for candidate, _, _ in labelled]
    if not centers:
        return ()
    spread_x = max(x for x, _ in centers) - min(x for x, _ in centers)
    spread_y = max(y for _, y in centers) - min(y for _, y in centers)
    if spread_y > spread_x * 1.5:
        return tuple(sorted(labelled, key=lambda item: -_center(item[0].bbox)[1]))
    row_gap = _row_gap(tuple(candidate.bbox for candidate, _, _ in labelled))
    return tuple(sorted(labelled, key=lambda item: (-round(_center(item[0].bbox)[1] / row_gap), _center(item[0].bbox)[0])))


def _sequences(labelled: tuple[tuple[_Candidate, _Label | None, bool], ...]) -> tuple[int, ...]:
    used: set[int] = set()
    result: list[int] = []
    for _, label, conflict in labelled:
        if label is not None and not conflict and label.number not in used:
            sequence = label.number
        else:
            sequence = _next_free_sequence(used)
        used.add(sequence)
        result.append(sequence)
    return tuple(result)


def _next_free_sequence(used: set[int]) -> int:
    sequence = 1
    while sequence in used:
        sequence += 1
    return sequence


def _station(
    sequence: int,
    fallback: int,
    candidate: _Candidate,
    label: _Label | None,
    conflict: bool,
    config,
    config_hash: str,
) -> DetectedStation:
    unlabelled = label is None
    review = unlabelled or conflict
    confidence = 0.9 if label is not None and not conflict else 0.55
    if confidence < config.stations.minimum_confidence:
        review = True
    drawing_label = label.text if label is not None else f"Station_Unknown_{fallback}"
    record = StationRecord(
        station_id=f"S{sequence}",
        sequence_index=sequence,
        bbox=candidate.bbox,
        source_handles=candidate.source_handles,
        method="station_detector",
        configuration_hash=config_hash,
        confidence=confidence,
        evidence={
            "candidate_method": candidate.method,
            "drawing_label": drawing_label,
            "manual_review_required": review,
        },
    )
    return DetectedStation(record, drawing_label, review)


def _text(entity: CadEntityRecord) -> str:
    if "text" in entity.attributes:
        return str(entity.attributes["text"])
    if entity.original_primitives and "text" in entity.original_primitive.attributes:
        return str(entity.original_primitive.attributes["text"])
    return ""


def _center(box: BBox) -> tuple[float, float]:
    return ((box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2)


def _row_gap(boxes: tuple[BBox, ...]) -> float:
    heights = sorted(box.max_y - box.min_y for box in boxes)
    return max(1.0, heights[len(heights) // 2] * 2.0) if heights else 1.0


def _box_distance(left: BBox, right: BBox) -> float:
    dx = max(left.min_x - right.max_x, right.min_x - left.max_x, 0.0)
    dy = max(left.min_y - right.max_y, right.min_y - left.max_y, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _union(boxes: Iterable[BBox]) -> BBox:
    items = tuple(boxes)
    return BBox(
        min(box.min_x for box in items),
        min(box.min_y for box in items),
        max(box.max_x for box in items),
        max(box.max_y for box in items),
    )
