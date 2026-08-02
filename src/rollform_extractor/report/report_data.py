from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord, RollerOccurrenceRecord, StationRecord, WarningRecord
from rollform_extractor.transition_analysis import bend_change_events, profile_step_changes, segment_change_events
from rollform_extractor.pass_features import PASS_FEATURE_SCHEMA_VERSION, FeatureKey
from rollform_extractor.pass_alignment import align_passes_to_stations, build_alignment_candidates


def build_report_data(bundle: ExtractionBundle, project_path: Path, warnings: tuple[WarningRecord, ...]) -> dict[str, Any]:
    stations = tuple(sorted(bundle.stations, key=lambda item: (_sequence_id(item), item.sequence_index or 0, item.station_id)))
    profiles_by_station = {
        station.station_id: tuple(profile for profile in bundle.profiles if profile.station_id == station.station_id)
        for station in stations
    }
    rollers_by_station = {
        station.station_id: tuple(roller for roller in bundle.roller_occurrences if roller.station_id == station.station_id)
        for station in stations
    }
    return {
        "project": {
            "drawing_id": bundle.drawing_id,
            "source_path": str(bundle.source_path),
            "status": bundle.status,
            "engineering_status": "Candidate extraction - not approved for production use",
            "units": bundle.configuration_snapshot.get("units", {}),
            "validation_status": "valid",
            "confirmed_assemblies": len(getattr(bundle, "assemblies", ())),
            "confirmed_transitions": len(getattr(bundle, "transitions", ())),
            "feature_summary": _feature_summary(bundle),
        },
        "manual_review_decisions": _latest_review_decisions(project_path),
        "sequences": _individual_sequences(stations, profiles_by_station, rollers_by_station, project_path),
        "composite_flowers": [
            _composite_flower(composite, project_path, getattr(bundle, "pass_features", {}))
            for composite in getattr(bundle, "composite_flowers", ())
        ],
        "rejected_composite_regions": [_jsonable(region) for region in getattr(bundle, "rejected_composite_regions", ())],
        "stages": [_stage(station, profiles_by_station[station.station_id], rollers_by_station[station.station_id], project_path, stations) for station in stations],
        "roller_candidates": [_roller(roller) for roller in bundle.roller_occurrences],
        "assemblies": [_jsonable(assembly) for assembly in getattr(bundle, "assemblies", ())],
        "transitions": [_jsonable(transition) for transition in getattr(bundle, "transitions", ())],
        "warnings": [_warning(warning) for warning in warnings],
    }


def _latest_review_decisions(project_path: Path) -> dict[str, Any]:
    review_dir = project_path / "review"
    candidates = sorted(review_dir.glob("applied_review*.json")) if review_dir.exists() else []
    if not candidates:
        return {}
    try:
        value = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _individual_sequences(stations, profiles_by_station, rollers_by_station, project_path: Path) -> list[dict[str, Any]]:
    sequences: dict[int, list[dict[str, Any]]] = {}
    all_stations = tuple(stations)
    for station in stations:
        sequences.setdefault(_sequence_id(station), []).append(_stage(station, profiles_by_station[station.station_id], rollers_by_station[station.station_id], project_path, all_stations))
    return [
        {
            "sequence_id": f"sequence_{sequence_id:02d}",
            "label": f"Sequence {sequence_id:02d}",
            "steps": steps,
        }
        for sequence_id, steps in sorted(sequences.items())
    ]


def _composite_flower(composite, project_path: Path, pass_features: Mapping[FeatureKey, Any] | None = None) -> dict[str, Any]:
    root = Path("composite_flowers") / composite.composite_flower_id
    pass_features = pass_features or {}
    passes = [_composite_pass(item, root / "passes" / item.pass_id, project_path, pass_features.get((composite.composite_flower_id, item.pass_id))) for item in composite.passes]
    return {
        "composite_flower_id": composite.composite_flower_id,
        "label": _title(composite.composite_flower_id),
        "source_region_id": composite.source_region_id,
        "pass_count": composite.pass_count,
        "sequence_confidence": composite.sequence_confidence,
        "confirmed": composite.confirmed,
        "status": "Engineer confirmed" if composite.confirmed else "Candidate",
        "requires_review": any(item["requires_review"] for item in passes),
        "source_bbox": _bbox(composite.source_bbox),
        "passes": passes,
        "bend_progression": _bend_progression(passes),
        "developed_length_progression": _developed_length_progression(passes),
        "station_alignment": _station_alignment(passes),
        "profile_step_changes": [_jsonable(change) for change in profile_step_changes(composite.passes)],
        "bend_change_events": [_jsonable(event) for event in bend_change_events(composite.passes)],
        "segment_change_events": [_jsonable(event) for event in segment_change_events(composite.passes)],
        "downloads": _existing_links(project_path, root, {
            "complete_composite_flower_dxf": "complete_composite_flower.dxf",
            "overlaid_reconstruction_dxf": "overlaid_reconstruction.dxf",
            "sequence_csv": "sequence.csv",
            "sequence_preview_png": "sequence_preview.png",
            "overlaid_reconstruction_png": "overlaid_reconstruction.png",
            "extraction_debug_png": "extraction_debug.png",
            "extraction_summary_json": "extraction_summary.json",
        }),
    }


def _composite_pass(item, pass_root: Path, project_path: Path, feature=None) -> dict[str, Any]:
    downloads = _existing_links(project_path, pass_root, {
        "profile_dxf": "profile.dxf",
        "profile_original_coordinates_dxf": "profile_original_coordinates.dxf",
        "profile_normalized_dxf": "profile_normalized.dxf",
        "profile_json": "profile.json",
        "profile_png": "profile.png",
        "profile_original_coordinates_png": "profile_original_coordinates.png",
        "profile_normalized_png": "profile_normalized.png",
        "profile_outline_dxf": "profile_outline.dxf",
        "profile_neutral_line_dxf": "profile_neutral_line.dxf",
        "profile_outline_png": "profile_outline.png",
        "profile_neutral_line_png": "profile_neutral_line.png",
        "profile_geometry_json": "profile_geometry.json",
        "source_entities_json": "source_entities.json",
        "transform_json": "transform.json",
        "pass_features_json": "pass_features.json",
        "pass_feature_vector_json": "pass_feature_vector.json",
        "segments_csv": "segments.csv",
        "bend_features_csv": "bend_features.csv",
    })
    return {
        "kind": "composite_pass",
        "sequence_id": item.composite_flower_id,
        "pass_id": item.pass_id,
        "name": _pass_label(item),
        "profile_id": item.profile_id,
        "station_id": item.station_id,
        "inferred_order": item.inferred_order,
        "engineer_confirmed_order": item.confirmed_order,
        "profile_type": item.profile_type,
        "status": "Engineer confirmed" if item.confirmed_order is not None else "Candidate",
        "tooling_link_status": "Tooling unlinked",
        "confidence": item.confidence,
        "contour_confidence": item.confidence,
        "order_confidence": item.order_confidence,
        "requires_review": item.requires_review,
        "source_handles": list(item.source_handles),
        "source_layers": list(item.source_layers),
        "developed_length_drawing_units": item.developed_length,
        "developed_length_mm": None,
        "outline_perimeter_drawing_units": (feature.geometry.contour.get("perimeter") if feature is not None else None),
        "outline_perimeter_mm": (feature.geometry.contour.get("perimeter_mm") if feature is not None else None),
        "generated_neutral_developed_length_drawing_units": item.neutral_line_developed_length,
        "generated_neutral_developed_length_mm": None,
        "expected_neutral_developed_length_drawing_units": item.expected_neutral_length,
        "expected_neutral_developed_length_mm": None,
        "neutral_length_error_drawing_units": item.neutral_length_error,
        "neutral_length_error_mm": None,
        "expected_neutral_length": item.expected_neutral_length,
        "generated_neutral_length": item.neutral_line_developed_length,
        "neutral_length_error": item.neutral_length_error,
        "neutral_length_error_percent": item.neutral_length_error_percent,
        "neutral_length_status": _neutral_length_status(item.neutral_length_error_percent),
        "width": item.width,
        "height": item.height,
        "bend_count": item.physical_forming_bend_count,
        "total_bend_angle": item.physical_total_bend_angle,
        "sheet_thickness_drawing_units": item.sheet_thickness,
        "sheet_thickness": {
            "value": item.sheet_thickness,
            "calculation_method": item.thickness_method,
            "sampling_count": item.thickness_sampling_count,
            "variation": item.thickness_variation,
            "confidence": item.thickness_confidence,
            "engineer_confirmed_value": item.engineer_confirmed_thickness,
        },
        "neutral_line_method": item.neutral_line_method,
        "neutral_line_confidence": item.neutral_line_confidence,
        "neutral_line_developed_length": item.neutral_line_developed_length,
        "physical_bends": [_jsonable(bend) for bend in item.physical_bends],
        "bend_zones": [_jsonable(bend) for bend in item.physical_bends],
        "active_bend_count": item.active_bend_count,
        "bend_signature": item.bend_signature,
        "vertex_turn_count": item.vertex_turn_count,
        "physical_forming_bend_count": item.physical_forming_bend_count,
        "physical_total_bend_angle": item.physical_total_bend_angle,
        "raw_geometry_corner_count": item.raw_geometry_corner_count,
        "raw_total_turning_angle": item.raw_total_turning_angle,
        "duplicate_group_id": item.duplicate_group_id,
        "duplicate_of": item.duplicate_of,
        "transform_matrix_4x4": item.transform_matrix_4x4,
        "individual_profile_matches": [_jsonable(match) for match in item.individual_profile_matches],
        "features": feature.to_dict() if feature is not None else None,
        "feature_quality": _jsonable(feature.quality) if feature is not None else None,
        "feature_schema_version": feature.schema_version if feature is not None else None,
        "feature_vector_length": len(feature.full_vector.values) if feature is not None else 0,
        "fingerprints": _jsonable(feature.fingerprints) if feature is not None else {},
        "feature_downloads": {key: downloads.get(key) for key in ("pass_features_json", "pass_feature_vector_json", "segments_csv", "bend_features_csv")},
        "downloads": downloads,
        "preview_path": downloads.get("profile_png"),
        "original_preview_path": downloads.get("profile_original_coordinates_png") or downloads.get("profile_png"),
        "normalized_preview_path": downloads.get("profile_normalized_png") or downloads.get("profile_png"),
        "outline_preview_path": downloads.get("profile_outline_png") or downloads.get("profile_png"),
        "neutral_line_preview_path": downloads.get("profile_neutral_line_png") or downloads.get("profile_png"),
        "normalized_dxf_path": downloads.get("profile_normalized_dxf"),
    }


def _neutral_length_status(percent: float | None) -> str:
    if percent is None:
        return "UNKNOWN"
    return "REVIEW_REQUIRED" if abs(percent) > 0.2 else "CONSISTENT"


def _bend_progression(passes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bend_ids = sorted({bend["bend_id"] for item in passes for bend in item.get("physical_bends", ())})
    return [
        {
            "composite_flower_id": item["sequence_id"],
            "bend_id": bend_id,
            "pass_id": item["pass_id"],
            "pass_order": item["inferred_order"],
            "developed_position": (bend or {}).get("developed_length_position"),
            "signed_angle": (bend or {}).get("signed_bend_angle", 0.0),
            "radius": (bend or {}).get("neutral_line_radius"),
            "activation_status": (bend or {}).get("activation_status", "inactive"),
            "confidence": (bend or {}).get("confidence", 0.0),
            "engineer_confirmed": False,
        }
        for bend_id in bend_ids
        for item in passes
        for bend in (next((candidate for candidate in item.get("physical_bends", ()) if candidate["bend_id"] == bend_id), None),)
    ]


def _developed_length_progression(passes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lengths = [float(item.get("developed_length_drawing_units") or 0.0) for item in passes]
    median = sorted(lengths)[len(lengths) // 2] if lengths else 0.0
    rows = []
    previous = None
    for item, length in zip(passes, lengths):
        percent = None if not median else abs(length - median) / median * 100.0
        rows.append(
            {
                "pass_id": item["pass_id"],
                "pass_order": item["inferred_order"],
                "developed_length_drawing_units": length,
                "change_from_previous": None if previous is None else length - previous,
                "variation_from_median_percent": percent,
                "classification": _length_classification(percent),
            }
        )
        previous = length
    return rows


def _length_classification(percent: float | None) -> str:
    if percent is None or percent <= 0.25:
        return "CONSISTENT"
    if percent <= 1.0:
        return "MINOR_VARIATION"
    if percent <= 5.0:
        return "REVIEW_REQUIRED"
    return "INVALID"


def _station_alignment(passes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = []
    for item in passes:
        for match in item.get("individual_profile_matches", ()):
            if match.get("candidate_station_id"):
                raw.append({**match, "composite_flower_id": item["sequence_id"], "pass_id": item["pass_id"], "profile_id": item.get("profile_id"), "pass_order": item.get("inferred_order", 0)})
    station_ids = sorted(
        [row["candidate_station_id"] for row in raw if row.get("candidate_station_id")],
        key=lambda station: (_station_sort_key(station), station),
    )
    index_by_station = {station: index for index, station in enumerate(dict.fromkeys(station_ids))}
    candidates = build_alignment_candidates([{**row, "candidate_station_order": index_by_station[row["candidate_station_id"]]} for row in raw])
    result = align_passes_to_stations([item["pass_id"] for item in passes], station_ids, candidates, minimum_pair_score=0.0)
    by_pass = {candidate.pass_id: candidate for candidate in result.matches}
    rows = []
    for item in passes:
        match = by_pass.get(item["pass_id"])
        if match is None:
            rows.append(_unmatched_alignment(item))
            continue
        rows.append({
            "composite_pass_id": item["pass_id"],
            "individual_profile_id": match.candidate_profile_id,
            "sequence_id": match.candidate_sequence_id,
            "drawing_stage_id": match.candidate_station_id,
            "inferred_station_order": match.candidate_station_order,
            "similarity_score": match.score,
            "contour_difference": 1.0 - match.score,
            "bend_signature_difference": match.bend_signature_difference,
            "developed_length_difference": match.developed_length_difference,
            "link_status": "EXACT_CANDIDATE" if match.score >= 0.995 else "SIMILAR_CANDIDATE",
            "engineer_confirmed": False,
            "alignment_status": result.status,
        })
    return rows


def _station_sort_key(station_id: str) -> tuple[int, str]:
    try:
        return int(str(station_id).rsplit("_S", 1)[1]), str(station_id)
    except (IndexError, ValueError):
        return (10**9, str(station_id))


def _unmatched_alignment(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "composite_pass_id": item["pass_id"],
        "individual_profile_id": None,
        "sequence_id": item["sequence_id"],
        "drawing_stage_id": None,
        "inferred_station_order": None,
        "similarity_score": None,
        "contour_difference": None,
        "bend_signature_difference": None,
        "developed_length_difference": None,
        "link_status": "UNMATCHED",
        "engineer_confirmed": False,
    }


def _stage(station: StationRecord, profiles: tuple[ProfileRecord, ...], rollers: tuple[RollerOccurrenceRecord, ...], project_path: Path, stations: tuple[StationRecord, ...]) -> dict[str, Any]:
    station_dir = Path("stations") / _station_dir_name(station, stations)
    profile = profiles[0] if profiles else None
    return {
        "kind": "stage",
        "stage_id": station.station_id,
        "sequence_id": f"sequence_{_sequence_id(station):02d}",
        "name": f"Stage {station.sequence_index:02d}",
        "sequence_index": station.sequence_index,
        "region_type": _region_type(station),
        "status": "Engineer confirmed" if station.evidence.get("confirmed") else "Candidate",
        "confidence": station.confidence,
        "requires_review": not bool(station.evidence.get("confirmed")),
        "profile_id": profile.profile_id if profile else None,
        "profile_type": str(profile.features.get("profile_state", "UNCLASSIFIED")) if profile else "UNCLASSIFIED",
        "width": _feature(profile, "width_drawing_units"),
        "height": _feature(profile, "height_drawing_units"),
        "developed_length_drawing_units": _feature(profile, "developed_length_drawing_units") or _feature(profile, "exact_length"),
        "bend_count": len(tuple(profile.features.get("bend_angles", ()))) if profile else 0,
        "roller_candidate_count": len(rollers),
        "tooling_link_status": "Tooling candidate" if rollers else "Tooling unlinked",
        "downloads": _existing_links(project_path, station_dir, {"profile_dxf": "profile.dxf", "profile_json": "profile_not_detected.json", "review_png": "review.png", "rollers_csv": "rollers.csv"}),
    }


def _roller(roller: RollerOccurrenceRecord) -> dict[str, Any]:
    return {
        "occurrence_id": roller.occurrence_id,
        "station_id": roller.station_id,
        "role": roller.role,
        "status": "Tooling confirmed" if roller.role and roller.confidence >= 0.65 else "Tooling candidate",
        "confidence": roller.confidence,
        "source_handles": list(roller.source_handles),
        "evidence": _jsonable(roller.evidence),
    }


def _warning(warning: WarningRecord) -> dict[str, Any]:
    return {
        "code": warning.code,
        "message": warning.message,
        "source_handles": list(warning.source_handles),
        "method": warning.method,
        "confidence": warning.confidence,
    }


def _existing_links(project_path: Path, root: Path, names: Mapping[str, str]) -> dict[str, str | None]:
    return {
        key: str(root / filename) if (project_path / root / filename).exists() else None
        for key, filename in names.items()
    }


def _pass_label(item) -> str:
    if item.inferred_order == 0:
        return "Flat Strip"
    if str(item.pass_id).endswith("_final"):
        return "Final Profile"
    return f"Pass {item.inferred_order:02d}"


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def _feature(profile: ProfileRecord | None, name: str) -> Any:
    return profile.features.get(name) if profile else None


def _region_type(station: StationRecord) -> str:
    return str(station.evidence.get("region_type") or station.evidence.get("stage_type") or "UNKNOWN")


def _sequence_id(station: StationRecord) -> int:
    try:
        return int(station.evidence.get("sequence_id") or 1)
    except (TypeError, ValueError):
        return 1


def _station_dir_name(station: StationRecord, stations: tuple[StationRecord, ...]) -> str:
    if len({_sequence_id(other) for other in stations}) > 1:
        return f"sequence_{_sequence_id(station):02d}_station_{station.sequence_index:02d}"
    return f"station_{station.sequence_index:02d}"


def _bbox(bbox: BBox | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {"min_x": bbox.min_x, "min_y": bbox.min_y, "max_x": bbox.max_x, "max_y": bbox.max_y}


def _jsonable(value: Any) -> Any:
    if isinstance(value, CadPrimitive):
        return {"kind": value.kind, "attributes": _jsonable(value.attributes), "source_handle": value.source_handle}
    if isinstance(value, BBox):
        return _bbox(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return value


def _feature_summary(bundle: ExtractionBundle) -> dict[str, Any]:
    features = tuple(getattr(bundle, "pass_features", {}).values())
    scalar_lengths = {len(item.scalar_vector.values) for item in features}
    shape_lengths = {len(item.shape_vector.values) for item in features}
    full_lengths = {len(item.full_vector.values) for item in features}
    return {
        "feature_set_count": len(features),
        "feature_schema_version": PASS_FEATURE_SCHEMA_VERSION,
        "scalar_vector_length": next(iter(scalar_lengths), 0),
        "shape_vector_length": next(iter(shape_lengths), 0),
        "full_vector_length": next(iter(full_lengths), 0),
        "passes_with_warnings": sum(bool(item.quality.flags) for item in features),
        "passes_with_unconfirmed_units": sum(item.quality.units_status != "CONFIRMED" for item in features),
    }
