from __future__ import annotations

from rollform_extractor.composite_flower import CompositeFlowerPass, CompositeFlowerRecord
from rollform_extractor.config import ExtractionConfig
from rollform_extractor.models import BBox, ProfileRecord
from rollform_extractor.pass_features import PASS_FEATURE_SCHEMA_VERSION, extract_composite_pass_features


def _pass(points, *, pass_id="pass_00_flat", order=0, translated=(0.0, 0.0)):
    points = tuple((x + translated[0], y + translated[1], 0.0) for x, y in points)
    profile = ProfileRecord("profile-1", "station-1", ("H1",), "test", "profile-hash", 0.9, {"bbox": BBox(min(x for x, _, _ in points), min(y for _, y, _ in points), max(x for x, _, _ in points), max(y for _, y, _ in points))})
    return CompositeFlowerPass(
        pass_id=pass_id, composite_flower_id="flower-1", station_id="station-1", profile_id="profile-1",
        inferred_order=order, confirmed_order=None, profile_type="TRUE_CENTERLINE_PROFILE", source_handles=("H1",), source_layers=(),
        developed_length=sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(points, points[1:])),
        width=max(x for x, _, _ in points) - min(x for x, _, _ in points), height=max(y for _, y, _ in points) - min(y for _, y, _ in points),
        bend_count=0, total_bend_angle=0.0, raw_geometry_corner_count=0, raw_total_turning_angle=0.0,
        physical_forming_bend_count=0, physical_total_bend_angle=0.0, active_bend_count=0, bend_signature="", vertex_turn_count=0,
        physical_bends=(), neutral_line_primitives=(), neutral_line_points=points, neutral_line_developed_length=0.0,
        expected_neutral_length=None, neutral_length_error=None, neutral_length_error_percent=None, sheet_thickness=None,
        thickness_method="unavailable", thickness_sampling_count=0, thickness_variation=None, thickness_confidence=0.0,
        engineer_confirmed_thickness=None, neutral_line_method="test", neutral_line_confidence=0.9, confidence=0.9,
        order_confidence=0.9, duplicate_group_id=None, requires_review=False, transform_matrix_4x4=(), profile=profile,
    )


def _features(item):
    config = ExtractionConfig.load()
    flower = CompositeFlowerRecord("flower-1", "station-1", 1, 0.9, False, BBox(0, 0, 10, 5), (item,))
    return extract_composite_pass_features("drawing-1", flower, config.hash_for("feature_extraction"), config.features, {"confirmed": True})[item.pass_id]


def test_flat_open_line_has_fixed_vectors_and_explicit_area_warning():
    features = _features(_pass(((0, 0), (10, 0))))
    assert features.schema_version == PASS_FEATURE_SCHEMA_VERSION
    assert len(features.scalar_vector.values) == 94
    assert len(features.shape_vector.values) == 256
    assert len(features.full_vector.values) == 350
    assert "OPEN_PROFILE_AREA_UNAVAILABLE" in features.quality.flags
    assert all(len(value) == 64 for value in features.fingerprints.values())


def test_translation_and_direction_reversal_preserve_shape_fingerprint():
    first = _features(_pass(((0, 0), (10, 0), (10, 5))))
    translated = _features(_pass(((0, 0), (10, 0), (10, 5)), translated=(100, -20)))
    reversed_pass = _features(_pass(((10, 5), (10, 0), (0, 0))))
    assert first.fingerprints["shape_fingerprint"] == translated.fingerprints["shape_fingerprint"]
    assert first.fingerprints["shape_fingerprint"] == reversed_pass.fingerprints["shape_fingerprint"]


def test_missing_values_use_mask_without_nonfinite_numbers():
    features = _features(_pass(((0, 0), (0, 0))))
    assert all(value == value and abs(value) != float("inf") for value in features.full_vector.values)
    assert len(features.full_vector.missing_mask) == len(features.full_vector.values)
