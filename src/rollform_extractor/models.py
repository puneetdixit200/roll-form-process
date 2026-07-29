from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping as MappingABC
from types import MappingProxyType
from typing import Any, Mapping


STAGE_TYPES = {
    "REFERENCE_GEOMETRY",
    "FLAT_STRIP",
    "FLOWER_PROFILE",
    "FORMING_STATION",
    "CALIBRATION_STATION",
    "FINAL_PROFILE",
    "ROLLER_DETAIL",
    "TOOLING_ASSEMBLY_DETAIL",
    "COMPOSITE_FLOWER",
    "MACHINE_LAYOUT",
    "UNKNOWN",
    "UNCLASSIFIED",
}


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
class TransformRecord:
    matrix_4x4: tuple[tuple[float, ...], ...]
    block_path: tuple[str, ...] = ()
    parent_block: str | None = None
    mirrored: bool = False


@dataclass(frozen=True)
class NormalizedGeometry:
    primitives: tuple[CadPrimitive, ...]
    sampled_points: tuple[tuple[float, float, float], ...]


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
    sampled_geometry: tuple[tuple[float, float, float], ...] = ()
    transform: TransformRecord | None = None
    source_handles: tuple[str, ...] = ()
    method: str = "parsed"
    configuration_hash: str = ""
    confidence: float = 1.0
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", _freeze(self.attributes))

    @property
    def original_primitive(self) -> CadPrimitive:
        return self.original_primitives[0]

    @property
    def original_dxf_attributes(self) -> Mapping[str, Any]:
        return self.attributes


@dataclass(frozen=True)
class ParseResult:
    entities: tuple[CadEntityRecord, ...]
    expanded_entities: tuple[CadEntityRecord, ...]
    warnings: tuple["WarningRecord", ...]
    method: str
    configuration_hash: str


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
class StationTransitionRecord:
    from_station_id: str
    to_station_id: str
    sequence_id: int
    measurements: Mapping[str, Any]
    source_handles: tuple[str, ...]
    method: str
    configuration_hash: str
    confidence: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "measurements", _freeze(self.measurements))


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
