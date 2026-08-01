"""Deterministic Phase 15 pass-feature extraction.

The feature layer deliberately consumes ``CompositeFlowerPass``.  CAD
primitives and the existing canonical bend zones remain authoritative; the
values here are derived descriptors for search, comparison, and review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import Polygon

from rollform_extractor.composite_flower import CompositeFlowerPass, CompositeFlowerRecord
from rollform_extractor.config import FeaturesConfig


PASS_FEATURE_SCHEMA_VERSION = 1

SCALAR_FEATURE_FIELDS = (
    "bbox_min_x", "bbox_min_y", "bbox_max_x", "bbox_max_y", "width", "height",
    "bbox_area", "bbox_perimeter", "aspect_ratio", "bbox_diagonal", "bbox_center_x", "bbox_center_y",
    "outline_area", "outline_perimeter", "polygon_centroid_x", "polygon_centroid_y", "convex_hull_area",
    "convex_hull_perimeter", "solidity", "compactness", "number_of_holes", "neutral_line_developed_length",
    "expected_neutral_length", "absolute_neutral_length_error", "neutral_length_error_percent",
    "neutral_point_count", "chord_length", "tortuosity", "maximum_distance_from_chord", "rms_distance_from_chord",
    "neutral_centroid_x", "neutral_centroid_y", "start_tangent_angle", "end_tangent_angle", "net_profile_rotation",
    "maximum_local_curvature", "mean_absolute_curvature", "curvature_stddev", "segment_count", "min_segment_length",
    "max_segment_length", "mean_segment_length", "segment_length_stddev", "longest_segment_ratio", "active_bend_count",
    "positive_bend_count", "negative_bend_count", "total_absolute_bend_angle", "total_signed_bend_angle",
    "maximum_absolute_bend_angle", "mean_absolute_bend_angle", "bend_angle_stddev", "minimum_bend_radius",
    "mean_bend_radius", "minimum_radius_to_thickness", "mean_radius_to_thickness", "bend_density",
    "total_angle_per_length", "alternating_bend_direction_count", "sheet_thickness", "thickness_variation",
    "thickness_confidence", "flat_material_fraction", "curved_material_fraction", "edge_height_left",
    "edge_height_right", "edge_height_difference", "maximum_profile_height", "width_to_developed_length",
    "height_to_developed_length", "symmetry_score", "vertical_symmetry_score", "horizontal_symmetry_score",
    "formedness_index", "geometry_quality_score", "feature_confidence", "width_delta_previous", "height_delta_previous",
    "developed_length_delta_previous", "total_bend_angle_delta_previous", "active_bend_count_delta_previous",
    "maximum_material_point_displacement", "mean_contour_displacement", "centroid_movement_previous",
    "newly_activated_bend_count", "deactivated_bend_count", "radius_tightening_count", "radius_opening_count",
    "segment_change_count", "progress_ratio", "width_ratio_final", "height_ratio_final", "bend_angle_ratio_final",
    "formedness_ratio_final",
)


@dataclass(frozen=True)
class FeatureProvenance:
    source_handles: tuple[str, ...]
    calculation_method: str
    software_version: str
    configuration_hash: str


@dataclass(frozen=True)
class FeatureQuality:
    confidence: float
    flags: tuple[str, ...]
    units_status: str
    review_required: bool
    valid: bool = True


@dataclass(frozen=True)
class FeatureVector:
    field_names: tuple[str, ...]
    values: tuple[float, ...]
    missing_mask: tuple[bool, ...]
    schema_version: int
    normalization_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class SegmentFeature:
    segment_id: str
    segment_index: int
    start_u: float
    end_u: float
    start_developed_coordinate: float
    end_developed_coordinate: float
    length: float
    normalized_length: float | None
    start_point: tuple[float, float, float]
    end_point: tuple[float, float, float]
    orientation_angle: float | None
    absolute_orientation: float | None
    chord_length: float
    tortuosity: float | None
    mean_curvature: float | None
    maximum_curvature: float | None
    segment_type: str
    previous_bend_id: str | None
    next_bend_id: str | None
    connectivity: str
    source_handles: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class GeometryFeatures:
    bbox: Mapping[str, float]
    contour: Mapping[str, Any]
    neutral_line: Mapping[str, Any]
    symmetry: Mapping[str, Any]


@dataclass(frozen=True)
class ManufacturingFeatures:
    values: Mapping[str, Any]


@dataclass(frozen=True)
class SequenceFeatures:
    values: Mapping[str, Any]
    bend_history: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class PassFeatureSet:
    schema_version: int
    drawing_id: str
    composite_flower_id: str
    pass_id: str
    profile_id: str
    station_id: str
    inferred_pass_order: int
    confirmed_pass_order: int | None
    configuration_hash: str
    source_handles: tuple[str, ...]
    provenance: FeatureProvenance
    quality: FeatureQuality
    geometry: GeometryFeatures
    segments: tuple[SegmentFeature, ...]
    bends: tuple[Mapping[str, Any], ...]
    manufacturing: ManufacturingFeatures
    sequence: SequenceFeatures
    scalar_vector: FeatureVector
    shape_vector: FeatureVector
    full_vector: FeatureVector
    fingerprints: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def extract_composite_pass_features(
    drawing_id: str,
    composite: CompositeFlowerRecord,
    configuration_hash: str,
    features_config: FeaturesConfig,
    units: Mapping[str, Any] | None = None,
) -> dict[str, PassFeatureSet]:
    """Extract all pass features, with sequence-relative values in one pass."""
    ordered = tuple(sorted(composite.passes, key=lambda item: item.inferred_order))
    units = units or {}
    rows: dict[str, PassFeatureSet] = {}
    previous: PassFeatureSet | None = None
    first: PassFeatureSet | None = None
    for item in ordered:
        previous_item = ordered[item.inferred_order - 1] if item.inferred_order > 0 and item.inferred_order - 1 < len(ordered) else None
        current = _extract_one(drawing_id, composite.composite_flower_id, item, configuration_hash, features_config, units, previous, first, None, previous_item)
        rows[item.pass_id] = current
        first = first or current
        previous = current
    final = previous
    if final is not None:
        for item in ordered:
            if item.pass_id not in rows:
                continue
            previous_item = ordered[item.inferred_order - 1] if item.inferred_order > 0 and item.inferred_order - 1 < len(ordered) else None
            previous_features = rows.get(previous_item.pass_id) if previous_item else None
            rows[item.pass_id] = _extract_one(drawing_id, composite.composite_flower_id, item, configuration_hash, features_config, units, previous_features, rows.get(ordered[0].pass_id), final, previous_item)
    histories = _bend_histories(ordered)
    for item in ordered:
        row = rows[item.pass_id]
        sequence = SequenceFeatures(row.sequence.values, tuple(histories.get(str(b.get("bend_id")), {}) for b in item.physical_bends))
        rows[item.pass_id] = _replace_sequence(row, sequence)
    return rows


def _replace_sequence(row: PassFeatureSet, sequence: SequenceFeatures) -> PassFeatureSet:
    return replace(row, sequence=sequence)


def _extract_one(drawing_id, flower_id, item, config_hash, cfg, units, previous, first, final, previous_item=None):
    points = _clean_points(item.neutral_line_points)
    flags: list[str] = []
    unit_status = "CONFIRMED" if units.get("confirmed") else "UNCONFIRMED"
    if unit_status != "CONFIRMED":
        flags.append("UNCONFIRMED_UNITS")
    bbox = _bbox(points, item)
    outline = _outline_features(item)
    if outline["area"] is None:
        flags.append("OPEN_PROFILE_AREA_UNAVAILABLE")
    neutral = _neutral_features(points, item, flags)
    normalized = _normalized_shape(points, cfg.material_sample_count, cfg.mirror_canonicalization, cfg.vector_rounding_decimals, cfg.minimum_path_length)
    segments = _segments(points, item.physical_bends, neutral["developed_length"], cfg.straight_angle_tolerance_deg)
    bends = _bend_features(item.physical_bends, item.sheet_thickness, neutral["developed_length"])
    symmetry = _symmetry(normalized["physical_points"], item.physical_bends, cfg.symmetry_tolerance)
    manufacturing = _manufacturing(item, neutral, outline, segments, bends, symmetry, previous, final)
    sequence = _sequence_features(item, previous, first, final, previous_item)
    scalar_values = _scalar_values(bbox, outline, neutral, segments, bends, manufacturing, symmetry, sequence)
    scalar = _vector(SCALAR_FEATURE_FIELDS, scalar_values, cfg.vector_rounding_decimals, {"units_status": unit_status})
    shape_names = tuple(f"{axis}_{index:03d}" for index in range(cfg.material_sample_count) for axis in ("x", "y"))
    shape_values = tuple(value for point in normalized["normalized_points"] for value in point[:2])
    shape = _vector(shape_names, dict(zip(shape_names, shape_values)), cfg.vector_rounding_decimals, normalized["metadata"])
    full_names = SCALAR_FEATURE_FIELDS + shape_names
    full_values = scalar.values + shape.values
    full_mask = scalar.missing_mask + shape.missing_mask
    full = FeatureVector(full_names, full_values, full_mask, PASS_FEATURE_SCHEMA_VERSION, {**scalar.normalization_metadata, **normalized["metadata"]})
    fingerprints = _fingerprints(item, neutral, normalized, bends, cfg.vector_rounding_decimals)
    confidence = min(float(item.confidence), float(item.neutral_line_confidence), max(float(item.thickness_confidence), 0.35))
    quality = FeatureQuality(max(0.0, min(1.0, confidence)), tuple(sorted(set(flags))), unit_status, bool(item.requires_review or flags))
    provenance = FeatureProvenance(tuple(item.source_handles), "composite_pass_neutral_line_v1", "rollform-extractor/0.1.0", config_hash)
    return PassFeatureSet(PASS_FEATURE_SCHEMA_VERSION, drawing_id, flower_id, item.pass_id, item.profile_id, item.station_id, item.inferred_order, item.confirmed_order, config_hash, tuple(item.source_handles), provenance, quality, GeometryFeatures(bbox, outline, neutral | {"normalized_shape": normalized["metadata"]}, symmetry), tuple(segments), tuple(bends), ManufacturingFeatures(manufacturing), SequenceFeatures(sequence, ()), scalar, shape, full, fingerprints)


def _bbox(points, item):
    if points:
        xs, ys = zip(*[(point[0], point[1]) for point in points])
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    else:
        min_x = min_y = max_x = max_y = 0.0
    width, height = max_x - min_x, max_y - min_y
    return {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y, "width": width, "height": height, "area": width * height, "perimeter": 2 * (width + height), "aspect_ratio": _safe_ratio(width, height), "diagonal": math.hypot(width, height), "center_x": (min_x + max_x) / 2, "center_y": (min_y + max_y) / 2}


def _outline_features(item):
    candidates = []
    for primitive in tuple(item.profile.features.get("normalized_primitives", ())) + tuple(item.profile.features.get("original_primitives", ())):
        attrs = primitive.attributes
        if primitive.kind in {"LWPOLYLINE", "POLYLINE"} and attrs.get("closed"):
            points = _clean_points(tuple(_point(v.get("point", v)) if isinstance(v, Mapping) else _point(v) for v in attrs.get("vertices", attrs.get("points", ()))))
            if len(points) >= 3:
                candidates.append(points)
    if not candidates:
        return {"area": None, "perimeter": None, "centroid_x": None, "centroid_y": None, "convex_hull_area": None, "convex_hull_perimeter": None, "solidity": None, "compactness": None, "number_of_holes": None, "validity": "OPEN_OR_UNAVAILABLE"}
    points = max(candidates, key=_path_length)
    polygon = Polygon([(point[0], point[1]) for point in points])
    if not polygon.is_valid or polygon.area <= 0:
        return {"area": None, "perimeter": None, "centroid_x": None, "centroid_y": None, "convex_hull_area": None, "convex_hull_perimeter": None, "solidity": None, "compactness": None, "number_of_holes": 0, "validity": "INVALID"}
    hull = polygon.convex_hull
    area = float(polygon.area)
    perimeter = float(polygon.length)
    return {"area": area, "perimeter": perimeter, "centroid_x": float(polygon.centroid.x), "centroid_y": float(polygon.centroid.y), "convex_hull_area": float(hull.area), "convex_hull_perimeter": float(hull.length), "solidity": _safe_ratio(area, float(hull.area)), "compactness": _safe_ratio(4 * math.pi * area, perimeter * perimeter), "number_of_holes": len(polygon.interiors), "validity": "VALID"}


def _neutral_features(points, item, flags):
    cumulative = _cumulative(points)
    length = _finite(item.neutral_line_developed_length) or (cumulative[-1] if cumulative else 0.0)
    expected = item.expected_neutral_length
    error = (length - expected) if expected is not None else item.neutral_length_error
    chord = _distance(points[0], points[-1]) if len(points) > 1 else 0.0
    distances = _chord_distances(points)
    curvature = _curvatures(points)
    centroid = _weighted_centroid(points, cumulative)
    start_angle = _tangent(points, True)
    end_angle = _tangent(points, False)
    return {"developed_length": _finite(length), "expected_neutral_length": _finite(expected), "absolute_error": abs(error) if error is not None else None, "error_percent": abs(error) / abs(expected) * 100 if error is not None and expected else item.neutral_length_error_percent, "point_count": len(points), "chord_length": chord, "tortuosity": _safe_ratio(length, chord), "maximum_distance_from_chord": max(distances) if distances else 0.0, "rms_distance_from_chord": math.sqrt(mean(d * d for d in distances)) if distances else 0.0, "centroid_x": centroid[0], "centroid_y": centroid[1], "start_tangent_angle": start_angle, "end_tangent_angle": end_angle, "net_profile_rotation": _angle_delta(start_angle, end_angle), "maximum_local_curvature": max(curvature) if curvature else 0.0, "mean_absolute_curvature": mean(curvature) if curvature else 0.0, "curvature_stddev": pstdev(curvature) if len(curvature) > 1 else 0.0, "sampled_points": points}


def _segments(points, bends, total, tolerance):
    if len(points) < 2 or total <= 0:
        return ()
    bend_rows = sorted(bends, key=lambda bend: float(bend.get("u", 0.0)))
    cuts = [0.0] + [float(bend.get("u", 0.0)) for bend in bend_rows] + [1.0]
    cumulative = _cumulative(points)
    result = []
    for index, (start_u, end_u) in enumerate(zip(cuts, cuts[1:]), start=1):
        start = _point_at(points, cumulative, start_u * total)
        end = _point_at(points, cumulative, end_u * total)
        sub = tuple(point for point, s in zip(points, cumulative) if start_u * total <= s <= end_u * total) or (start, end)
        curv = _curvatures(sub)
        length = max(0.0, (end_u - start_u) * total)
        chord = _distance(start, end)
        max_curv = max(curv) if curv else 0.0
        avg_curv = mean(curv) if curv else 0.0
        segment_type = "DEGENERATE" if length <= 1e-9 else "STRAIGHT" if max_curv <= math.radians(tolerance) / max(length, 1e-9) else "CURVED"
        result.append(SegmentFeature(f"S{index:02d}", index, start_u, end_u, start_u * total, end_u * total, length, _safe_ratio(length, total), start, end, _tangent((start, end), True), abs(_tangent((start, end), True) or 0.0), chord, _safe_ratio(length, chord), avg_curv, max_curv, segment_type, str(bend_rows[index - 2].get("bend_id")) if index > 1 else None, str(bend_rows[index - 1].get("bend_id")) if index - 1 < len(bend_rows) else None, "CONNECTED" if chord >= 0 else "INVALID", tuple(), 0.7))
    return tuple(result)


def _bend_features(bends, thickness, total):
    result = []
    for index, bend in enumerate(sorted(bends, key=lambda value: float(value.get("u", 0.0))), start=1):
        radius = _num(bend.get("neutral_line_radius"))
        angle = _num(bend.get("signed_bend_angle")) or 0.0
        result.append({"bend_id": str(bend.get("bend_id", f"BZ{index:02d}")), "bend_order": index, "u": bend.get("u"), "developed_coordinate": bend.get("developed_length_position"), "start_developed_coordinate": bend.get("start_developed_coordinate"), "end_developed_coordinate": bend.get("end_developed_coordinate"), "zone_length": bend.get("zone_length"), "signed_bend_angle": angle, "absolute_bend_angle": abs(angle), "bend_direction": bend.get("bend_direction"), "neutral_line_radius": radius, "estimated_inside_radius": bend.get("inside_radius", radius), "estimated_outside_radius": bend.get("outside_radius", radius), "incoming_tangent": bend.get("incoming_tangent"), "outgoing_tangent": bend.get("outgoing_tangent"), "contributing_vertex_count": bend.get("contributing_vertex_count", 0), "activation_status": bend.get("activation_status", "inactive"), "confidence": bend.get("confidence", 0.0), "source_handles": bend.get("source_entity_handles", ()), "radius_to_thickness_ratio": _safe_ratio(radius, thickness), "angle_per_zone_length": _safe_ratio(abs(angle), bend.get("zone_length")), "bend_severity": abs(angle) * _safe_ratio(1.0, radius) if radius else None, "signed_curvature_contribution": angle / total if total else None, "bend_type": "UP_BEND" if angle > 0 else "DOWN_BEND" if angle < 0 else "INACTIVE"})
    for index, row in enumerate(result):
        row["distance_from_previous_bend"] = row["developed_coordinate"] - result[index - 1]["developed_coordinate"] if index else row["developed_coordinate"]
        row["distance_to_next_bend"] = result[index + 1]["developed_coordinate"] - row["developed_coordinate"] if index + 1 < len(result) else (total - row["developed_coordinate"] if row["developed_coordinate"] is not None else None)
        row["normalized_spacing"] = _safe_ratio(row["distance_from_previous_bend"], total)
    return result


def _symmetry(points, bends, tolerance):
    if not points:
        return {"vertical_score": None, "horizontal_score": None, "best_axis_error": None, "score": None, "classification": "UNKNOWN", "mirror_hausdorff": None, "bend_position_symmetry": None, "bend_angle_symmetry": None, "segment_length_symmetry": None}
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    scale = max(math.hypot(max_x - min_x, max_y - min_y), 1e-9)
    vertical = _mirror_error(points, "x", (min_x + max_x) / 2) / scale
    horizontal = _mirror_error(points, "y", (min_y + max_y) / 2) / scale
    score = max(0.0, 1.0 - min(vertical, horizontal))
    error = min(vertical, horizontal)
    classification = "SYMMETRIC" if error <= tolerance / 2 else "APPROXIMATELY_SYMMETRIC" if error <= tolerance else "ASYMMETRIC"
    positions = [float(b.get("u", 0.0)) for b in bends]
    position_error = _mirror_list_error(positions) if positions else None
    angle_error = _mirror_angle_error(bends) if bends else None
    return {"vertical_score": max(0.0, 1.0 - vertical), "horizontal_score": max(0.0, 1.0 - horizontal), "best_axis_error": error, "score": score, "classification": classification, "mirror_hausdorff": error * scale, "bend_position_symmetry": None if position_error is None else max(0.0, 1.0 - position_error), "bend_angle_symmetry": None if angle_error is None else max(0.0, 1.0 - angle_error), "segment_length_symmetry": None}


def _manufacturing(item, neutral, outline, segments, bends, symmetry, previous, final):
    radii = [row["neutral_line_radius"] for row in bends if row.get("neutral_line_radius") is not None]
    ratios = [row["radius_to_thickness_ratio"] for row in bends if row.get("radius_to_thickness_ratio") is not None]
    active = [row for row in bends if row.get("activation_status") != "inactive"]
    total = neutral["developed_length"]
    curved = sum(row.length for row in segments if row.segment_type == "CURVED")
    curved_fraction = _safe_ratio(curved, total)
    values = {"sheet_thickness": item.sheet_thickness, "thickness_method": item.thickness_method, "thickness_sampling_count": item.thickness_sampling_count, "thickness_variation": item.thickness_variation, "thickness_confidence": item.thickness_confidence, "neutral_line_developed_length": total, "expected_neutral_length": neutral["expected_neutral_length"], "neutral_length_error_percent": neutral["error_percent"], "active_bend_count": len(active), "positive_bend_count": sum(1 for row in active if row["signed_bend_angle"] > 0), "negative_bend_count": sum(1 for row in active if row["signed_bend_angle"] < 0), "total_absolute_bend_angle": sum(row["absolute_bend_angle"] for row in bends), "total_signed_bend_angle": sum(row["signed_bend_angle"] for row in bends), "maximum_absolute_bend_angle": max((row["absolute_bend_angle"] for row in bends), default=0.0), "mean_absolute_bend_angle": mean([row["absolute_bend_angle"] for row in bends]) if bends else 0.0, "bend_angle_stddev": pstdev([row["absolute_bend_angle"] for row in bends]) if len(bends) > 1 else 0.0, "minimum_bend_radius": min(radii) if radii else None, "mean_bend_radius": mean(radii) if radii else None, "minimum_radius_to_thickness": min(ratios) if ratios else None, "mean_radius_to_thickness": mean(ratios) if ratios else None, "bend_density": _safe_ratio(len(active), total), "total_angle_per_length": _safe_ratio(sum(row["absolute_bend_angle"] for row in bends), total), "alternating_bend_direction_count": sum(1 for left, right in zip(bends, bends[1:]) if left["signed_bend_angle"] * right["signed_bend_angle"] < 0), "flat_material_fraction": _safe_ratio(sum(row.length for row in segments if row.segment_type == "STRAIGHT"), total), "curved_material_fraction": curved_fraction, "edge_height_left": abs(item.neutral_line_points[0][1]) if item.neutral_line_points else None, "edge_height_right": abs(item.neutral_line_points[-1][1]) if item.neutral_line_points else None, "edge_height_difference": None, "maximum_profile_height": item.height, "profile_width": item.width, "width_to_developed_length": _safe_ratio(item.width, total), "height_to_developed_length": _safe_ratio(item.height, total), "symmetry_score": symmetry["score"], "formedness_index": _formedness(item.height, item.total_bend_angle, curved_fraction, len(active), item.width), "geometry_quality_score": min(item.confidence, item.neutral_line_confidence), "review_required": item.requires_review}
    if values["edge_height_left"] is not None and values["edge_height_right"] is not None:
        values["edge_height_difference"] = abs(values["edge_height_left"] - values["edge_height_right"])
    return values


def _sequence_features(item, previous, first, final, previous_item=None):
    previous_values = {"width_delta_previous": None, "height_delta_previous": None, "developed_length_delta_previous": None, "total_bend_angle_delta_previous": None, "active_bend_count_delta_previous": None, "maximum_material_point_displacement": None, "mean_contour_displacement": None, "centroid_movement_previous": None, "newly_activated_bend_count": None, "deactivated_bend_count": None, "radius_tightening_count": None, "radius_opening_count": None, "segment_change_count": None}
    if previous:
        previous_values.update({"width_delta_previous": item.width - _scalar(previous, "width"), "height_delta_previous": item.height - _scalar(previous, "height"), "developed_length_delta_previous": item.developed_length - _scalar(previous, "neutral_line_developed_length"), "total_bend_angle_delta_previous": item.physical_total_bend_angle - _scalar(previous, "total_absolute_bend_angle"), "active_bend_count_delta_previous": item.active_bend_count - _scalar(previous, "active_bend_count")})
        old_bends = {str(bend.get("bend_id")): bend for bend in (previous_item.physical_bends if previous_item else ())}
        new_bends = {str(bend.get("bend_id")): bend for bend in item.physical_bends}
        previous_values["newly_activated_bend_count"] = len(set(new_bends) - set(old_bends))
        previous_values["deactivated_bend_count"] = len(set(old_bends) - set(new_bends))
        previous_values["radius_tightening_count"] = sum(1 for key in set(old_bends) & set(new_bends) if _num(new_bends[key].get("neutral_line_radius")) is not None and _num(old_bends[key].get("neutral_line_radius")) is not None and new_bends[key]["neutral_line_radius"] < old_bends[key]["neutral_line_radius"] - 0.1)
        previous_values["radius_opening_count"] = sum(1 for key in set(old_bends) & set(new_bends) if _num(new_bends[key].get("neutral_line_radius")) is not None and _num(old_bends[key].get("neutral_line_radius")) is not None and new_bends[key]["neutral_line_radius"] > old_bends[key]["neutral_line_radius"] + 0.1)
        previous_values["segment_change_count"] = abs((len(item.physical_bends) + 1) - (len(previous_item.physical_bends) + 1))
        if previous_item and previous.geometry.neutral_line.get("sampled_points"):
            left = _resample(previous.geometry.neutral_line["sampled_points"], 101)
            right = _resample(item.neutral_line_points, 101)
            displacements = [_distance(a, b) for a, b in zip(left, right)]
            previous_values["maximum_material_point_displacement"] = max(displacements, default=None)
            previous_values["mean_contour_displacement"] = mean(displacements) if displacements else None
            previous_values["centroid_movement_previous"] = _distance(_weighted_centroid(left, _cumulative(left)), _weighted_centroid(right, _cumulative(right)))
    total_order = max(item.inferred_order, 1)
    final_width = _scalar(final, "width") if final else None
    final_height = _scalar(final, "height") if final else None
    final_angle = _scalar(final, "total_absolute_bend_angle") if final else None
    final_formedness = _scalar(final, "formedness_index") if final else None
    return {**previous_values, "progress_ratio": _safe_ratio(item.inferred_order, total_order), "width_ratio_final": _safe_ratio(item.width, final_width), "height_ratio_final": _safe_ratio(item.height, final_height), "bend_angle_ratio_final": _safe_ratio(item.physical_total_bend_angle, final_angle), "formedness_ratio_final": _safe_ratio(_scalar(None, "formedness_index"), final_formedness)}


def _scalar_values(bbox, outline, neutral, segments, bends, manufacturing, symmetry, sequence):
    values = {"bbox_min_x": bbox["min_x"], "bbox_min_y": bbox["min_y"], "bbox_max_x": bbox["max_x"], "bbox_max_y": bbox["max_y"], "width": bbox["width"], "height": bbox["height"], "bbox_area": bbox["area"], "bbox_perimeter": bbox["perimeter"], "aspect_ratio": bbox["aspect_ratio"], "bbox_diagonal": bbox["diagonal"], "bbox_center_x": bbox["center_x"], "bbox_center_y": bbox["center_y"], "outline_area": outline["area"], "outline_perimeter": outline["perimeter"], "polygon_centroid_x": outline["centroid_x"], "polygon_centroid_y": outline["centroid_y"], "convex_hull_area": outline["convex_hull_area"], "convex_hull_perimeter": outline["convex_hull_perimeter"], "solidity": outline["solidity"], "compactness": outline["compactness"], "number_of_holes": outline["number_of_holes"], "neutral_line_developed_length": neutral["developed_length"], "expected_neutral_length": neutral["expected_neutral_length"], "absolute_neutral_length_error": neutral["absolute_error"], "neutral_length_error_percent": neutral["error_percent"], "neutral_point_count": neutral["point_count"], "chord_length": neutral["chord_length"], "tortuosity": neutral["tortuosity"], "maximum_distance_from_chord": neutral["maximum_distance_from_chord"], "rms_distance_from_chord": neutral["rms_distance_from_chord"], "neutral_centroid_x": neutral["centroid_x"], "neutral_centroid_y": neutral["centroid_y"], "start_tangent_angle": neutral["start_tangent_angle"], "end_tangent_angle": neutral["end_tangent_angle"], "net_profile_rotation": neutral["net_profile_rotation"], "maximum_local_curvature": neutral["maximum_local_curvature"], "mean_absolute_curvature": neutral["mean_absolute_curvature"], "curvature_stddev": neutral["curvature_stddev"], "segment_count": len(segments), "min_segment_length": min((row.length for row in segments), default=None), "max_segment_length": max((row.length for row in segments), default=None), "mean_segment_length": mean([row.length for row in segments]) if segments else None, "segment_length_stddev": pstdev([row.length for row in segments]) if len(segments) > 1 else 0.0, "longest_segment_ratio": _safe_ratio(max((row.length for row in segments), default=None), neutral["developed_length"])}
    values.update({key: manufacturing.get(key) for key in SCALAR_FEATURE_FIELDS if key not in values})
    values.update({key: symmetry.get(key.replace("symmetry_score", "score")) for key in ("symmetry_score",) if key not in values})
    values["vertical_symmetry_score"] = symmetry.get("vertical_score")
    values["horizontal_symmetry_score"] = symmetry.get("horizontal_score")
    values.update(sequence)
    values["feature_confidence"] = manufacturing.get("geometry_quality_score")
    return values


def _vector(names, mapping, decimals, metadata):
    values, mask = [], []
    for name in names:
        value = _finite(mapping.get(name))
        mask.append(value is None)
        values.append(0.0 if value is None else round(float(value), decimals))
    return FeatureVector(tuple(names), tuple(values), tuple(mask), PASS_FEATURE_SCHEMA_VERSION, dict(metadata))


def _normalized_shape(points, count, mirror, decimals, minimum):
    physical = _resample(points, count)
    scale = _path_length(physical)
    if scale < minimum:
        scale = 1.0
    origin = physical[0] if physical else (0.0, 0.0, 0.0)
    forward = tuple(((point[0] - origin[0]) / scale, (point[1] - origin[1]) / scale, 0.0) for point in physical)
    reverse_raw = tuple(reversed(physical))
    reverse_origin = reverse_raw[0] if reverse_raw else (0.0, 0.0, 0.0)
    reverse = tuple(((point[0] - reverse_origin[0]) / scale, (point[1] - reverse_origin[1]) / scale, 0.0) for point in reverse_raw)
    canonical = min(forward, reverse)
    mirrored = tuple((-point[0], point[1], point[2]) for point in canonical)
    chosen = min(canonical, mirrored) if mirror else canonical
    physical_forward = tuple((point[0] - origin[0], point[1] - origin[1], 0.0) for point in physical)
    physical_reverse = tuple(reversed(physical_forward))
    physical_canonical = min(physical_forward, physical_reverse)
    return {"physical_points": physical_canonical, "normalized_points": chosen, "metadata": {"translation_invariant": True, "direction_canonical": True, "mirror_canonicalization": mirror, "scale": scale, "scale_basis": "developed_length", "sample_count": count, "rounding_decimals": decimals}}


def _fingerprints(item, neutral, normalized, bends, decimals):
    physical_payload = {"schema_version": PASS_FEATURE_SCHEMA_VERSION, "points": _rounded_points(normalized["physical_points"], decimals), "developed_length": _round(neutral["developed_length"], decimals), "bends": _canonical_bends(bends, decimals)}
    shape_payload = {"schema_version": PASS_FEATURE_SCHEMA_VERSION, "points": _rounded_points(normalized["normalized_points"], decimals)}
    mirror_payload = {"schema_version": PASS_FEATURE_SCHEMA_VERSION, "points": min(_rounded_points(normalized["normalized_points"], decimals), _rounded_points(tuple((-x, y, z) for x, y, z in normalized["normalized_points"]), decimals))}
    combined_payload = {"physical": physical_payload, "shape": shape_payload, "mirror": mirror_payload}
    return {"physical_fingerprint": _digest(physical_payload), "shape_fingerprint": _digest(shape_payload), "mirror_canonical_fingerprint": _digest(mirror_payload), "combined_fingerprint": _digest(combined_payload)}


def _bend_histories(passes):
    rows: dict[str, dict[str, Any]] = {}
    for item in passes:
        for bend in item.physical_bends:
            bend_id = str(bend.get("bend_id"))
            angle = _num(bend.get("signed_bend_angle")) or 0.0
            radius = _num(bend.get("neutral_line_radius"))
            row = rows.setdefault(bend_id, {"bend_id": bend_id, "first_activation_pass": item.inferred_order, "last_active_pass": item.inferred_order, "activation_order": item.inferred_order, "maximum_absolute_angle": 0.0, "final_angle": angle, "angle_progression": [], "maximum_angle_increment": 0.0, "number_of_reversals": 0, "minimum_radius": radius, "final_radius": radius, "radius_progression": [], "confidence": bend.get("confidence", 0.0), "engineer_confirmed": False})
            row["last_active_pass"] = item.inferred_order
            row["maximum_absolute_angle"] = max(row["maximum_absolute_angle"], abs(angle))
            row["final_angle"] = angle
            row["angle_progression"].append(angle)
            row["radius_progression"].append(radius)
            row["minimum_radius"] = min((value for value in (row["minimum_radius"], radius) if value is not None), default=None)
            row["final_radius"] = radius
    for row in rows.values():
        row["maximum_angle_increment"] = max((abs(b - a) for a, b in zip(row["angle_progression"], row["angle_progression"][1:])), default=0.0)
        row["number_of_reversals"] = sum(1 for a, b in zip(row["angle_progression"], row["angle_progression"][1:]) if a * b < 0)
    return rows


def _weighted_centroid(points, cumulative):
    if len(points) < 2:
        return (points[0][0], points[0][1]) if points else (None, None)
    total = cumulative[-1]
    if total <= 0:
        return (points[0][0], points[0][1])
    return (sum((a[0] + b[0]) / 2 * (s2 - s1) for a, b, s1, s2 in zip(points, points[1:], cumulative, cumulative[1:])) / total, sum((a[1] + b[1]) / 2 * (s2 - s1) for a, b, s1, s2 in zip(points, points[1:], cumulative, cumulative[1:])) / total)


def _chord_distances(points):
    if len(points) < 2:
        return []
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    denominator = math.hypot(dx, dy)
    if denominator <= 1e-12:
        return [_distance(point, a) for point in points]
    return [abs(dy * point[0] - dx * point[1] + b[0] * a[1] - b[1] * a[0]) / denominator for point in points]


def _curvatures(points):
    result = []
    for left, center, right in zip(points, points[1:], points[2:]):
        first = _distance(left, center)
        second = _distance(center, right)
        if first <= 1e-12 or second <= 1e-12:
            continue
        angle = abs(_turn(left, center, right))
        result.append(angle / ((first + second) / 2))
    return result


def _turn(left, center, right):
    a = (center[0] - left[0], center[1] - left[1])
    b = (right[0] - center[0], right[1] - center[1])
    return math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])


def _tangent(points, start):
    seq = points if start else tuple(reversed(points))
    for left, right in zip(seq, seq[1:]):
        if _distance(left, right) > 1e-12:
            return math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))
    return None


def _mirror_error(points, axis, center):
    reflected = [((2 * center - point[0], point[1]) if axis == "x" else (point[0], 2 * center - point[1])) for point in points]
    return mean(min(math.hypot(point[0] - target[0], point[1] - target[1]) for target in points) for point in reflected) if points else 0.0


def _mirror_list_error(values):
    return mean(abs(value - (1 - other)) for value, other in zip(sorted(values), reversed(sorted(values)))) if values else 0.0


def _mirror_angle_error(bends):
    angles = [abs(float(bend.get("signed_bend_angle", 0.0))) for bend in bends]
    return _safe_ratio(mean(abs(a - b) for a, b in zip(angles, reversed(angles))), max(angles, default=1.0))


def _formedness(height, angle, curved_fraction, bend_count, width):
    return max(0.0, min(1.0, 0.25 * _safe_ratio(abs(height), max(abs(width), abs(height), 1e-9)) + 0.25 * min(abs(angle) / 180.0, 1.0) + 0.25 * (curved_fraction or 0.0) + 0.25 * min(bend_count / 8.0, 1.0)))


def _resample(points, count):
    if count <= 0:
        return ()
    points = _clean_points(points)
    if not points:
        return tuple((0.0, 0.0, 0.0) for _ in range(count))
    cumulative = _cumulative(points)
    total = cumulative[-1]
    if total <= 1e-12:
        return tuple(points[0] for _ in range(count))
    return tuple(_point_at(points, cumulative, total * index / (count - 1 if count > 1 else 1)) for index in range(count))


def _point_at(points, cumulative, target):
    for left, right, start, end in zip(points, points[1:], cumulative, cumulative[1:]):
        if target <= end:
            ratio = _safe_ratio(target - start, end - start) or 0.0
            return tuple(left[index] + (right[index] - left[index]) * ratio for index in range(3))
    return points[-1]


def _cumulative(points):
    result = [0.0]
    for left, right in zip(points, points[1:]):
        result.append(result[-1] + _distance(left, right))
    return tuple(result)


def _path_length(points):
    return sum(_distance(left, right) for left, right in zip(points, points[1:]))


def _canonical_bends(bends, decimals):
    return tuple((row.get("bend_id"), _round(row.get("u"), decimals), _round(row.get("signed_bend_angle"), decimals), _round(row.get("neutral_line_radius"), decimals)) for row in bends)


def _rounded_points(points, decimals):
    return tuple(tuple(round(float(value), decimals) for value in point) for point in points)


def _digest(payload):
    return sha256(json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    return value


def _clean_points(points):
    result = []
    for value in points or ():
        point = _point(value)
        if all(math.isfinite(component) for component in point) and (not result or _distance(result[-1], point) > 1e-12):
            result.append(point)
    return tuple(result)


def _point(value):
    value = tuple(value)
    return (float(value[0]), float(value[1]), float(value[2]) if len(value) > 2 else 0.0)


def _distance(left, right):
    return math.dist(_point(left), _point(right))


def _safe_ratio(numerator, denominator):
    if numerator is None or denominator is None or abs(float(denominator)) <= 1e-12:
        return None
    return float(numerator) / float(denominator)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _num(value):
    return _finite(value)


def _round(value, decimals):
    value = _finite(value)
    return None if value is None else round(value, decimals)


def _angle_delta(left, right):
    if left is None or right is None:
        return None
    return (right - left + 180.0) % 360.0 - 180.0


def _scalar(row, name):
    if row is None:
        return None
    if name == "width":
        return row.geometry.bbox.get("width")
    if name == "height":
        return row.geometry.bbox.get("height")
    if name == "neutral_line_developed_length":
        return row.geometry.neutral_line.get("developed_length")
    return row.manufacturing.values.get(name)
