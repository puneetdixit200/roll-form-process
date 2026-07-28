from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

import ezdxf

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord, RollerOccurrenceRecord, StationRecord, WarningRecord
from rollform_extractor.preview import render_drawing_preview
from rollform_extractor.review import write_review_queue


@dataclass(frozen=True)
class Manifest:
    project_path: Path
    files: Mapping[str, Mapping[str, Any]]
    dxf_files: tuple[Path, ...]
    source_sha256: str
    station_count: int


def export_project(bundle: ExtractionBundle, output_root: Path) -> Manifest:
    project_path = output_root / Path(bundle.source_path).stem
    project_path.mkdir(parents=True, exist_ok=True)
    stations_path = project_path / "stations"
    if stations_path.exists():
        shutil.rmtree(stations_path)
    stations_path.mkdir(exist_ok=True)
    (project_path / "previews").mkdir(exist_ok=True)
    (project_path / "summaries").mkdir(exist_ok=True)
    (project_path / "review").mkdir(exist_ok=True)

    _write_station_csv(project_path / "summaries" / "stations.csv", bundle.stations, bundle.profiles, bundle.roller_occurrences)
    render_drawing_preview(bundle.entities, project_path / "previews" / "classification.png")

    dxf_files = []
    export_warnings: list[WarningRecord] = []
    for station in sorted(bundle.stations, key=lambda item: item.sequence_index or 0):
        station_dir = project_path / "stations" / f"station_{station.sequence_index:02d}"
        station_dir.mkdir(exist_ok=True)
        profiles = tuple(profile for profile in bundle.profiles if profile.station_id == station.station_id)
        rollers = tuple(roller for roller in bundle.roller_occurrences if roller.station_id == station.station_id)
        path, warnings = _write_dxf(station_dir / "profile.dxf", _profile_primitives(profiles), bundle.configuration_hash)
        dxf_files.append(path)
        export_warnings.extend(warnings)
        if rollers:
            _write_rollers_csv(station_dir / "rollers.csv", rollers)
        for role in sorted({roller.role for roller in rollers if roller.role}):
            path, warnings = _write_dxf(station_dir / f"{role}.dxf", _roller_primitives(rollers, role), bundle.configuration_hash)
            dxf_files.append(path)
            export_warnings.extend(warnings)

    warnings = bundle.warnings + tuple(export_warnings)
    _write_json(project_path / "project.json", _project_payload(bundle, warnings))
    write_review_queue(project_path / "review", warnings, _review_template(bundle))
    (project_path / "report.html").write_text(_report(bundle), encoding="utf-8")
    files = _file_manifest(project_path)
    manifest = Manifest(project_path, files, tuple(dxf_files), bundle.source_sha256, len(bundle.stations))
    _write_json(project_path / "manifest.json", _manifest_payload(manifest))
    return manifest


def _project_payload(bundle: ExtractionBundle, warnings: tuple[WarningRecord, ...]) -> dict[str, Any]:
    return {
        "drawing_id": bundle.drawing_id,
        "source_path": str(bundle.source_path),
        "source_sha256": bundle.source_sha256,
        "configuration_hash": bundle.configuration_hash,
        "configuration_snapshot": _jsonable(bundle.configuration_snapshot),
        "units": bundle.configuration_snapshot.get("units", {}).get("default"),
        "station_count": len(bundle.stations),
        "stations": [_station(station) for station in bundle.stations],
        "profiles": [_profile(profile) for profile in bundle.profiles],
        "rollers": [_roller(roller) for roller in bundle.roller_occurrences],
        "warnings": [_warning(warning) for warning in warnings],
    }


def _station_csv_row(station: StationRecord, profiles: tuple[ProfileRecord, ...], rollers: tuple[RollerOccurrenceRecord, ...]) -> dict[str, Any]:
    return {
        "station_id": station.station_id,
        "sequence_index": station.sequence_index,
        "confidence": station.confidence,
        "profile_count": sum(profile.station_id == station.station_id for profile in profiles),
        "roller_count": sum(roller.station_id == station.station_id for roller in rollers),
    }


def _write_station_csv(path: Path, stations, profiles, rollers) -> None:
    rows = [_station_csv_row(station, profiles, rollers) for station in stations]
    _write_csv(path, rows, ("station_id", "sequence_index", "confidence", "profile_count", "roller_count"))


def _write_rollers_csv(path: Path, rollers: tuple[RollerOccurrenceRecord, ...]) -> None:
    rows = [
        {"occurrence_id": roller.occurrence_id, "role": roller.role or "", "confidence": roller.confidence}
        for roller in rollers
    ]
    _write_csv(path, rows, ("occurrence_id", "role", "confidence"))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_dxf(path: Path, primitives: Iterable[CadPrimitive], config_hash: str) -> tuple[Path, tuple[WarningRecord, ...]]:
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    warnings = []
    for primitive in primitives:
        if not _add_primitive(msp, primitive):
            warnings.append(
                WarningRecord(
                    "export",
                    f"unsupported DXF export primitive {primitive.kind}",
                    (primitive.source_handle,),
                    "exporter",
                    config_hash,
                    1.0,
                )
            )
    doc.saveas(path)
    return path, tuple(warnings)


def _add_primitive(msp, primitive: CadPrimitive) -> bool:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        msp.add_line(attrs["start"], attrs["end"])
    elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = [tuple(vertex["point"][:2]) for vertex in attrs.get("vertices", ())]
        if len(points) > 1:
            msp.add_lwpolyline(points, close=bool(attrs.get("closed")))
    elif primitive.kind == "CIRCLE":
        msp.add_circle(attrs["center"], float(attrs["radius"]))
    elif primitive.kind == "ARC":
        msp.add_arc(attrs["center"], float(attrs["radius"]), float(attrs["start_angle"]), float(attrs["end_angle"]))
    else:
        return False
    return True


def _profile_primitives(profiles: tuple[ProfileRecord, ...]) -> tuple[CadPrimitive, ...]:
    return tuple(primitive for profile in profiles for primitive in profile.features.get("normalized_primitives", ()))


def _roller_primitives(rollers: tuple[RollerOccurrenceRecord, ...], role: str) -> tuple[CadPrimitive, ...]:
    result = []
    for roller in rollers:
        if roller.role != role:
            continue
        center = roller.evidence.get("center")
        diameter = roller.evidence.get("outer_diameter_mm")
        if center and diameter:
            result.append(CadPrimitive("CIRCLE", {"center": (*center, 0.0), "radius": float(diameter) / 2.0}, roller.occurrence_id))
    return tuple(result)


def _review_template(bundle: ExtractionBundle) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_hash": bundle.source_sha256,
        "configuration_snapshot": _jsonable(bundle.configuration_snapshot),
        "stations": [],
        "profile_handles": {},
        "roller_handles": {},
    }


def _report(bundle: ExtractionBundle) -> str:
    return (
        "<!doctype html><title>Rollform Extraction</title>"
        f"<h1>{bundle.drawing_id}</h1><p>stations={len(bundle.stations)}</p>"
        f"<p>warnings={len(bundle.warnings)}</p>"
    )


def _file_manifest(project_path: Path) -> dict[str, dict[str, Any]]:
    return {
        str(path.relative_to(project_path)): {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in sorted(project_path.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }


def _manifest_payload(manifest: Manifest) -> dict[str, Any]:
    return {
        "source_sha256": manifest.source_sha256,
        "station_count": manifest.station_count,
        "dxf_files": [str(path.relative_to(manifest.project_path)) for path in manifest.dxf_files],
        "files": manifest.files,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _station(station: StationRecord) -> dict[str, Any]:
    return {
        "station_id": station.station_id,
        "sequence_index": station.sequence_index,
        "bbox": _bbox(station.bbox),
        "source_handles": list(station.source_handles),
        "confidence": station.confidence,
    }


def _profile(profile: ProfileRecord) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "station_id": profile.station_id,
        "source_handles": list(profile.source_handles),
        "confidence": profile.confidence,
        "features": _jsonable(profile.features),
    }


def _roller(roller: RollerOccurrenceRecord) -> dict[str, Any]:
    return {
        "occurrence_id": roller.occurrence_id,
        "station_id": roller.station_id,
        "role": roller.role,
        "source_handles": list(roller.source_handles),
        "confidence": roller.confidence,
        "evidence": _jsonable(roller.evidence),
    }


def _warning(warning) -> dict[str, Any]:
    return {
        "code": warning.code,
        "message": warning.message,
        "source_handles": list(warning.source_handles),
        "confidence": warning.confidence,
    }


def _bbox(bbox: BBox | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {"min_x": bbox.min_x, "min_y": bbox.min_y, "max_x": bbox.max_x, "max_y": bbox.max_y}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, CadPrimitive):
        return {"kind": value.kind, "attributes": _jsonable(value.attributes), "source_handle": value.source_handle}
    if isinstance(value, BBox):
        return _bbox(value)
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
