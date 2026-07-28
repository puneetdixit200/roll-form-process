from __future__ import annotations

from dataclasses import replace

import pytest

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive, StationRecord
from rollform_extractor.profile_detector import detect_profiles
from rollform_extractor.review import ManualOverrides


@pytest.fixture
def station_with_two_contours():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 30, 10), ("A1", "A2", "A3", "B1", "B2"))
    entities = (
        _line("A1", (0, 0), (10, 0), layer="PROFILE"),
        _line("A2", (10, 0), (20, 0), layer="PROFILE"),
        _line("A3", (20, 0), (30, 0), layer="PROFILE"),
        _line("B1", (0, 5), (8, 5), layer="ROLLER"),
        _line("B2", (8, 5), (16, 5), layer="ROLLER"),
    )
    return station, entities, config


def test_manual_profile_handles_take_precedence(station_with_two_contours):
    station, entities, config = station_with_two_contours

    result = detect_profiles((station,), entities, config, overrides=ManualOverrides(profile_handles={"1": ("A1", "A2")}))

    assert result.profiles[0].source_handles == ("A1", "A2")
    assert result.profiles[0].method == "manual_override"
    assert result.manual_review_required is False


def test_long_profile_chain_beats_short_roller_geometry(station_with_two_contours):
    station, entities, config = station_with_two_contours

    result = detect_profiles((station,), entities, config)

    assert result.profiles[0].source_handles == ("A1", "A2", "A3")
    assert result.profiles[0].confidence >= config.profiles.minimum_confidence
    assert result.manual_review_required is False


def test_ambiguous_profile_candidates_are_sent_to_review(station_with_two_contours):
    station, entities, _ = station_with_two_contours
    config = ExtractionConfig.load(overrides={"profiles": {"minimum_score_margin": 0.5}})

    result = detect_profiles((station,), entities, config)

    assert result.manual_review_required is True
    assert result.warnings[0].code == "profile_ambiguity"
    assert set(result.warnings[0].source_handles) == {"A1", "A2", "A3", "B1", "B2"}


def test_duplicate_profile_handles_are_not_counted_twice(station_with_two_contours):
    station, entities, config = station_with_two_contours
    duplicate = replace(entities[0], handle="A1_DUP", source_handles=("A1",))

    result = detect_profiles((station,), (*entities, duplicate), config)

    assert result.profiles[0].source_handles == ("A1", "A2", "A3")


def test_broken_contour_is_retained_with_warning():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 20, 20), ("P1", "P2"))
    entities = (
        _line("P1", (0, 0), (10, 0), layer="PROFILE"),
        _line("P2", (12, 0), (18, 0), layer="PROFILE"),
    )

    result = detect_profiles((station,), entities, config)

    assert result.profiles[0].source_handles == ("P1",)
    assert result.manual_review_required is True
    assert result.warnings[0].code == "broken_profile_contour"


def test_developed_length_consistency_breaks_tie_between_consecutive_stations():
    config = ExtractionConfig.load()
    first = _station("S1", 1, BBox(0, 0, 30, 10), ("S1A", "S1B", "S1C"))
    second = _station("S2", 2, BBox(40, 0, 70, 10), ("S2A", "S2B", "S2C", "S2D", "S2E"))
    entities = (
        _line("S1A", (0, 0), (10, 0), layer="PROFILE"),
        _line("S1B", (10, 0), (20, 0), layer="PROFILE"),
        _line("S1C", (20, 0), (30, 0), layer="PROFILE"),
        _line("S2A", (40, 0), (50, 0), layer="PROFILE"),
        _line("S2B", (50, 0), (60, 0), layer="PROFILE"),
        _line("S2C", (60, 0), (70, 0), layer="PROFILE"),
        _line("S2D", (40, 5), (55, 5), layer="PROFILE"),
        _line("S2E", (55, 5), (70, 5), layer="PROFILE"),
    )

    result = detect_profiles((first, second), entities, config)

    assert result.profiles[1].source_handles == ("S2A", "S2B", "S2C")


def test_profile_only_station_can_extract_profile_without_rollers(station_with_two_contours):
    station, entities, config = station_with_two_contours

    result = detect_profiles((station,), entities[:3], config)

    assert result.profiles[0].station_id == "S1"
    assert result.profiles[0].source_handles == ("A1", "A2", "A3")


def test_arc_connected_to_line_stays_in_same_profile_chain():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 15, 5), ("L1", "A1"))
    line = _line("L1", (0, 0), (10, 0), layer="PROFILE")
    arc_primitive = CadPrimitive(
        kind="ARC",
        attributes={"center": (10.0, 3.0, 0.0), "radius": 3.0, "start_angle": 270.0, "end_angle": 360.0},
        source_handle="A1",
    )
    arc = CadEntityRecord(
        handle="A1",
        entity_type="ARC",
        layer="PROFILE",
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(10, 0, 13, 3),
        normalized_primitives=(arc_primitive,),
        sampled_geometry=(),
        source_handles=("A1",),
    )

    result = detect_profiles((station,), (line, arc), config)

    assert result.profiles[0].source_handles == ("L1", "A1")


def test_polyline_mapping_vertices_connect_to_line_after_model_freeze():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 20, 10), ("L1", "P1"))
    line = _line("L1", (0, 0), (10, 0), layer="PROFILE")
    polyline_primitive = CadPrimitive(
        kind="LWPOLYLINE",
        attributes={
            "vertices": (
                {"point": (10, 0, 0), "bulge": 0, "start_width": 0, "end_width": 0},
                {"point": (15, 0, 0), "bulge": 0, "start_width": 0, "end_width": 0},
            ),
            "closed": False,
        },
        source_handle="P1",
    )
    polyline = CadEntityRecord(
        handle="P1",
        entity_type="LWPOLYLINE",
        layer="PROFILE",
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(10, 0, 15, 0),
        normalized_primitives=(polyline_primitive,),
        sampled_geometry=(),
        source_handles=("P1",),
    )

    result = detect_profiles((station,), (line, polyline), config)

    assert result.profiles[0].source_handles == ("L1", "P1")


def test_ellipse_arc_connects_to_line_by_first_and_last_sampled_points():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 20, 5), ("E1", "L1"))
    ellipse_primitive = CadPrimitive(
        kind="ELLIPSE_ARC",
        attributes={
            "center": (0, 0, 0),
            "major_axis": (10, 0, 0),
            "minor_axis": (0, 2, 0),
            "start_param": 0.0,
            "end_param": 3.141592653589793,
        },
        source_handle="E1",
    )
    ellipse = CadEntityRecord(
        handle="E1",
        entity_type="ELLIPSE",
        layer="PROFILE",
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(-10, 0, 10, 2),
        normalized_primitives=(ellipse_primitive,),
        sampled_geometry=((10, 0, 0), (0, 2, 0), (-10, 0, 0)),
        source_handles=("E1",),
    )
    line = _line("L1", (-10, 0), (-15, 0), layer="PROFILE")

    result = detect_profiles((station,), (ellipse, line), config)

    assert result.profiles[0].source_handles == ("E1", "L1")
    assert result.profiles[0].features["exact_length"] > 5.0


def _station(station_id, sequence, bbox, handles):
    return StationRecord(
        station_id=station_id,
        sequence_index=sequence,
        bbox=bbox,
        source_handles=handles,
        method="station_detector",
        configuration_hash="station-hash",
        confidence=0.9,
    )


def _line(handle, start, end, *, layer="0", color=3, line_type="CONTINUOUS"):
    primitive = CadPrimitive(
        kind="LINE",
        attributes={"start": (*start, 0.0), "end": (*end, 0.0)},
        source_handle=handle,
    )
    min_x = min(start[0], end[0])
    max_x = max(start[0], end[0])
    min_y = min(start[1], end[1])
    max_y = max(start[1], end[1])
    return CadEntityRecord(
        handle=handle,
        entity_type="LINE",
        layer=layer,
        color=color,
        line_type=line_type,
        layout="Model",
        bbox=BBox(min_x, min_y, max_x, max_y),
        normalized_primitives=(primitive,),
        sampled_geometry=((*start, 0.0), (*end, 0.0)),
        source_handles=(handle,),
    )
