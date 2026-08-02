from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

import ezdxf
from PIL import Image, ImageDraw, ImageFont

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord, RollerOccurrenceRecord, StationRecord, WarningRecord
from rollform_extractor.preview import render_drawing_preview, render_manual_review_preview, render_stage_review_preview
from rollform_extractor.report import write_engineering_report
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
    render_manual_review_preview(bundle.entities, project_path / "previews" / "manual_review_handles.png")

    dxf_files = []
    export_warnings: list[WarningRecord] = []
    for station in sorted(bundle.stations, key=lambda item: (_sequence_id(item), item.sequence_index or 0, item.station_id)):
        station_dir = project_path / "stations" / _station_dir_name(station, bundle.stations)
        station_dir.mkdir(exist_ok=True)
        profiles = tuple(profile for profile in bundle.profiles if profile.station_id == station.station_id)
        rollers = tuple(roller for roller in bundle.roller_occurrences if roller.station_id == station.station_id)
        render_stage_review_preview(
            bundle.entities,
            station_dir / "review.png",
            station.bbox,
            _stage_title(station, profiles, rollers),
            profile_handles=tuple(handle for profile in profiles for handle in profile.source_handles),
            upper_handles=_roller_handles(rollers, "upper"),
            lower_handles=_roller_handles(rollers, "lower"),
            side_handles=_roller_handles(rollers, "side"),
        )
        if _region_type(station) == "COMPOSITE_FLOWER" and profiles:
            passes_dir = station_dir / "composite_passes"
            passes_dir.mkdir(exist_ok=True)
            for profile in sorted(profiles, key=lambda item: int(item.features.get("composite_pass_index", 0))):
                pass_path, warnings = _write_dxf(
                    passes_dir / f"profile_pass_{int(profile.features.get('composite_pass_index', 0)):02d}.dxf",
                    _profile_primitives((profile,)),
                    bundle.configuration_hash,
                )
                dxf_files.append(pass_path)
                export_warnings.extend(warnings)
            _write_json(passes_dir / "passes.json", [_profile(profile) for profile in profiles])
        elif (profile_primitives := _profile_primitives(profiles)):
            path, warnings = _write_dxf(station_dir / "profile.dxf", profile_primitives, bundle.configuration_hash)
            dxf_files.append(path)
            export_warnings.extend(warnings)
        else:
            _write_json(
                station_dir / "profile_not_detected.json",
                {
                    "station_id": station.station_id,
                    "sequence_id": _sequence_id(station),
                    "stage_order": station.sequence_index,
                    "reason": "no accepted profile geometry",
                },
            )
        if rollers:
            _write_rollers_csv(station_dir / "rollers.csv", rollers)
        for role in sorted({roller.role for roller in rollers if roller.role}):
            path, warnings = _write_dxf(station_dir / f"{role}.dxf", _roller_primitives(rollers, role), bundle.configuration_hash)
            dxf_files.append(path)
            export_warnings.extend(warnings)
    composite_dxfs, composite_warnings = _export_composite_flowers(bundle, project_path)
    dxf_files.extend(composite_dxfs)
    export_warnings.extend(composite_warnings)

    warnings = bundle.warnings + tuple(export_warnings)
    _write_json(project_path / "project.json", _project_payload(bundle, warnings))
    write_review_queue(project_path / "review", warnings, _review_template(bundle))
    _write_pass_order_evidence(bundle, project_path)
    write_engineering_report(bundle, project_path, warnings)
    files = _file_manifest(project_path)
    manifest = Manifest(project_path, files, tuple(dxf_files), bundle.source_sha256, len(bundle.stations))
    _write_json(project_path / "manifest.json", _manifest_payload(manifest))
    return manifest


def _write_pass_order_evidence(bundle: ExtractionBundle, project_path: Path) -> None:
    """Export alignment evidence without making an inferred order authoritative."""
    rows: list[dict[str, Any]] = []
    for flower in getattr(bundle, "composite_flowers", ()):
        for item in flower.passes:
            candidates = [
                {
                    "candidate_profile_id": match.get("candidate_profile_id"),
                    "candidate_station_id": match.get("candidate_station_id"),
                    "candidate_sequence_id": match.get("candidate_sequence_id"),
                    "candidate_station_order": match.get("candidate_station_order"),
                    "geometry_similarity": match.get("geometry_similarity"),
                    "developed_length_difference": match.get("developed_length_difference"),
                    "bend_signature_difference": match.get("bend_signature_difference"),
                    "evidence_coverage": match.get("evidence_coverage"),
                    "quality_flags": match.get("quality_flags", ()),
                }
                for match in item.individual_profile_matches
            ]
            rows.append({
                "composite_flower_id": flower.composite_flower_id,
                "pass_id": item.pass_id,
                "profile_id": item.profile_id,
                "source_handles": item.source_handles,
                "inferred_order": item.inferred_order,
                "confirmed_order": item.confirmed_order,
                "current_station_id": item.station_id,
                "candidates": candidates,
                "recommended_correction": "ENGINEER_CONFIRMATION_REQUIRED",
                "preview_paths": {
                    "original": f"../composite_flowers/{flower.composite_flower_id}/passes/{item.pass_id}/profile_original_coordinates.png",
                    "normalized": f"../composite_flowers/{flower.composite_flower_id}/passes/{item.pass_id}/profile_normalized.png",
                },
            })
    review_dir = project_path / "review"
    _write_json(review_dir / "pass_order_evidence.json", {
        "schema_version": 2,
        "status": "ENGINEER_CONFIRMATION_REQUIRED",
        "drawing_id": bundle.drawing_id,
        "rows": rows,
    })
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{_html_escape(str(value))}</td>" for value in (
            row["pass_id"], row["profile_id"], ", ".join(row["source_handles"]),
            row["inferred_order"], row["current_station_id"], len(row["candidates"]),
            row["recommended_correction"],
        )) + "</tr>"
        for row in rows
    )
    (review_dir / "pass_order_evidence.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Pass order evidence</title>"
        "<h1>Pass order evidence</h1><p>Engineer confirmation required; inferred values are not authoritative.</p>"
        "<table><thead><tr><th>Pass</th><th>Profile</th><th>Handles</th><th>Inferred order</th>"
        "<th>Current station</th><th>Candidates</th><th>Status</th></tr></thead>"
        f"<tbody>{html_rows}</tbody></table>", encoding="utf-8"
    )


def _html_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _project_payload(bundle: ExtractionBundle, warnings: tuple[WarningRecord, ...]) -> dict[str, Any]:
    return {
        "drawing_id": bundle.drawing_id,
        "source_path": str(bundle.source_path),
        "source_sha256": bundle.source_sha256,
        "configuration_hash": bundle.configuration_hash,
        "configuration_snapshot": _jsonable(bundle.configuration_snapshot),
        "units": bundle.configuration_snapshot.get("units", {}).get("default")
        or bundle.configuration_snapshot.get("units", {}).get("detected"),
        "units_confirmed": bool(bundle.configuration_snapshot.get("units", {}).get("confirmed")),
        "station_count": len(bundle.stations),
        "summary": _summary(bundle, warnings),
        "stations": [_station(station) for station in bundle.stations],
        "profiles": [_profile(profile) for profile in bundle.profiles],
        "rollers": [_roller(roller) for roller in bundle.roller_occurrences],
        "sequences": _sequences(bundle.stations),
        "rejected_composite_regions": [_jsonable(region) for region in getattr(bundle, "rejected_composite_regions", ())],
        "warnings": [_warning(warning) for warning in warnings],
    }


def _station_csv_row(station: StationRecord, profiles: tuple[ProfileRecord, ...], rollers: tuple[RollerOccurrenceRecord, ...]) -> dict[str, Any]:
    return {
        "station_id": station.station_id,
        "sequence_index": station.sequence_index,
        "sequence_id": station.evidence.get("sequence_id"),
        "region_type": _region_type(station),
        "stage_type": station.evidence.get("stage_type", _region_type(station)),
        "confirmation_status": station.evidence.get("confirmation_status", "candidate"),
        "method": station.method,
        "confidence": station.confidence,
        "profile_count": sum(profile.station_id == station.station_id for profile in profiles),
        "roller_count": sum(roller.station_id == station.station_id for roller in rollers),
    }


def _write_station_csv(path: Path, stations, profiles, rollers) -> None:
    rows = [_station_csv_row(station, profiles, rollers) for station in stations]
    _write_csv(path, rows, ("station_id", "sequence_id", "sequence_index", "region_type", "stage_type", "confirmation_status", "method", "confidence", "profile_count", "roller_count"))


def _write_rollers_csv(path: Path, rollers: tuple[RollerOccurrenceRecord, ...]) -> None:
    rows = [
        {"occurrence_id": roller.occurrence_id, "role": roller.role or "", "confidence": roller.confidence}
        for roller in rollers
    ]
    _write_csv(path, rows, ("occurrence_id", "role", "confidence"))


def _export_composite_flowers(bundle: ExtractionBundle, project_path: Path) -> tuple[list[Path], list[WarningRecord]]:
    root = project_path / "composite_flowers"
    if root.exists():
        shutil.rmtree(root)
    composites = tuple(getattr(bundle, "composite_flowers", ()))
    if not composites:
        return [], []
    root.mkdir(exist_ok=True)
    entities_by_handle = {
        handle: entity
        for entity in bundle.entities
        for handle in (entity.source_handles or (entity.handle,))
    }
    dxf_files: list[Path] = []
    warnings: list[WarningRecord] = []
    units = bundle.configuration_snapshot.get("units", {})
    units_confirmed = bool(units.get("confirmed"))
    factor = float(units.get("conversion_factor_to_mm") or 1.0)
    for composite in composites:
        composite_dir = root / composite.composite_flower_id
        passes_dir = composite_dir / "passes"
        passes_dir.mkdir(parents=True, exist_ok=True)
        pass_entities = tuple(
            entity
            for item in composite.passes
            for handle in item.source_handles
            if (entity := entities_by_handle.get(handle)) is not None
        )
        complete_path, complete_warnings = _write_dxf(
            composite_dir / "complete_composite_flower.dxf",
            _source_primitives(pass_entities),
            bundle.configuration_hash,
        )
        overlay_path, overlay_warnings = _write_dxf(
            composite_dir / "overlaid_reconstruction.dxf",
            _source_primitives(pass_entities),
            bundle.configuration_hash,
        )
        dxf_files.extend([complete_path, overlay_path])
        warnings.extend(complete_warnings + overlay_warnings)
        render_drawing_preview(pass_entities, composite_dir / "complete_composite_flower.png")
        render_drawing_preview(pass_entities, composite_dir / "overlaid_reconstruction.png")
        _render_composite_debug(composite.passes, entities_by_handle, composite_dir / "extraction_debug.png")
        render_drawing_preview(_sequence_preview_entities(composite.passes, entities_by_handle), composite_dir / "sequence_preview.png")
        _write_json(composite_dir / "extraction_summary.json", _composite_summary(composite, units_confirmed))
        _write_composite_sequence_csv(composite_dir / "sequence.csv", composite, units_confirmed, factor)
        (composite_dir / "summaries").mkdir(exist_ok=True)
        feature_rows = []
        for item in composite.passes:
            pass_dir = passes_dir / item.pass_id
            pass_dir.mkdir(exist_ok=True)
            entities = tuple(entities_by_handle[handle] for handle in item.source_handles if handle in entities_by_handle)
            original_primitives = _source_primitives(entities) or _profile_feature_primitives(item.profile)
            normalized_primitives = _translated_primitives(original_primitives, item.transform_matrix_4x4)
            for name, primitives in (
                ("profile.dxf", original_primitives),
                ("profile_original_coordinates.dxf", original_primitives),
                ("profile_normalized.dxf", normalized_primitives),
                ("profile_outline.dxf", original_primitives),
                ("profile_neutral_line.dxf", item.neutral_line_primitives),
            ):
                path, export_warnings = _write_dxf(pass_dir / name, primitives, bundle.configuration_hash)
                dxf_files.append(path)
                warnings.extend(export_warnings)
            feature = bundle.pass_features.get((composite.composite_flower_id, item.pass_id))
            _write_json(pass_dir / "profile.json", _composite_pass_payload(item, units_confirmed, factor, feature))
            _write_json(pass_dir / "profile_geometry.json", _composite_geometry_payload(item, original_primitives))
            _write_json(pass_dir / "source_entities.json", {"entities": [_source_entity(entity) for entity in entities]})
            _write_json(pass_dir / "transform.json", {"matrix_4x4": item.transform_matrix_4x4})
            render_drawing_preview(entities or _preview_entities_from_primitives(item.pass_id, original_primitives), pass_dir / "profile.png")
            render_drawing_preview(_preview_entities_from_primitives(f"{item.pass_id}_original", original_primitives), pass_dir / "profile_original_coordinates.png")
            render_drawing_preview(_preview_entities_from_primitives(f"{item.pass_id}_normalized", normalized_primitives), pass_dir / "profile_normalized.png")
            render_drawing_preview(_preview_entities_from_primitives(f"{item.pass_id}_outline", original_primitives), pass_dir / "profile_outline.png")
            render_drawing_preview(_preview_entities_from_primitives(f"{item.pass_id}_neutral", item.neutral_line_primitives), pass_dir / "profile_neutral_line.png")
            if feature is not None:
                _write_json(pass_dir / "pass_features.json", feature.to_dict())
                _write_json(pass_dir / "pass_feature_vector.json", {"schema_version": feature.schema_version, "scalar": _jsonable(feature.scalar_vector), "shape": _jsonable(feature.shape_vector), "full": _jsonable(feature.full_vector), "fingerprints": _jsonable(feature.fingerprints)})
                _write_csv(pass_dir / "segments.csv", [_jsonable(asdict(segment)) for segment in feature.segments], tuple(asdict(feature.segments[0]).keys()) if feature.segments else ("segment_id",))
                _write_csv(pass_dir / "bend_features.csv", [_jsonable(dict(bend)) for bend in feature.bends], tuple(feature.bends[0].keys()) if feature.bends else ("bend_id",))
                feature_rows.append({"composite_flower_id": feature.composite_flower_id, "pass_id": feature.pass_id, "profile_id": feature.profile_id, "station_id": feature.station_id, "inferred_pass_order": feature.inferred_pass_order, "schema_version": feature.schema_version, "confidence": feature.quality.confidence, "quality_flags": ";".join(feature.quality.flags), **{field: feature.scalar_vector.values[index] for index, field in enumerate(feature.scalar_vector.field_names)}})
        if feature_rows:
            _write_csv(composite_dir / "summaries" / "pass_features.csv", feature_rows, tuple(feature_rows[0].keys()))
            _write_json(composite_dir / "summaries" / "pass_feature_index.json", {"schema_version": 1, "feature_set_count": len(feature_rows), "passes": [{"pass_id": row["pass_id"], "path": f"passes/{row['pass_id']}/pass_features.json"} for row in feature_rows]})
    return dxf_files, warnings


def _write_composite_sequence_csv(path: Path, composite, units_confirmed: bool, factor: float) -> None:
    rows = []
    for item in composite.passes:
        rows.append(
            {
                "composite_flower_id": composite.composite_flower_id,
                "pass_id": item.pass_id,
                "inferred_order": item.inferred_order,
                "confirmed_order": item.confirmed_order if item.confirmed_order is not None else "",
                "profile_type": item.profile_type,
                "source_handles": " ".join(item.source_handles),
                "source_layers": " ".join(item.source_layers),
                "developed_length_drawing_units": item.developed_length,
                "developed_length_mm": item.developed_length * factor if units_confirmed else "",
                "width": item.width,
                "height": item.height,
                "bend_count": item.bend_count,
                "total_bend_angle": item.total_bend_angle,
                "contour_confidence": item.confidence,
                "order_confidence": item.order_confidence,
                "duplicate_group_id": item.duplicate_group_id or "",
                "requires_review": item.requires_review,
                "dxf_path": f"passes/{item.pass_id}/profile.dxf",
                "preview_path": f"passes/{item.pass_id}/profile.png",
            }
        )
    _write_csv(
        path,
        rows,
        (
            "composite_flower_id",
            "pass_id",
            "inferred_order",
            "confirmed_order",
            "profile_type",
            "source_handles",
            "source_layers",
            "developed_length_drawing_units",
            "developed_length_mm",
            "width",
            "height",
            "bend_count",
            "total_bend_angle",
            "contour_confidence",
            "order_confidence",
            "duplicate_group_id",
            "requires_review",
            "dxf_path",
            "preview_path",
        ),
    )


def _composite_summary(composite, units_confirmed: bool) -> dict[str, Any]:
    return {
        "composite_flower_id": composite.composite_flower_id,
        "source_region_id": composite.source_region_id,
        "pass_count": composite.pass_count,
        "sequence_confidence": composite.sequence_confidence,
        "confirmed": composite.confirmed,
        "units_confirmed": units_confirmed,
        "source_bbox": _bbox(composite.source_bbox),
        "passes": [_composite_pass_payload(item, units_confirmed, 1.0) for item in composite.passes],
    }


def _composite_pass_payload(item, units_confirmed: bool, factor: float, feature=None) -> dict[str, Any]:
    outline_perimeter = feature.geometry.contour.get("perimeter") if feature is not None else None
    outline_perimeter_mm = outline_perimeter * factor if units_confirmed and outline_perimeter is not None else None
    return {
        "pass_id": item.pass_id,
        "composite_flower_id": item.composite_flower_id,
        "station_id": item.station_id,
        "profile_id": item.profile_id,
        "automatically_inferred_order": item.inferred_order,
        "engineer_confirmed_order": item.confirmed_order,
        "profile_type": item.profile_type,
        "source_handles": list(item.source_handles),
        "source_layers": list(item.source_layers),
        "developed_length_drawing_units": item.developed_length,
        "outline_perimeter_drawing_units": outline_perimeter,
        "outline_perimeter_mm": outline_perimeter_mm,
        "generated_neutral_developed_length_drawing_units": item.neutral_line_developed_length,
        "generated_neutral_developed_length_mm": item.neutral_line_developed_length * factor if units_confirmed else None,
        "expected_neutral_developed_length_drawing_units": item.expected_neutral_length,
        "expected_neutral_developed_length_mm": item.expected_neutral_length * factor if units_confirmed and item.expected_neutral_length is not None else None,
        "neutral_length_error_drawing_units": item.neutral_length_error,
        "neutral_length_error_mm": item.neutral_length_error * factor if units_confirmed and item.neutral_length_error is not None else None,
        "expected_neutral_length": item.expected_neutral_length,
        "generated_neutral_length": item.neutral_line_developed_length,
        "neutral_length_error": item.neutral_length_error,
        "neutral_length_error_percent": item.neutral_length_error_percent,
        "developed_length_mm": item.developed_length * factor if units_confirmed else None,
        "width": item.width,
        "height": item.height,
        "bend_count": item.bend_count,
        "total_bend_angle": item.total_bend_angle,
        "sheet_thickness_drawing_units": item.sheet_thickness,
        "neutral_line_method": item.neutral_line_method,
        "neutral_line_confidence": item.neutral_line_confidence,
        "physical_bends": _jsonable(item.physical_bends),
        "bend_zones": _jsonable(item.physical_bends),
        "active_bend_count": item.active_bend_count,
        "bend_signature": item.bend_signature,
        "vertex_turn_count": item.vertex_turn_count,
        "raw_geometry_corner_count": item.raw_geometry_corner_count,
        "physical_forming_bend_count": item.physical_forming_bend_count,
        "raw_total_turning_angle": item.raw_total_turning_angle,
        "physical_total_bend_angle": item.physical_total_bend_angle,
        "contour_confidence": item.confidence,
        "order_confidence": item.order_confidence,
        "duplicate_group_id": item.duplicate_group_id,
        "duplicate_of": item.duplicate_of,
        "requires_review": item.requires_review,
        "transform_matrix_4x4": item.transform_matrix_4x4,
        "individual_profile_matches": _jsonable(item.individual_profile_matches),
    }


def _composite_geometry_payload(item, original_primitives: tuple[CadPrimitive, ...]) -> dict[str, Any]:
    return {
        "profile_representation": item.profile_type,
        "original_strip_outline": [_jsonable(primitive) for primitive in original_primitives],
        "neutral_line": {
            "method": item.neutral_line_method,
            "confidence": item.neutral_line_confidence,
            "primitives": [_jsonable(primitive) for primitive in item.neutral_line_primitives],
            "expected_length": item.expected_neutral_length,
            "generated_length": item.neutral_line_developed_length,
            "length_error": item.neutral_length_error,
            "length_error_percent": item.neutral_length_error_percent,
        },
        "sheet_thickness_drawing_units": item.sheet_thickness,
        "physical_bends": _jsonable(item.physical_bends),
        "bend_zones": _jsonable(item.physical_bends),
        "raw_geometry_corner_count": item.raw_geometry_corner_count,
        "vertex_turn_count": item.vertex_turn_count,
        "raw_total_turning_angle": item.raw_total_turning_angle,
        "physical_forming_bend_count": item.physical_forming_bend_count,
        "physical_total_bend_angle": item.physical_total_bend_angle,
        "active_bend_count": item.active_bend_count,
        "bend_signature": item.bend_signature,
    }


def _source_entity(entity) -> dict[str, Any]:
    return {
        "handle": entity.handle,
        "source_handles": list(entity.source_handles or (entity.handle,)),
        "entity_type": entity.entity_type,
        "layer": entity.layer,
        "bbox": _bbox(entity.bbox),
        "original_primitives": [_jsonable(primitive) for primitive in entity.original_primitives],
    }


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


def _source_primitives(entities: tuple[Any, ...]) -> tuple[CadPrimitive, ...]:
    return tuple(primitive for entity in entities for primitive in (entity.original_primitives or entity.normalized_primitives))


def _profile_feature_primitives(profile: ProfileRecord) -> tuple[CadPrimitive, ...]:
    return tuple(profile.features.get("original_primitives", ()) or profile.features.get("normalized_primitives", ()))


def _translated_primitives(primitives: tuple[CadPrimitive, ...], matrix: tuple[tuple[float, ...], ...]) -> tuple[CadPrimitive, ...]:
    return tuple(_translate_primitive(primitive, matrix) for primitive in primitives)


def _translate_primitive(primitive: CadPrimitive, matrix: tuple[tuple[float, ...], ...]) -> CadPrimitive:
    dx = float(matrix[0][3])
    dy = float(matrix[1][3])
    attrs = dict(primitive.attributes)
    if primitive.kind == "LINE":
        attrs["start"] = _translated_point(attrs["start"], dx, dy)
        attrs["end"] = _translated_point(attrs["end"], dx, dy)
    elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        attrs["vertices"] = tuple(
            {**dict(vertex), "point": _translated_point(vertex["point"], dx, dy)}
            for vertex in attrs.get("vertices", ())
        )
        if "points" in attrs:
            attrs["points"] = tuple(_translated_point(point, dx, dy) for point in attrs["points"])
    elif primitive.kind in {"CIRCLE", "ARC"}:
        attrs["center"] = _translated_point(attrs["center"], dx, dy)
    return CadPrimitive(primitive.kind, attrs, primitive.source_handle)


def _translated_point(point, dx: float, dy: float) -> tuple[float, float, float]:
    return (float(point[0]) + dx, float(point[1]) + dy, float(point[2]) if len(point) > 2 else 0.0)


def _sequence_preview_entities(passes, entities_by_handle: Mapping[str, Any]) -> tuple[Any, ...]:
    result = []
    cursor = 0.0
    gap = 20.0
    for item in sorted(passes, key=lambda record: record.inferred_order):
        source = tuple(entities_by_handle[handle] for handle in item.source_handles if handle in entities_by_handle)
        primitives = _source_primitives(source) or _profile_feature_primitives(item.profile)
        local = _translated_primitives(primitives, item.transform_matrix_4x4)
        bbox = _bbox_from_primitives(local)
        offset = cursor - (bbox.min_x if bbox else 0.0)
        shifted = _translated_primitives(local, ((1.0, 0.0, 0.0, offset), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        result.extend(_preview_entities_from_primitives(item.pass_id, shifted))
        if bbox:
            cursor += max(bbox.max_x - bbox.min_x, 1.0) + gap
    return tuple(result)


def _preview_entities_from_primitives(handle_prefix: str, primitives: tuple[CadPrimitive, ...]) -> tuple[Any, ...]:
    from rollform_extractor.models import CadEntityRecord

    records = []
    for index, primitive in enumerate(primitives):
        points = _primitive_points(primitive)
        bbox = _bbox_from_points(points)
        records.append(
            CadEntityRecord(
                f"{handle_prefix}_{index}",
                primitive.kind,
                "COMPOSITE_FLOWER",
                7,
                "CONTINUOUS",
                "model",
                bbox,
                (primitive,),
                (primitive,),
                points,
                source_handles=(primitive.source_handle,),
            )
        )
    return tuple(records)


def _bbox_from_primitives(primitives: tuple[CadPrimitive, ...]) -> BBox | None:
    return _bbox_from_points(tuple(point for primitive in primitives for point in _primitive_points(primitive)))


def _bbox_from_points(points: tuple[tuple[float, float, float], ...]) -> BBox | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def _primitive_points(primitive: CadPrimitive) -> tuple[tuple[float, float, float], ...]:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        return (tuple(attrs["start"]), tuple(attrs["end"]))
    if primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        return tuple(tuple(vertex["point"]) for vertex in attrs.get("vertices", ())) or tuple(tuple(point) for point in attrs.get("points", ()))
    if primitive.kind in {"CIRCLE", "ARC"}:
        center = attrs["center"]
        radius = float(attrs["radius"])
        return ((center[0] - radius, center[1] - radius, 0.0), (center[0] + radius, center[1] + radius, 0.0))
    return ()


def _render_composite_debug(passes, entities_by_handle: Mapping[str, Any], path: Path) -> None:
    pass_records = []
    for item in sorted(passes, key=lambda record: record.inferred_order):
        entities = tuple(entities_by_handle[handle] for handle in item.source_handles if handle in entities_by_handle)
        primitives = _source_primitives(entities) or _profile_feature_primitives(item.profile)
        points = tuple(point for entity in entities for point in entity.sampled_geometry) or tuple(point for primitive in primitives for point in _primitive_points(primitive))
        bbox = _bbox_from_points(points)
        pass_records.append((item, entities, primitives, points, bbox))
    all_points = tuple(point for _item, _entities, _primitives, points, _bbox in pass_records for point in points)
    bounds = _bbox_from_points(all_points)
    if bounds is None:
        Image.new("RGB", (256, 256), "white").save(path)
        return
    margin = 28
    span_x = max(bounds.max_x - bounds.min_x, 1.0)
    span_y = max(bounds.max_y - bounds.min_y, 1.0)
    scale = min(1400 / span_x, 900 / span_y)
    width = max(256, int(span_x * scale + margin * 2))
    height = max(256, int(span_y * scale + margin * 2))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    palette = (
        (22, 109, 160),
        (218, 95, 2),
        (0, 138, 82),
        (204, 121, 167),
        (213, 94, 0),
        (86, 180, 233),
        (230, 159, 0),
        (0, 114, 178),
        (240, 128, 128),
        (80, 80, 80),
        (120, 80, 170),
        (40, 150, 120),
    )
    for color_index, (item, _entities, _primitives, _points, _bbox) in enumerate(pass_records):
        color = palette[color_index % len(palette)]
        x = 12 + (color_index % 6) * 170
        y = 8 + (color_index // 6) * 18
        draw.rectangle((x, y, x + 14, y + 10), fill=color)
        draw.text((x + 18, y - 1), f"{item.inferred_order}: {item.pass_id}", fill=color, font=font)
    for color_index, (item, entities, primitives, points, bbox) in enumerate(pass_records):
        color = palette[color_index % len(palette)]
        drew_sampled = False
        for entity in entities:
            if len(entity.sampled_geometry) > 1:
                draw.line([_debug_point(point, bounds, scale, height, margin) for point in entity.sampled_geometry], fill=color, width=4)
                drew_sampled = True
        if not drew_sampled:
            for primitive in primitives:
                _draw_debug_primitive(draw, primitive, bounds, scale, height, margin, color)
        if bbox is not None:
            x, y = _debug_point((bbox.min_x, bbox.max_y, 0.0), bounds, scale, height, margin)
            label = f"{item.inferred_order}: {' '.join(item.source_handles)}"
            draw.text((x + 3, max(0, y - 12)), label, fill=color, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _draw_debug_primitive(draw, primitive: CadPrimitive, bounds: BBox, scale: float, height: int, margin: int, color) -> None:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        draw.line((_debug_point(attrs["start"], bounds, scale, height, margin), _debug_point(attrs["end"], bounds, scale, height, margin)), fill=color, width=2)
    elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = _primitive_points(primitive)
        if len(points) > 1:
            draw.line([_debug_point(point, bounds, scale, height, margin) for point in points], fill=color, width=2)
            if attrs.get("closed"):
                draw.line((_debug_point(points[-1], bounds, scale, height, margin), _debug_point(points[0], bounds, scale, height, margin)), fill=color, width=2)
    elif primitive.kind == "CIRCLE":
        center = attrs["center"]
        radius = float(attrs["radius"]) * scale
        x, y = _debug_point(center, bounds, scale, height, margin)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
    elif primitive.kind == "ARC":
        points = _primitive_points(primitive)
        if len(points) > 1:
            draw.line([_debug_point(point, bounds, scale, height, margin) for point in points], fill=color, width=2)


def _debug_point(point, bounds: BBox, scale: float, height: int, margin: int) -> tuple[int, int]:
    return (
        int(round((float(point[0]) - bounds.min_x) * scale + margin)),
        int(round(height - ((float(point[1]) - bounds.min_y) * scale + margin))),
    )


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
        "drawing_units": {
            "detected": bundle.configuration_snapshot.get("units", {}).get("detected"),
            "engineer_confirmed_unit": None,
            "conversion_factor_to_mm": None,
            "confirmed": False,
        },
        "stations": [
            {
                "station_id": station.station_id,
                "sequence_id": _sequence_id(station),
                "sequence_index": station.sequence_index,
                "region_type": _region_type(station),
                "stage_type": _region_type(station),
                "confirmed": False,
                "physical_tooling_station": False,
                "composite_flower": _region_type(station) == "COMPOSITE_FLOWER",
                "bbox": _bbox(station.bbox),
                "source_handles": list(station.source_handles),
            }
            for station in sorted(bundle.stations, key=lambda item: (_sequence_id(item), item.sequence_index or 0))
        ],
        "profile_handles": {},
        "roller_handles": {},
    }


def _report(bundle: ExtractionBundle) -> str:
    sequences = _sequences(bundle.stations)
    tooling = [station for station in bundle.stations if station.evidence.get("machine_tooling_station")]
    confirmed_rollers = [roller for roller in bundle.roller_occurrences if roller.role and roller.confidence >= 0.65]
    summary = _summary(bundle, bundle.warnings)
    cards = "\n".join(_stage_card(bundle, station) for station in sorted(bundle.stations, key=lambda item: (_sequence_id(item), item.sequence_index or 0)))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rollform Review - {bundle.drawing_id}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#f7f7f5;color:#202020}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:16px 0}}
.metric,.stage{{background:white;border:1px solid #ddd;border-radius:8px;padding:12px}}
.stages{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
img{{max-width:100%;border:1px solid #ddd;background:white}}
.candidate{{color:#8a5a00}} .confirmed{{color:#0b6b35}} .warn{{color:#9b1c1c}}
a{{color:#174ea6}}
</style></head><body>
<h1>{bundle.drawing_id}</h1>
<p>Review status: candidates are not accepted engineering data until confirmed in <code>review/manual_overrides.json</code>.</p>
<div class="metrics">
{_metric("Sequences", len(sequences))}
{_metric("Drawing stages", len(bundle.stations))}
{_metric("Actual tooling stations", len(tooling))}
{_metric("Profiles detected", len(bundle.profiles))}
{_metric("Roller candidates", len(bundle.roller_occurrences))}
{_metric("Confirmed rollers", len(confirmed_rollers))}
{_metric("Assemblies", len(getattr(bundle, "assemblies", ())))}
{_metric("Unresolved warnings", len(bundle.warnings))}
</div>
<h2>Summary</h2><pre>{json.dumps(summary, indent=2)}</pre>
<p><a href="previews/classification.png">Classification preview</a> | <a href="previews/manual_review_handles.png">Entity handle preview</a> | <a href="project.sqlite">SQLite database</a></p>
<h2>Stages</h2><div class="stages">{cards}</div>
</body></html>"""


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
        "method": station.method,
        "confidence": station.confidence,
        "evidence": _jsonable(station.evidence),
    }


def _sequences(stations: tuple[StationRecord, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for station in stations:
        key = f"sequence_{_sequence_id(station):02d}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stage_title(station: StationRecord, profiles: tuple[ProfileRecord, ...], rollers: tuple[RollerOccurrenceRecord, ...]) -> str:
    return (
        f"Sequence {_sequence_id(station):02d} Stage {station.sequence_index:02d} "
        f"{_region_type(station)} "
        f"stage_conf={station.confidence:.2f} profile={max((p.confidence for p in profiles), default=0):.2f} "
        f"rollers={len(rollers)}"
    )


def _roller_handles(rollers: tuple[RollerOccurrenceRecord, ...], token: str) -> tuple[str, ...]:
    return tuple(
        handle
        for roller in rollers
        if token in str(roller.role or roller.evidence.get("candidate_role") or "")
        for handle in roller.source_handles
    )


def _metric(label: str, value: int) -> str:
    return f'<div class="metric"><strong>{value}</strong><br>{label}</div>'


def _stage_card(bundle: ExtractionBundle, station: StationRecord) -> str:
    station_dir = _station_dir_name(station, bundle.stations)
    profiles = [profile for profile in bundle.profiles if profile.station_id == station.station_id]
    rollers = [roller for roller in bundle.roller_occurrences if roller.station_id == station.station_id]
    status_class = "confirmed" if station.evidence.get("confirmed") else "candidate"
    dxf_links = _stage_links(station_dir, bool(profiles), bool(rollers), _region_type(station) == "COMPOSITE_FLOWER")
    return (
        f'<div class="stage"><h3>Sequence {_sequence_id(station):02d} Stage {station.sequence_index:02d}</h3>'
        f'<p><strong>{_region_type(station)}</strong> '
        f'<span class="{status_class}">{station.evidence.get("confirmation_status", "candidate")}</span></p>'
        f'<p>Stage confidence {station.confidence:.2f}. Profiles {len(profiles)}. Roller candidates {len(rollers)}.</p>'
        f'<a href="stations/{station_dir}/review.png"><img src="stations/{station_dir}/review.png" alt="stage review"></a>'
        f'<p>{dxf_links}</p></div>'
    )


def _stage_links(station_dir: str, has_profile: bool, has_rollers: bool, composite: bool = False) -> str:
    names = ["review.png"]
    if composite and has_profile:
        names.append("composite_passes/passes.json")
    else:
        names.append("profile.dxf" if has_profile else "profile_not_detected.json")
    if has_rollers:
        names.append("rollers.csv")
    return " ".join(f'<a href="stations/{station_dir}/{name}">{name}</a>' for name in names)


def _summary(bundle: ExtractionBundle, warnings: tuple[WarningRecord, ...]) -> dict[str, Any]:
    stage_counts: dict[str, int] = {}
    profile_states: dict[str, int] = {}
    for station in bundle.stations:
        region_type = _region_type(station)
        stage_counts[region_type] = stage_counts.get(region_type, 0) + 1
    for profile in bundle.profiles:
        state = str(profile.features.get("profile_state", "UNCLASSIFIED"))
        profile_states[state] = profile_states.get(state, 0) + 1
    confirmed_rollers = [roller for roller in bundle.roller_occurrences if roller.role and roller.confidence >= 0.65]
    candidate_rollers = [roller for roller in bundle.roller_occurrences if not (roller.role and roller.confidence >= 0.65)]
    return {
        "detected_drawing_sequences": _sequences(bundle.stations),
        "profile_states": profile_states,
        "actual_tooling_stations": sum(1 for station in bundle.stations if station.evidence.get("machine_tooling_station")),
        "roller_detail_drawings": stage_counts.get("ROLLER_DETAIL", 0),
        "composite_flowers": stage_counts.get("COMPOSITE_FLOWER", 0),
        "reference_geometries": stage_counts.get("REFERENCE_GEOMETRY", 0),
        "final_profiles": stage_counts.get("FINAL_PROFILE", 0),
        "confirmed_rollers": len(confirmed_rollers),
        "candidate_rollers": len(candidate_rollers),
        "confirmed_assemblies": len(getattr(bundle, "assemblies", ())),
        "unresolved_warnings": len(warnings),
    }


def _region_type(station: StationRecord) -> str:
    return str(station.evidence.get("region_type") or station.evidence.get("stage_type") or "UNKNOWN")


def _sequence_id(station: StationRecord) -> int:
    try:
        return int(station.evidence.get("sequence_id") or 1)
    except (TypeError, ValueError):
        return 1


def _station_dir_name(station: StationRecord, stations: tuple[StationRecord, ...]) -> str:
    multi_sequence = len({_sequence_id(other) for other in stations}) > 1
    if multi_sequence:
        return f"sequence_{_sequence_id(station):02d}_station_{station.sequence_index:02d}"
    return f"station_{station.sequence_index:02d}"


def _profile(profile: ProfileRecord) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "station_id": profile.station_id,
        "source_handles": list(profile.source_handles),
        "method": profile.method,
        "confidence": profile.confidence,
        "features": _jsonable(profile.features),
    }


def _roller(roller: RollerOccurrenceRecord) -> dict[str, Any]:
    return {
        "occurrence_id": roller.occurrence_id,
        "station_id": roller.station_id,
        "role": roller.role,
        "source_handles": list(roller.source_handles),
        "method": roller.method,
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
    if is_dataclass(value):
        return _jsonable(vars(value))
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
