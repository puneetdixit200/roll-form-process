from __future__ import annotations

import pytest

from rollform_extractor.feature_extractor import extract_profile_features, fingerprint_profile
from rollform_extractor.models import BBox, CadPrimitive, ProfileRecord


def test_arc_radius_and_developed_length_use_exact_primitives(profile_with_arc):
    features = extract_profile_features(profile_with_arc, "config-hash")

    assert features.bends[0].radius_mm == pytest.approx(3.0)
    assert features.developed_length_mm == pytest.approx(profile_with_arc.features["exact_length"])
    assert features.provenance["developed_length_mm"].source_handles == ("L1", "A1")


def test_inches_profile_uses_normalized_millimetre_primitives():
    profile = _profile(
        ("I1",),
        (CadPrimitive("LINE", {"start": (0, 0, 0), "end": (25.4, 0, 0)}, "I1"),),
        ((0, 0, 0), (25.4, 0, 0)),
    )

    features = extract_profile_features(profile, "config-hash")

    assert features.developed_length_mm == pytest.approx(25.4)
    assert features.width_mm == pytest.approx(25.4)


def test_double_boundary_uses_longest_connected_contour_for_developed_length():
    profile = _profile(
        ("O1", "O2", "I1"),
        (
            CadPrimitive("LINE", {"start": (0, 0, 0), "end": (10, 0, 0)}, "O1"),
            CadPrimitive("LINE", {"start": (10, 0, 0), "end": (20, 0, 0)}, "O2"),
            CadPrimitive("LINE", {"start": (0, 2, 0), "end": (8, 2, 0)}, "I1"),
        ),
        ((0, 0, 0), (10, 0, 0), (20, 0, 0), (0, 2, 0), (8, 2, 0)),
    )

    features = extract_profile_features(profile, "config-hash")

    assert features.developed_length_mm == pytest.approx(20.0)
    assert features.provenance["developed_length_mm"].source_handles == ("O1", "O2")


def test_mirrored_fingerprint_matches_unmirrored_profile():
    features = extract_profile_features(_profile_with_lines("P", ((0, 0), (10, 0), (10, 5))), "hash")
    mirrored_points = tuple((-x, y, z) for x, y, z in features.sampled_points)

    normal = fingerprint_profile(features, features.sampled_points)
    mirrored = fingerprint_profile(features, mirrored_points, mirrored=True)

    assert normal.digest == mirrored.digest


def test_fingerprint_changes_when_bend_radius_changes(profile_with_arc):
    first = extract_profile_features(profile_with_arc, "config-hash")
    other_profile = _profile(
        ("L1", "A1"),
        (
            CadPrimitive("LINE", {"start": (0, 0, 0), "end": (10, 0, 0)}, "L1"),
            CadPrimitive("ARC", {"center": (10, 4, 0), "radius": 4, "start_angle": 270, "end_angle": 360}, "A1"),
        ),
        ((0, 0, 0), (10, 0, 0), (14, 4, 0)),
    )
    second = extract_profile_features(other_profile, "config-hash")

    assert fingerprint_profile(first, first.sampled_points).digest != fingerprint_profile(second, second.sampled_points).digest


@pytest.fixture
def profile_with_arc():
    return _profile(
        ("L1", "A1"),
        (
            CadPrimitive("LINE", {"start": (0, 0, 0), "end": (10, 0, 0)}, "L1"),
            CadPrimitive("ARC", {"center": (10, 3, 0), "radius": 3, "start_angle": 270, "end_angle": 360}, "A1"),
        ),
        ((0, 0, 0), (10, 0, 0), (13, 3, 0)),
        exact_length=10 + 3 * 3.141592653589793 / 2,
    )


def _profile_with_lines(prefix, points):
    primitives = tuple(
        CadPrimitive("LINE", {"start": (*start, 0.0), "end": (*end, 0.0)}, f"{prefix}{index}")
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1)
    )
    return _profile(tuple(primitive.source_handle for primitive in primitives), primitives, tuple((*point, 0.0) for point in points))


def _profile(handles, primitives, sampled, *, exact_length=None):
    xs = [point[0] for point in sampled]
    ys = [point[1] for point in sampled]
    features = {"normalized_primitives": primitives, "sampled_points": sampled}
    if exact_length is not None:
        features["exact_length"] = exact_length
    return ProfileRecord(
        profile_id="P1",
        station_id="S1",
        source_handles=handles,
        method="profile_detector",
        configuration_hash="profile-hash",
        confidence=0.9,
        features={**features, "bbox": BBox(min(xs), min(ys), max(xs), max(ys))},
    )
