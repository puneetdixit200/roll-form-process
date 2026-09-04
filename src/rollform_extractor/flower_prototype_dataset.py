"""Private, deterministic historical flower data for the sequence prototype.

This module intentionally keeps the prototype dataset separate from the
production Phase 15--18 domain records. It reads staged DXF representations of
private DWGs, stores redacted identifiers in public-facing summaries, and
retains source provenance in the local private workspace only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import ezdxf

from rollform_extractor.converter import stage_input


FLOWER_PROTOTYPE_SCHEMA_VERSION = 2
FLOWER_PROTOTYPE_ALGORITHM_VERSION = "history_constrained_flower_v2"
SAMPLE_COUNT = 128


@dataclass(frozen=True)
class HistoricalPass:
    pass_id: str
    source_flower_id: str
    source_handle: str
    inferred_order: int
    points: tuple[tuple[float, float, float], ...]
    normalized_points: tuple[tuple[float, float], ...]
    shape_vector: tuple[float, ...]
    width: float
    height: float
    outline_perimeter: float
    developed_length: float
    bend_angles: tuple[float, ...]
    bend_positions: tuple[float, ...]
    bend_directions: tuple[str, ...]
    topology: str
    quality_flags: tuple[str, ...]
    source_sha256: str

    @property
    def bend_count(self) -> int:
        return len(self.bend_angles)

    @property
    def formedness(self) -> float:
        return max(0.0, min(1.0, (self.height / self.width) if self.width > 0 else 0.0))

    def to_dict(self, *, include_points: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_points:
            value.pop("points", None)
            value.pop("normalized_points", None)
            value.pop("shape_vector", None)
        value["schema_version"] = FLOWER_PROTOTYPE_SCHEMA_VERSION
        value["algorithm_version"] = FLOWER_PROTOTYPE_ALGORITHM_VERSION
        return value


@dataclass(frozen=True)
class HistoricalFlower:
    flower_id: str
    source_classification: str
    source_sha256: str
    source_entity_count: int
    raw_profile_count: int
    passes: tuple[HistoricalPass, ...]
    topology: str
    quality_flags: tuple[str, ...]
    source_station_count: int | None = None
    extractor_mode_requested: str = "LEGACY_POLYLINE"
    extractor_mode_used: str = "LEGACY_POLYLINE"
    source_region_id: str | None = None

    def to_dict(self, *, include_geometry: bool = False) -> dict[str, Any]:
        return {
            "schema_version": FLOWER_PROTOTYPE_SCHEMA_VERSION,
            "algorithm_version": FLOWER_PROTOTYPE_ALGORITHM_VERSION,
            "flower_id": self.flower_id,
            "source_classification": self.source_classification,
            "source_sha256": self.source_sha256,
            "source_entity_count": self.source_entity_count,
            "raw_profile_count": self.raw_profile_count,
            "source_station_count": self.source_station_count,
            "extractor_mode_requested": self.extractor_mode_requested,
            "extractor_mode_used": self.extractor_mode_used,
            "source_region_id": self.source_region_id,
            "topology": self.topology,
            "quality_flags": list(self.quality_flags),
            "passes": [item.to_dict(include_points=include_geometry) for item in self.passes],
        }


@dataclass(frozen=True)
class RollerSequenceEvidence:
    evidence_id: str
    source_file_id: str
    source_sha256: str
    raw_profile_count: int
    entity_count: int
    association_status: str
    quality_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = FLOWER_PROTOTYPE_SCHEMA_VERSION
        value["algorithm_version"] = FLOWER_PROTOTYPE_ALGORITHM_VERSION
        value["source_classification"] = "PRIVATE_PROTOTYPE"
        return value


@dataclass(frozen=True)
class FlowerPrototypeDataset:
    dataset_id: str
    dataset_hash: str
    source_classification: str
    flowers: tuple[HistoricalFlower, ...]
    roller_evidence: tuple[RollerSequenceEvidence, ...]
    configuration_hash: str
    quality_flags: tuple[str, ...]
    roller_station_evidence: tuple[dict[str, Any], ...] = ()

    def to_dict(self, *, include_geometry: bool = False) -> dict[str, Any]:
        return {
            "schema_version": FLOWER_PROTOTYPE_SCHEMA_VERSION,
            "algorithm_version": FLOWER_PROTOTYPE_ALGORITHM_VERSION,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "source_classification": self.source_classification,
            "configuration_hash": self.configuration_hash,
            "quality_flags": list(self.quality_flags),
            "flowers": [item.to_dict(include_geometry=include_geometry) for item in self.flowers],
            "roller_evidence": [item.to_dict() for item in self.roller_evidence],
            "roller_station_evidence": [dict(item) for item in self.roller_station_evidence],
        }


def ingest_private_flower(
    source: Path,
    private_root: Path,
    flower_id: str,
    *,
    source_station_count: int | None = None,
    extractor_mode: str = "AUTO",
) -> HistoricalFlower:
    """Convert a private DWG to a private staged DXF and derive pass records."""
    source = source.resolve()
    before = _sha256(source)
    staged = stage_input(source, private_root / "staged" / flower_id)
    document = ezdxf.readfile(staged.converted_file)
    entities = tuple(document.modelspace())
    requested = extractor_mode.upper()
    polylines = tuple(entity for entity in entities if entity.dxftype() == "POLYLINE")
    lwpolylines = tuple(entity for entity in entities if entity.dxftype() == "LWPOLYLINE")
    composite_requires_review = False
    station_sequence_requires_review = False
    source_region_id: str | None = None
    if requested == "COMPOSITE_FLOWER":
        selected, composite_requires_review = _detected_composite_pass_entities(document, staged.converted_file)
        used = "COMPOSITE_FLOWER"
        passes = tuple(
            _pass_from_polyline(entity, flower_id, index, before)
            if entity.dxftype() == "POLYLINE"
            else _pass_from_points(_lwpolyline_points(entity), str(entity.dxf.handle), flower_id, index, before)
            for index, entity in enumerate(selected)
        )
    elif requested.startswith("STATION_SEQUENCE:"):
        selector = requested.split(":", 1)[1].strip()
        selected, source_region_id = _detected_station_sequence_pass_entities(
            document,
            staged.converted_file,
            selector,
        )
        used = f"STATION_SEQUENCE:{selector}"
        station_sequence_requires_review = True
        passes = tuple(
            _pass_from_polyline(entity, flower_id, index, before)
            if entity.dxftype() == "POLYLINE"
            else _pass_from_points(_lwpolyline_points(entity), str(entity.dxf.handle), flower_id, index, before)
            for index, entity in enumerate(selected)
        )
    elif requested in {"LEGACY_POLYLINE", "AUTO"} and polylines:
        used = "LEGACY_POLYLINE"
        passes = tuple(_pass_from_polyline(entity, flower_id, index, before) for index, entity in enumerate(polylines))
    elif requested in {"LWPOLYLINE", "AUTO"} and lwpolylines:
        used = "LWPOLYLINE"
        passes = tuple(_pass_from_points(_lwpolyline_points(entity), str(entity.dxf.handle), flower_id, index, before) for index, entity in enumerate(lwpolylines))
    else:
        used = "REVIEW_REQUIRED"
        passes = ()
    _assert_unchanged(source, before)
    quality: list[str] = []
    if not passes:
        quality.append("NO_SUPPORTED_SEQUENCE_PASSES")
    if source_station_count is not None and source_station_count != len(passes):
        quality.append("GENERIC_PIPELINE_STATION_COUNT_DIFFERS")
    if composite_requires_review:
        quality.append("COMPOSITE_PASS_ORDER_INFERRED_REVIEW_REQUIRED")
    if station_sequence_requires_review:
        quality.append("STATION_SEQUENCE_ORDER_INFERRED_REVIEW_REQUIRED")
    return HistoricalFlower(
        flower_id=flower_id,
        source_classification="PRIVATE_PROTOTYPE",
        source_sha256=before,
        source_entity_count=len(entities),
        raw_profile_count=len(passes),
        passes=passes,
        topology=_flower_topology(passes),
        quality_flags=tuple(quality),
        source_station_count=source_station_count,
        extractor_mode_requested=requested,
        extractor_mode_used=used,
        source_region_id=source_region_id,
    )


def _detect_flower_domain(document: Any, converted_file: Path) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
    """Run the authoritative extraction detectors and return stations, profiles, composites."""
    from rollform_extractor.composite_flower import build_composite_flowers
    from rollform_extractor.config import ExtractionConfig
    from rollform_extractor.dxf_reader import inspect_drawing
    from rollform_extractor.entity_parser import parse_entities
    from rollform_extractor.profile_detector import detect_profiles
    from rollform_extractor.roller_detector import detect_rollers
    from rollform_extractor.stage_classifier import assign_stage_types
    from rollform_extractor.station_detector import detect_stations
    from rollform_extractor.support_classifier import classify_support

    config = ExtractionConfig.load(None)
    inspection = inspect_drawing(converted_file)
    parsed = parse_entities(document, config)
    classified = classify_support(parsed.entities + parsed.expanded_entities, inspection, config)
    detected_stations = detect_stations(classified.entities, inspection, config, None)
    profiles = detect_profiles(tuple(item.record for item in detected_stations.stations), classified.entities, config, None)
    typed_for_rollers = assign_stage_types((item.record for item in detected_stations.stations), profiles.profiles)
    rollers = detect_rollers(typed_for_rollers, profiles.profiles, classified.entities, config, None)
    typed_stations = tuple(assign_stage_types(typed_for_rollers, profiles.profiles, rollers.rollers))
    composites = tuple(build_composite_flowers(typed_stations, profiles.profiles, classified.entities))
    return typed_stations, tuple(profiles.profiles), composites


def _detected_station_sequence_pass_entities(
    document: Any,
    converted_file: Path,
    selector: str,
) -> tuple[tuple[Any, ...], str]:
    """Select ordered profile outlines from one detected station sequence."""
    if not selector.isdigit() or int(selector) < 1:
        raise ValueError(f"INVALID_STATION_SEQUENCE_SELECTOR: {selector}")
    sequence_number = int(selector)
    stations, profiles, _composites = _detect_flower_domain(document, converted_file)
    station_by_id = {item.station_id: item for item in stations}
    candidates = []
    for profile in profiles:
        station = station_by_id.get(profile.station_id)
        if station is None or int(station.evidence.get("sequence_id", 0) or 0) != sequence_number:
            continue
        region_type = str(station.evidence.get("region_type") or station.evidence.get("stage_type") or "")
        if region_type not in {"FLOWER_PROFILE", "FINAL_PROFILE", "FLAT_STRIP"}:
            continue
        candidates.append((station.sequence_index if station.sequence_index is not None else 10**9, profile.profile_id, profile))
    if not candidates:
        raise ValueError(f"STATION_SEQUENCE_NOT_FOUND: {selector}")

    by_handle = {
        str(entity.dxf.handle): entity
        for entity in document.modelspace()
        if getattr(entity.dxf, "handle", None)
    }
    selected = []
    for _order, profile_id, profile in sorted(candidates, key=lambda item: (item[0], item[1])):
        matches = [
            by_handle[handle]
            for handle in profile.source_handles
            if handle in by_handle and by_handle[handle].dxftype() in {"POLYLINE", "LWPOLYLINE"}
        ]
        if len(matches) != 1:
            raise ValueError(f"STATION_SEQUENCE_PROFILE_SOURCE_REQUIRES_REVIEW: {profile_id}")
        selected.append(matches[0])
    return tuple(selected), f"sequence_{sequence_number:02d}"


def _detected_composite_pass_entities(document: Any, converted_file: Path) -> tuple[tuple[Any, ...], bool]:
    """Return one canonical composite sequence using the main extraction detectors."""
    _stations, _profiles, detected = _detect_flower_domain(document, converted_file)
    composites = tuple(item for item in detected if item.pass_count >= 3)
    if len(composites) != 1:
        raise ValueError(f"COMPOSITE_FLOWER_SELECTION_REQUIRES_REVIEW: detected {len(composites)} eligible regions")

    by_handle = {str(entity.dxf.handle): entity for entity in document.modelspace() if getattr(entity.dxf, "handle", None)}
    selected = []
    composite = composites[0]
    for item in sorted(composite.passes, key=lambda value: (value.inferred_order, value.pass_id)):
        matches = [by_handle[handle] for handle in item.source_handles if handle in by_handle and by_handle[handle].dxftype() in {"POLYLINE", "LWPOLYLINE"}]
        if len(matches) != 1:
            raise ValueError(f"COMPOSITE_PASS_SOURCE_REQUIRES_REVIEW: {item.pass_id}")
        selected.append(matches[0])
    return tuple(selected), not composite.confirmed


def ingest_private_roller_evidence(source: Path, private_root: Path, evidence_id: str) -> RollerSequenceEvidence:
    source = source.resolve()
    before = _sha256(source)
    staged = stage_input(source, private_root / "staged" / evidence_id)
    document = ezdxf.readfile(staged.converted_file)
    entities = tuple(document.modelspace())
    polylines = tuple(entity for entity in entities if entity.dxftype() == "POLYLINE")
    _assert_unchanged(source, before)
    return RollerSequenceEvidence(
        evidence_id=evidence_id,
        source_file_id=evidence_id,
        source_sha256=before,
        raw_profile_count=len(polylines),
        entity_count=len(entities),
        association_status="POSSIBLE_STATION_ASSOCIATION" if polylines else "INSUFFICIENT_GEOMETRY",
        quality_flags=("PHYSICAL_ASSET_NOT_IDENTIFIED", "OPTIONAL_SUPPORTING_EVIDENCE"),
    )


def build_dataset(
    flowers: Iterable[HistoricalFlower],
    roller_evidence: Iterable[RollerSequenceEvidence],
    *,
    configuration_hash: str = "flower-prototype-default-v1",
    roller_station_evidence: Iterable[Mapping[str, Any]] = (),
) -> FlowerPrototypeDataset:
    flowers = tuple(sorted(flowers, key=lambda item: item.flower_id))
    source_keys = [
        (item.source_sha256, item.source_region_id or "__WHOLE_SOURCE__")
        for item in flowers
        if item.source_sha256 not in {"", "source"}
    ]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("DUPLICATE_HISTORICAL_SOURCE_REGION")
    grouped_regions: dict[str, list[str | None]] = {}
    for item in flowers:
        if item.source_sha256 not in {"", "source"}:
            grouped_regions.setdefault(item.source_sha256, []).append(item.source_region_id)
    if any(len(regions) > 1 and any(region is None for region in regions) for regions in grouped_regions.values()):
        raise ValueError("DUPLICATE_HISTORICAL_SOURCE_REQUIRES_REGION_IDENTITY")
    rollers = tuple(sorted(roller_evidence, key=lambda item: item.evidence_id))
    station_evidence = tuple(sorted((dict(item) for item in roller_station_evidence), key=lambda item: (str(item.get("flower_id", "")), str(item.get("pass_id", "")), str(item.get("role", "")), str(item.get("design_id", "")), str(item.get("geometry_revision_id", "")))))
    payload = {
        "schema_version": FLOWER_PROTOTYPE_SCHEMA_VERSION,
        "algorithm_version": FLOWER_PROTOTYPE_ALGORITHM_VERSION,
        "configuration_hash": configuration_hash,
        "flowers": [flower.to_dict(include_geometry=True) for flower in flowers],
        "roller_evidence": [item.to_dict() for item in rollers],
        "roller_station_evidence": list(station_evidence),
    }
    dataset_hash = _digest(payload)
    flags = tuple(flag for flower in flowers for flag in flower.quality_flags)
    return FlowerPrototypeDataset(
        dataset_id=f"fpd-{dataset_hash[:16]}",
        dataset_hash=dataset_hash,
        source_classification="PRIVATE_PROTOTYPE",
        flowers=flowers,
        roller_evidence=rollers,
        configuration_hash=configuration_hash,
        quality_flags=tuple(sorted(set(flags))),
        roller_station_evidence=station_evidence,
    )


def _dataset_from_dict(value: dict[str, Any]) -> FlowerPrototypeDataset:
    """Load a redacted dataset export without accessing the private source files."""
    flowers = []
    for flower_value in value.get("flowers", []):
        passes = []
        for item in flower_value.get("passes", []):
            points = tuple(tuple(float(v) for v in point) for point in item.get("points", []))
            normalized = tuple(tuple(float(v) for v in point) for point in item.get("normalized_points", []))
            passes.append(HistoricalPass(
                pass_id=item["pass_id"], source_flower_id=item["source_flower_id"], source_handle=item["source_handle"],
                inferred_order=int(item["inferred_order"]), points=points, normalized_points=normalized,
                shape_vector=tuple(float(v) for v in item.get("shape_vector", [])), width=float(item["width"]), height=float(item["height"]),
                outline_perimeter=float(item["outline_perimeter"]), developed_length=float(item["developed_length"]),
                bend_angles=tuple(float(v) for v in item.get("bend_angles", [])), bend_positions=tuple(float(v) for v in item.get("bend_positions", [])),
                bend_directions=tuple(str(v) for v in item.get("bend_directions", [])), topology=item["topology"],
                quality_flags=tuple(str(v) for v in item.get("quality_flags", [])), source_sha256=item["source_sha256"],
            ))
        flowers.append(HistoricalFlower(
            flower_id=flower_value["flower_id"], source_classification=flower_value["source_classification"], source_sha256=flower_value["source_sha256"],
            source_entity_count=int(flower_value["source_entity_count"]), raw_profile_count=int(flower_value["raw_profile_count"]), passes=tuple(passes),
            topology=flower_value["topology"], quality_flags=tuple(flower_value.get("quality_flags", [])), source_station_count=flower_value.get("source_station_count"),
            extractor_mode_requested=str(flower_value.get("extractor_mode_requested", "LEGACY_POLYLINE")), extractor_mode_used=str(flower_value.get("extractor_mode_used", "LEGACY_POLYLINE")),
            source_region_id=flower_value.get("source_region_id"),
        ))
    rollers = tuple(RollerSequenceEvidence(
        evidence_id=item["evidence_id"], source_file_id=item["source_file_id"], source_sha256=item["source_sha256"],
        raw_profile_count=int(item["raw_profile_count"]), entity_count=int(item["entity_count"]), association_status=item["association_status"],
        quality_flags=tuple(item.get("quality_flags", [])),
    ) for item in value.get("roller_evidence", []))
    return FlowerPrototypeDataset(value["dataset_id"], value["dataset_hash"], value["source_classification"], tuple(flowers), rollers, value["configuration_hash"], tuple(value.get("quality_flags", [])), tuple(value.get("roller_station_evidence", [])))


def write_redacted_dataset(dataset: FlowerPrototypeDataset, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataset.to_dict(include_geometry=False), indent=2, sort_keys=True), encoding="utf-8")
    return path


def persist_dataset(engine: Any, dataset: FlowerPrototypeDataset) -> str:
    """Persist the small prototype dataset using additive project tables."""
    from rollform_extractor.flower_dataset_validation import validate_flower_prototype_dataset
    validation = validate_flower_prototype_dataset(dataset.to_dict(include_geometry=True))
    if not validation["valid"]:
        raise ValueError("invalid flower prototype dataset: " + "; ".join(item["code"] for item in validation["issues"]))
    from sqlalchemy.orm import Session
    from rollform_extractor.database import (
        FlowerPrototypeDatasetRow,
        FlowerPrototypeSourceRow,
        HistoricalFlowerPassRow,
        HistoricalFlowerRow,
        HistoricalPassTransitionRow,
        HistoricalRollerStationEvidenceRow,
    )

    with Session(engine) as session, session.begin():
        existing = session.query(FlowerPrototypeDatasetRow).filter_by(dataset_id=dataset.dataset_id).one_or_none()
        if existing is not None:
            return dataset.dataset_id
        session.add(FlowerPrototypeDatasetRow(
            dataset_id=dataset.dataset_id,
            dataset_hash=dataset.dataset_hash,
            schema_version=FLOWER_PROTOTYPE_SCHEMA_VERSION,
            algorithm_version=FLOWER_PROTOTYPE_ALGORITHM_VERSION,
            source_classification=dataset.source_classification,
            configuration_hash=dataset.configuration_hash,
            quality_flags_json=list(dataset.quality_flags),
        ))
        for evidence in dataset.roller_evidence:
            session.add(FlowerPrototypeSourceRow(
                dataset_id=dataset.dataset_id,
                source_id=evidence.source_file_id,
                source_sha256=evidence.source_sha256,
                source_classification="PRIVATE_PROTOTYPE",
                raw_profile_count=evidence.raw_profile_count,
                entity_count=evidence.entity_count,
                association_status=evidence.association_status,
                metadata_json=evidence.to_dict(),
            ))
        for flower in dataset.flowers:
            session.add(HistoricalFlowerRow(
                dataset_id=dataset.dataset_id,
                flower_id=flower.flower_id,
                source_sha256=flower.source_sha256,
                topology=flower.topology,
                pass_count=len(flower.passes),
                quality_flags_json=list(flower.quality_flags),
                metadata_json=flower.to_dict(include_geometry=False),
            ))
            for item in flower.passes:
                session.add(HistoricalFlowerPassRow(
                    dataset_id=dataset.dataset_id,
                    flower_id=flower.flower_id,
                    pass_id=item.pass_id,
                    source_handle=item.source_handle,
                    inferred_order=item.inferred_order,
                    geometry_json={"points": item.points, "normalized_points": item.normalized_points},
                    feature_json=item.to_dict(include_points=False),
                    provenance_json={"source_sha256": item.source_sha256, "source_classification": "PRIVATE_PROTOTYPE"},
                ))
            for left, right in zip(flower.passes, flower.passes[1:]):
                session.add(HistoricalPassTransitionRow(
                    dataset_id=dataset.dataset_id,
                    flower_id=flower.flower_id,
                    from_pass_id=left.pass_id,
                    to_pass_id=right.pass_id,
                    transition_json={
                        "width_delta": right.width - left.width,
                        "height_delta": right.height - left.height,
                        "formedness_delta": right.formedness - left.formedness,
                        "bend_count_delta": right.bend_count - left.bend_count,
                    },
                ))
        for item in dataset.roller_station_evidence:
            session.add(HistoricalRollerStationEvidenceRow(
                dataset_id=dataset.dataset_id,
                flower_id=str(item.get("flower_id") or ""),
                pass_id=str(item.get("pass_id") or ""),
                role=str(item.get("role") or "UNKNOWN"),
                design_id=str(item.get("design_id") or ""),
                geometry_revision_id=item.get("geometry_revision_id"),
                evidence_json=dict(item),
            ))
    return dataset.dataset_id


def _pass_from_polyline(entity: Any, flower_id: str, index: int, source_sha256: str) -> HistoricalPass:
    points = _polyline_points(entity)
    return _pass_from_points(points, str(entity.dxf.handle), flower_id, index, source_sha256)


def _lwpolyline_points(entity: Any) -> tuple[tuple[float, float, float], ...]:
    return tuple((float(x), float(y), 0.0) for x, y, *_ in entity.get_points("xy"))


def _pass_from_points(points: tuple[tuple[float, float, float], ...], source_handle: str, flower_id: str, index: int, source_sha256: str) -> HistoricalPass:
    if len(points) >= 2 and _distance(points[0], points[-1]) > 1e-6:
        points = points + (points[0],)
    min_x = min((point[0] for point in points), default=0.0)
    max_x = max((point[0] for point in points), default=0.0)
    min_y = min((point[1] for point in points), default=0.0)
    max_y = max((point[1] for point in points), default=0.0)
    width = max_x - min_x
    height = max_y - min_y
    perimeter = _path_length(points)
    normalized = _normalize_closed(points, SAMPLE_COUNT)
    shape = tuple(value for point in normalized for value in point)
    bends, positions, directions = _turning_signature(points)
    flags: list[str] = []
    if width <= 0 or height < 0:
        flags.append("DEGENERATE_GEOMETRY")
    if len(points) < 4:
        flags.append("LOW_POINT_COUNT")
    return HistoricalPass(
        pass_id=f"{flower_id}-pass-{index:03d}",
        source_flower_id=flower_id,
        source_handle=source_handle,
        inferred_order=index,
        points=points,
        normalized_points=normalized,
        shape_vector=shape,
        width=width,
        height=height,
        outline_perimeter=perimeter,
        developed_length=perimeter / 2.0,
        bend_angles=bends,
        bend_positions=positions,
        bend_directions=directions,
        topology="CLOSED_SINGLE_LOOP" if points and _distance(points[0], points[-1]) <= 1e-6 else "OPEN",
        quality_flags=tuple(flags),
        source_sha256=source_sha256,
    )


def _polyline_points(entity: Any) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for vertex in entity.vertices:
        location = vertex.dxf.location
        point = (float(location.x), float(location.y), float(location.z))
        if not points or _distance(points[-1], point) > 1e-9:
            points.append(point)
    return tuple(points)


def _normalize_closed(points: tuple[tuple[float, float, float], ...], count: int) -> tuple[tuple[float, float], ...]:
    if not points:
        return tuple((0.0, 0.0) for _ in range(count))
    path = points[:-1] if len(points) > 1 and _distance(points[0], points[-1]) <= 1e-6 else points
    cumulative = [0.0]
    for left, right in zip(path, path[1:] + path[:1]):
        cumulative.append(cumulative[-1] + _distance(left, right))
    total = cumulative[-1]
    if total <= 1e-9:
        return tuple((0.0, 0.0) for _ in range(count))
    sampled = []
    for index in range(count):
        target = total * index / count
        segment = 0
        while segment + 1 < len(cumulative) and cumulative[segment + 1] < target:
            segment += 1
        left = path[segment % len(path)]
        right = path[(segment + 1) % len(path)]
        span = cumulative[segment + 1] - cumulative[segment]
        ratio = 0.0 if span <= 1e-12 else (target - cumulative[segment]) / span
        sampled.append((left[0] + (right[0] - left[0]) * ratio, left[1] + (right[1] - left[1]) * ratio))
    cx = sum(point[0] for point in sampled) / len(sampled)
    cy = sum(point[1] for point in sampled) / len(sampled)
    centered = tuple((point[0] - cx, point[1] - cy) for point in sampled)
    scale = math.sqrt(sum(x * x + y * y for x, y in centered) / len(centered)) or 1.0
    forward = tuple((round(x / scale, 8), round(y / scale, 8)) for x, y in centered)
    reverse_raw = tuple(reversed(centered))
    reverse = tuple((round(x / scale, 8), round(y / scale, 8)) for x, y in reverse_raw)
    return min(forward, reverse)


def _turning_signature(points: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[str, ...]]:
    if len(points) < 3:
        return (), (), ()
    turns: list[tuple[float, float]] = []
    total = max(_path_length(points), 1e-9)
    traversed = 0.0
    for left, center, right in zip(points, points[1:], points[2:]):
        a = math.atan2(center[1] - left[1], center[0] - left[0])
        b = math.atan2(right[1] - center[1], right[0] - center[0])
        delta = math.degrees((b - a + math.pi) % (2 * math.pi) - math.pi)
        traversed += _distance(left, center)
        if abs(delta) >= 7.5 and abs(delta) <= 172.5:
            turns.append((delta, traversed / total))
    angles = tuple(round(value[0], 4) for value in turns)
    positions = tuple(round(value[1], 6) for value in turns)
    directions = tuple("UP_BEND" if angle > 0 else "DOWN_BEND" for angle in angles)
    return angles, positions, directions


def _flower_topology(passes: tuple[HistoricalPass, ...]) -> str:
    topologies = {item.topology for item in passes}
    return next(iter(topologies)) if len(topologies) == 1 else "MIXED"


def _path_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(_distance(left, right) for left, right in zip(points, points[1:]))


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _assert_unchanged(path: Path, before: str) -> None:
    after = _sha256(path)
    if after != before:
        raise RuntimeError(f"private source changed during extraction: {path.name}")


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()
