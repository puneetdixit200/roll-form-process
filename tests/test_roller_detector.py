from __future__ import annotations

import pytest

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive, ProfileRecord, StationRecord
from rollform_extractor.roller_detector import detect_rollers
from rollform_extractor.review import ManualOverrides


@pytest.fixture
def profile_and_rolls():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 100, 80), ("P1", "UL1", "UL2", "UR1", "UR2", "LL1", "LL2", "LR1", "LR2"))
    profile = _profile(station, BBox(35, 30, 65, 40), ("P1",))
    entities = (
        _line("P1", (35, 35), (65, 35), layer="PROFILE"),
        _circle("UL1", (30, 55), 8),
        _circle("UL2", (30, 55), 3),
        _circle("UR1", (70, 55), 8),
        _circle("UR2", (70, 55), 3),
        _circle("LL1", (30, 15), 8),
        _circle("LL2", (30, 15), 3),
        _circle("LR1", (70, 15), 8),
        _circle("LR2", (70, 15), 3),
    )
    return (station,), (profile,), entities, config


@pytest.fixture
def profile_only_station():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 100, 80), ("P1",))
    profile = _profile(station, BBox(35, 30, 65, 40), ("P1",))
    entities = (_line("P1", (35, 35), (65, 35), layer="PROFILE"),)
    return (station,), (profile,), entities, config


def test_subrollers_remain_separate_and_receive_profile_relative_roles(profile_and_rolls):
    result = detect_rollers(*profile_and_rolls, overrides=None)

    assert len(result.rollers) == 4
    assert {roller.role for roller in result.rollers} == {
        "upper_left",
        "upper_right",
        "lower_left",
        "lower_right",
    }


def test_profile_only_station_still_creates_empty_assembly(profile_only_station):
    result = detect_rollers(*profile_only_station, overrides=None)

    assert result.assemblies == ()


def test_concentric_circles_capture_outer_bore_keyway_and_annotation():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 80, 80), ("P1", "R1", "R2", "K1", "T1"))
    profile = _profile(station, BBox(30, 25, 50, 35), ("P1",))
    entities = (
        _line("P1", (30, 30), (50, 30), layer="PROFILE"),
        _circle("R1", (40, 50), 10),
        _circle("R2", (40, 50), 4),
        _line("K1", (36, 50), (44, 50), layer="ROLLER"),
        _text("T1", "R12 OD20 BORE8", (48, 56)),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    roller = result.rollers[0]
    assert roller.evidence["outer_diameter_mm"] == 20.0
    assert roller.evidence["bore_diameter_mm"] == 8.0
    assert roller.evidence["keyway"] is True
    assert roller.evidence["identifier"] == "R12"
    assert roller.evidence["annotations"] == ("R12 OD20 BORE8",)


def test_manual_roller_roles_override_profile_relative_classification(profile_and_rolls):
    stations, profiles, entities, config = profile_and_rolls
    overrides = ManualOverrides(roller_handles={"1": {"guide": ("UL1", "UL2")}})

    result = detect_rollers(stations, profiles, entities, config, overrides=overrides)

    guide = next(roller for roller in result.rollers if set(roller.source_handles) == {"UL1", "UL2"})
    assert guide.role == "guide"
    assert guide.method == "manual_override"
    assert result.manual_review_required is False


def test_weak_centre_role_and_duplicate_identifiers_go_to_review():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 100, 80), ("P1", "A1", "A2", "TA", "B1", "B2", "TB"))
    profile = _profile(station, BBox(35, 30, 65, 40), ("P1",))
    entities = (
        _line("P1", (35, 35), (65, 35), layer="PROFILE"),
        _circle("A1", (49, 55), 8),
        _circle("A2", (49, 55), 3),
        _text("TA", "R9", (55, 60)),
        _circle("B1", (51, 15), 8),
        _circle("B2", (51, 15), 3),
        _text("TB", "R9", (57, 20)),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    assert result.manual_review_required is True
    assert {warning.code for warning in result.warnings} == {"weak_roller_role", "duplicate_roller_identifier"}


def test_shaft_and_spacer_candidates_remain_separate_from_tooling_roles():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 100, 80), ("P1", "S1", "S2", "D1", "D2"))
    profile = _profile(station, BBox(35, 30, 65, 40), ("P1",))
    entities = (
        _line("P1", (35, 35), (65, 35), layer="PROFILE"),
        _circle("S1", (50, 60), 5, layer="SHAFT"),
        _circle("S2", (50, 60), 2, layer="SHAFT"),
        _circle("D1", (50, 10), 6, layer="SPACER"),
        _circle("D2", (50, 10), 3, layer="SPACER"),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    assert {roller.role for roller in result.rollers} == {"shaft", "spacer"}
    assert len(result.rollers) == 2


def test_manual_override_source_handles_suppress_expanded_auto_duplicates():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 80, 80), ("RAW1", "RAW2"))
    profile = _profile(station, BBox(30, 25, 50, 35), ("P1",))
    entities = (
        _circle("EXP1", (40, 50), 10, source_handles=("RAW1",)),
        _circle("EXP2", (40, 50), 4, source_handles=("RAW2",)),
    )
    overrides = ManualOverrides(roller_handles={"1": {"upper_centre": ("RAW1", "RAW2")}})

    result = detect_rollers((station,), (profile,), entities, config, overrides=overrides)

    assert len(result.rollers) == 1
    assert result.rollers[0].method == "manual_override"


def test_station_source_handles_include_owned_rollers_outside_station_bbox():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 20, 20), ("R1", "R2"))
    profile = _profile(station, BBox(5, 5, 15, 10), ("P1",))
    entities = (
        _circle("R1", (40, 30), 10),
        _circle("R2", (40, 30), 4),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    assert len(result.rollers) == 1
    assert set(result.rollers[0].source_handles) == {"R1", "R2"}


def test_arc_only_rotational_outlines_are_detected_as_rollers():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 80, 80), ("P1", "A1", "A2"))
    profile = _profile(station, BBox(30, 25, 50, 35), ("P1",))
    entities = (
        _line("P1", (30, 30), (50, 30), layer="PROFILE"),
        _arc("A1", (40, 50), 10, 0, 180),
        _arc("A2", (40, 50), 4, 180, 360),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    assert len(result.rollers) == 1
    assert result.rollers[0].evidence["outer_diameter_mm"] == 20.0
    assert result.rollers[0].evidence["bore_diameter_mm"] == 8.0


def test_polyline_tooling_outline_becomes_low_confidence_review_candidate():
    config = ExtractionConfig.load()
    station = _station("S1", 1, BBox(0, 0, 100, 80), ("P1", "RBOX"))
    profile = _profile(station, BBox(30, 30, 70, 35), ("P1",))
    entities = (
        _line("P1", (30, 32), (70, 32), layer="PROFILE"),
        _polyline("RBOX", ((25, 45), (75, 45), (75, 65), (25, 65)), layer="0-CAD-polyline"),
    )

    result = detect_rollers((station,), (profile,), entities, config)

    assert len(result.rollers) == 1
    assert result.rollers[0].method == "roller_polyline_candidate"
    assert result.rollers[0].role is None
    assert result.rollers[0].evidence["candidate_role"] == "upper_centre"
    assert result.manual_review_required is True


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


def _profile(station, bbox, handles):
    return ProfileRecord(
        profile_id=f"{station.station_id}-P1",
        station_id=station.station_id,
        source_handles=handles,
        method="profile_detector",
        configuration_hash="profile-hash",
        confidence=0.9,
        features={"bbox": bbox},
    )


def _circle(handle, center, radius, *, layer="ROLLER", source_handles=None):
    primitive = CadPrimitive(kind="CIRCLE", attributes={"center": (*center, 0.0), "radius": radius}, source_handle=handle)
    return CadEntityRecord(
        handle=handle,
        entity_type="CIRCLE",
        layer=layer,
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        normalized_primitives=(primitive,),
        sampled_geometry=((center[0] + radius, center[1], 0.0),),
        source_handles=source_handles or (handle,),
    )


def _arc(handle, center, radius, start_angle, end_angle, *, layer="ROLLER"):
    primitive = CadPrimitive(
        kind="ARC",
        attributes={"center": (*center, 0.0), "radius": radius, "start_angle": start_angle, "end_angle": end_angle},
        source_handle=handle,
    )
    return CadEntityRecord(
        handle=handle,
        entity_type="ARC",
        layer=layer,
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius),
        normalized_primitives=(primitive,),
        sampled_geometry=(),
        source_handles=(handle,),
    )


def _line(handle, start, end, *, layer="0"):
    primitive = CadPrimitive(kind="LINE", attributes={"start": (*start, 0.0), "end": (*end, 0.0)}, source_handle=handle)
    return CadEntityRecord(
        handle=handle,
        entity_type="LINE",
        layer=layer,
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1])),
        normalized_primitives=(primitive,),
        sampled_geometry=((*start, 0.0), (*end, 0.0)),
        source_handles=(handle,),
    )


def _text(handle, text, insert, *, layer="ROLLER"):
    primitive = CadPrimitive(kind="TEXT", attributes={"text": text, "insert": (*insert, 0.0)}, source_handle=handle)
    return CadEntityRecord(
        handle=handle,
        entity_type="TEXT",
        layer=layer,
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(insert[0], insert[1], insert[0], insert[1]),
        normalized_primitives=(primitive,),
        sampled_geometry=((*insert, 0.0),),
        source_handles=(handle,),
    )


def _polyline(handle, points, *, layer="0"):
    vertices = tuple({"point": (*point, 0.0), "bulge": 0.0, "start_width": 0.0, "end_width": 0.0} for point in points)
    primitive = CadPrimitive(kind="LWPOLYLINE", attributes={"vertices": vertices, "closed": True}, source_handle=handle)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return CadEntityRecord(
        handle=handle,
        entity_type="LWPOLYLINE",
        layer=layer,
        color=3,
        line_type="CONTINUOUS",
        layout="Model",
        bbox=BBox(min(xs), min(ys), max(xs), max(ys)),
        normalized_primitives=(primitive,),
        sampled_geometry=tuple((*point, 0.0) for point in points),
        source_handles=(handle,),
    )
