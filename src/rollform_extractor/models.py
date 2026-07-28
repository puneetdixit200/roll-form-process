from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class BBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class CadPrimitive:
    kind: str
    attributes: Mapping[str, Any]
    source_handle: str


@dataclass(frozen=True)
class CadEntityRecord:
    handle: str
    entity_type: str
    layer: str
    color: int | str | None
    line_type: str | None
    layout: str
    bbox: BBox | None
    original_primitives: tuple[CadPrimitive, ...] = ()
    normalized_primitives: tuple[CadPrimitive, ...] = ()
    source_handles: tuple[str, ...] = ()
    method: str = "parsed"
    configuration_hash: str = ""
    confidence: float = 1.0
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StationRecord:
    station_id: str
    sequence_index: int | None
    bbox: BBox
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileRecord:
    profile_id: str
    station_id: str
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
    features: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollerOccurrenceRecord:
    occurrence_id: str
    station_id: str
    role: str | None
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WarningRecord:
    code: str
    message: str
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float


@dataclass(frozen=True)
class StageResult:
    stage: str
    records: tuple[Any, ...]
    warnings: tuple[WarningRecord, ...]
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
