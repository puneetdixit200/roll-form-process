from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping as MappingABC
from types import MappingProxyType
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _freeze(self.attributes))


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _freeze(self.attributes))


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze(self.evidence))


@dataclass(frozen=True)
class ProfileRecord:
    profile_id: str
    station_id: str
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
    features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", _freeze(self.features))


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze(self.evidence))


@dataclass(frozen=True)
class WarningRecord:
    code: str
    message: str
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float


def _freeze(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class StageResult:
    stage: str
    records: tuple[Any, ...]
    warnings: tuple[WarningRecord, ...]
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float
