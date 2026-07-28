from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

from rollform_extractor.models import BBox, CadEntityRecord, StationRecord, WarningRecord


SCHEMA_VERSION = 1
VALID_UNITS = {"mm", "millimeter", "millimetre", "in", "inch", "inches"}
VALID_ROLLER_ROLES = {
    "upper",
    "lower",
    "left",
    "centre",
    "center",
    "right",
    "side",
    "guide",
    "support",
    "shaft",
    "spacer",
    "distance_ring",
    "distance-ring",
    "unidentified",
}


class OverrideValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StationOverride:
    sequence_index: int
    bbox: BBox
    station_id: str | None = None
    source_handles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualOverrides:
    schema_version: int = SCHEMA_VERSION
    units: str | None = None
    station_boxes: tuple[StationOverride, ...] = ()
    profile_handles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    roller_handles: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    configuration_snapshot: Mapping[str, Any] = field(default_factory=dict)
    source_hash: str = ""


def load_overrides(path: Path, known_handles: set[str]) -> ManualOverrides:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise OverrideValidationError("manual overrides must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise OverrideValidationError(f"schema_version must be {SCHEMA_VERSION}")
    units = data.get("units")
    if units is not None and str(units).lower() not in VALID_UNITS:
        raise OverrideValidationError(f"invalid units: {units}")
    configuration_snapshot = data.get("configuration_snapshot", {})
    if not isinstance(configuration_snapshot, Mapping):
        raise OverrideValidationError("configuration_snapshot must be a mapping")

    stations = tuple(_station_override(item, known_handles) for item in _list(data, "stations"))
    _validate_station_order(stations)
    station_keys = {str(station.sequence_index) for station in stations}
    profile_handles = _handle_map(data.get("profile_handles", {}), known_handles, station_keys)
    roller_handles = _roller_map(data.get("roller_handles", {}), known_handles, station_keys)
    _validate_ownership(stations, profile_handles, roller_handles)
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return ManualOverrides(
        schema_version=SCHEMA_VERSION,
        units=units,
        station_boxes=stations,
        profile_handles=profile_handles,
        roller_handles=roller_handles,
        configuration_snapshot=configuration_snapshot,
        source_hash=sha256(payload.encode("utf-8")).hexdigest(),
    )


def apply_station_overrides(
    entities: Iterable[CadEntityRecord], overrides: ManualOverrides
) -> list[StationRecord]:
    records = tuple(entities)
    stations: list[StationRecord] = []
    bbox_owners: dict[str, str] = {}
    for override in sorted(overrides.station_boxes, key=lambda station: station.sequence_index):
        handles = set(override.source_handles)
        station_key = str(override.sequence_index)
        for entity in records:
            if entity.bbox is not None and _intersects(entity.bbox, override.bbox):
                owner = bbox_owners.setdefault(entity.handle, station_key)
                if owner != station_key:
                    raise OverrideValidationError(
                        f"entity handle assigned to multiple stations: {entity.handle}"
                    )
                handles.add(entity.handle)
        handles.update(overrides.profile_handles.get(station_key, ()))
        for role_handles in overrides.roller_handles.get(station_key, {}).values():
            handles.update(role_handles)
        stations.append(
            StationRecord(
                station_id=override.station_id or f"S{override.sequence_index}",
                sequence_index=override.sequence_index,
                bbox=override.bbox,
                source_handles=tuple(sorted(handles)),
                method="manual_override",
                configuration_hash=overrides.source_hash,
                confidence=1.0,
                evidence={
                    "schema_version": overrides.schema_version,
                    "units": overrides.units,
                    "configuration_snapshot": dict(overrides.configuration_snapshot),
                },
            )
        )
    return stations


def write_review_queue(
    path: Path, warnings: Iterable[WarningRecord], template: Mapping[str, Any]
) -> tuple[Path, Path]:
    path.mkdir(parents=True, exist_ok=True)
    json_path = path / "review_queue.json"
    csv_path = path / "review_queue.csv"
    preserved = _completed_items(json_path)
    preserved_keys = {_item_key(item) for item in preserved}
    new_items = [
        {
            "category": _category(warning.code),
            "message": warning.message,
            "source_handles": list(warning.source_handles),
            "method": warning.method,
            "configuration_hash": warning.configuration_hash,
            "confidence": warning.confidence,
        }
        for warning in warnings
    ]
    items = preserved + [item for item in new_items if _item_key(item) not in preserved_keys]
    json_path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "items": items}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = _csv_fieldnames(items)
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        for item in items:
            writer.writerow({**item, "source_handles": " ".join(item.get("source_handles", ()))})
    manual_path = path / "manual_overrides.json"
    if not manual_path.exists():
        manual_path.write_text(json.dumps(template, indent=2, sort_keys=True), encoding="utf-8")
    return json_path, csv_path


def _station_override(data: Any, known_handles: set[str]) -> StationOverride:
    if not isinstance(data, dict):
        raise OverrideValidationError("station override must be an object")
    try:
        sequence_index = data["sequence_index"]
    except KeyError as exc:
        raise OverrideValidationError("station sequence_index must be an integer") from exc
    if isinstance(sequence_index, bool) or not isinstance(sequence_index, int):
        raise OverrideValidationError("station sequence_index must be an integer")
    if sequence_index <= 0:
        raise OverrideValidationError("station sequence_index must be positive")
    bbox = _bbox(data.get("bbox"))
    handles = _known_handles(data.get("source_handles", []), known_handles)
    return StationOverride(
        sequence_index=sequence_index,
        bbox=bbox,
        station_id=str(data["station_id"]) if data.get("station_id") else None,
        source_handles=handles,
    )


def _bbox(data: Any) -> BBox:
    if not isinstance(data, dict):
        raise OverrideValidationError("station bbox must be an object")
    try:
        box = BBox(
            min_x=float(data["min_x"]),
            min_y=float(data["min_y"]),
            max_x=float(data["max_x"]),
            max_y=float(data["max_y"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OverrideValidationError("station bbox coordinates must be numeric") from exc
    if box.max_x <= box.min_x or box.max_y <= box.min_y:
        raise OverrideValidationError("station bbox must have positive area")
    return box


def _list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise OverrideValidationError(f"{key} must be a list")
    return value


def _validate_station_order(stations: tuple[StationOverride, ...]) -> None:
    seen: set[int] = set()
    for station in stations:
        if station.sequence_index in seen:
            raise OverrideValidationError(f"duplicate station sequence: {station.sequence_index}")
        seen.add(station.sequence_index)


def _handle_map(
    data: Any, known_handles: set[str], station_keys: set[str]
) -> dict[str, tuple[str, ...]]:
    if not isinstance(data, dict):
        raise OverrideValidationError("profile_handles must be an object")
    result: dict[str, tuple[str, ...]] = {}
    for station, handles in data.items():
        station_key = str(station)
        _validate_station_key(station_key, station_keys)
        result[station_key] = _known_handles(handles, known_handles)
    return result


def _roller_map(
    data: Any, known_handles: set[str], station_keys: set[str]
) -> dict[str, dict[str, tuple[str, ...]]]:
    if not isinstance(data, dict):
        raise OverrideValidationError("roller_handles must be an object")
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for station, roles in data.items():
        station_key = str(station)
        _validate_station_key(station_key, station_keys)
        if not isinstance(roles, dict):
            raise OverrideValidationError("roller station entry must be an object")
        result[station_key] = {}
        for role, handles in roles.items():
            if str(role).lower() not in VALID_ROLLER_ROLES:
                raise OverrideValidationError(f"invalid roller role: {role}")
            result[station_key][str(role)] = _known_handles(handles, known_handles)
    return result


def _validate_station_key(station_key: str, station_keys: set[str]) -> None:
    if station_key not in station_keys:
        raise OverrideValidationError(f"unknown station reference: {station_key}")


def _known_handles(handles: Any, known_handles: set[str]) -> tuple[str, ...]:
    if not isinstance(handles, list):
        raise OverrideValidationError("handle assignments must be lists")
    result = tuple(str(handle) for handle in handles)
    for handle in result:
        if handle not in known_handles:
            raise OverrideValidationError(f"unknown entity handle: {handle}")
    return result


def _validate_ownership(
    stations: tuple[StationOverride, ...],
    profile_handles: Mapping[str, tuple[str, ...]],
    roller_handles: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> None:
    owners: dict[str, str] = {}
    for station in stations:
        _claim(owners, station.source_handles, str(station.sequence_index))
    for station, handles in profile_handles.items():
        _claim(owners, handles, station)
    for station, roles in roller_handles.items():
        for handles in roles.values():
            _claim(owners, handles, station)


def _claim(owners: dict[str, str], handles: Iterable[str], station: str) -> None:
    for handle in handles:
        if handle in owners and owners[handle] == station:
            raise OverrideValidationError(f"entity handle assigned more than once: {handle}")
        owner = owners.setdefault(handle, station)
        if owner != station:
            raise OverrideValidationError(
                f"entity handle assigned to multiple stations: {handle}"
            )


def _intersects(left: BBox, right: BBox) -> bool:
    return (
        left.min_x <= right.max_x
        and left.max_x >= right.min_x
        and left.min_y <= right.max_y
        and left.max_y >= right.min_y
    )


def _category(code: str) -> str:
    return {
        "uncertain_boundaries": "uncertain_boundary",
        "geometry_shared_across_stations": "shared_station_geometry",
        "order_conflict": "uncertain_boundary",
        "unidentified_rollers": "roller_ambiguity",
    }.get(code, code)


def _completed_items(json_path: Path) -> list[dict[str, Any]]:
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items = data.get("items", []) if isinstance(data, dict) else []
    return [dict(item) for item in items if isinstance(item, dict) and _is_completed(item)]


def _is_completed(item: Mapping[str, Any]) -> bool:
    status = str(item.get("status", "")).lower()
    return (
        status in {"resolved", "completed", "complete"}
        or item.get("resolved") is True
        or item.get("completed") is True
        or bool(item.get("engineer_decision"))
    )


def _item_key(item: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    handles = item.get("source_handles", ())
    if isinstance(handles, str):
        handle_tuple = tuple(handles.split())
    else:
        handle_tuple = tuple(str(handle) for handle in handles)
    return str(item.get("category", "")), handle_tuple


def _csv_fieldnames(items: Iterable[Mapping[str, Any]]) -> list[str]:
    base = [
        "category",
        "message",
        "source_handles",
        "method",
        "configuration_hash",
        "confidence",
    ]
    extras = sorted({key for item in items for key in item.keys()} - set(base))
    return base + extras
