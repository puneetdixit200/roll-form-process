from __future__ import annotations

from rollform_extractor.composite_flower import build_composite_flowers
from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive, ProfileRecord, StationRecord
from rollform_extractor.transition_analysis import bend_change_events, profile_step_changes


def test_flat_closed_strip_outline_has_constant_thickness_and_zero_physical_bends():
    composite = _flower_from_outlines((("P0", _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1)])),))
    item = composite.passes[0]

    assert item.profile_type == "CLOSED_STRIP_PROFILE"
    assert item.sheet_thickness == 1.0
    assert item.thickness_method == "explicit_end_cap_distance"
    assert item.thickness_sampling_count == 2
    assert item.height == 1.0
    assert item.raw_geometry_corner_count >= 0
    assert item.physical_forming_bend_count == 0
    assert item.physical_total_bend_angle == 0


def test_endpoint_closed_strip_outline_works_when_dxf_closed_flag_is_false():
    points = _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1), (0, 0)])
    primitive = CadPrimitive(
        "LWPOLYLINE",
        {"vertices": tuple({"point": (x, y, 0.0), "bulge": 0.0} for x, y in points), "closed": False},
        "H0",
    )
    entity = CadEntityRecord(
        "H0",
        "LWPOLYLINE",
        "FLOWER",
        7,
        "CONTINUOUS",
        "model",
        _bbox(points),
        (primitive,),
        (primitive,),
        tuple((x, y, 0.0) for x, y in points),
        source_handles=("H0",),
    )
    profile = ProfileRecord(
        "P0",
        "S1",
        ("H0",),
        "composite_flower_detector",
        "config",
        0.86,
        {
            "normalized_primitives": (primitive,),
            "bbox": _bbox(points),
            "profile_state": "CENTERLINE_PROFILE",
            "composite_pass_index": 0,
            "composite_pass_count": 1,
        },
    )
    station = StationRecord("S1", 1, _bbox(points), ("H0",), "test", "config", 0.9, {"region_type": "COMPOSITE_FLOWER"})

    item = build_composite_flowers((station,), (profile,), (entity,))[0].passes[0]

    assert item.neutral_line_method == "paired_boundary_midline"
    assert item.sheet_thickness == 1.0
    assert item.physical_forming_bend_count == 0


def test_strip_thickness_is_not_profile_height_when_profile_forms_upward():
    composite = _flower_from_outlines(
        (
            ("P0", _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1)])),
            ("P1", _strip_outline([(0, 0), (10, 10), (20, 0), (20, -1), (10, 9), (0, -1)])),
        )
    )
    flat, formed = composite.passes

    assert flat.sheet_thickness == 1.0
    assert formed.height > 10
    assert abs((formed.sheet_thickness or 0) - 1.0) < 0.05
    assert formed.sheet_thickness != formed.height
    assert formed.physical_forming_bend_count == 1


def test_bend_ids_are_material_coordinate_stable_across_gradual_forming():
    composite = _flower_from_outlines(
        (
            ("P1", _strip_outline([(0, 0), (10, 5), (20, 0), (20, -1), (10, 4), (0, -1)])),
            ("P2", _strip_outline([(0, 0), (10, 8), (20, 0), (20, -1), (10, 7), (0, -1)])),
        )
    )
    first, second = composite.passes
    events = bend_change_events(composite.passes)

    assert [bend["bend_id"] for bend in first.physical_bends] == ["BZ01"]
    assert [bend["bend_id"] for bend in second.physical_bends] == ["BZ01"]
    assert events[0]["bend_id"] == "BZ01"
    assert events[0]["change_classification"] in {"BEND_INCREASED", "BEND_DECREASED"}


def test_material_coordinate_change_ignores_rigid_translation_but_reports_profile_deltas():
    composite = _flower_from_outlines(
        (
            ("P1", _strip_outline([(0, 0), (10, 5), (20, 0), (20, -1), (10, 4), (0, -1)])),
            ("P2", _strip_outline([(5, 3), (15, 8), (25, 3), (25, 2), (15, 7), (5, 2)])),
        )
    )
    change = profile_step_changes(composite.passes)[0]

    assert change["topology_change"] is False
    assert change["centroid_movement"]["distance"] > 0
    assert "TOPOLOGY_CHANGE" not in change["classifications"]


def test_bend_activation_and_deactivation_are_reported():
    composite = _flower_from_outlines(
        (
            ("P0", _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1)])),
            ("P1", _strip_outline([(0, 0), (10, 8), (20, 0), (20, -1), (10, 7), (0, -1)])),
            ("P2", _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1)])),
        )
    )
    events = bend_change_events(composite.passes)

    assert any(event["change_classification"] == "NEW_BEND_ACTIVATED" for event in events)
    assert any(event["change_classification"] == "BEND_DEACTIVATED" for event in events)


def test_chamfered_corner_becomes_one_bend_zone_with_summed_angle():
    composite = _flower_from_centerlines(
        (
            (
                "P1",
                _strip_outline(
                        [
                            (0, 0),
                            (8, 0),
                            (9, 0.4),
                            (10, 1.2),
                            (18, 7.6),
                        ]
                    ),
                ),
            )
        )
    item = composite.passes[0]

    assert item.vertex_turn_count > item.physical_forming_bend_count
    assert item.physical_forming_bend_count == 1
    zone = item.physical_bends[0]
    assert zone["bend_zone_id"] == "BZ01"
    assert zone["contributing_vertex_count"] >= 2
    assert 1 < zone["zone_length"] < 13
    assert abs(zone["signed_bend_angle"]) > 5


def test_opposite_direction_bends_remain_separate_zones():
    composite = _flower_from_centerlines(
        (
            (
                "P1",
                _strip_outline(
                        [
                            (0, 0),
                            (6, 0),
                            (8, 2),
                            (10, 0),
                            (16, -6),
                        ]
                    ),
                ),
            )
    )

    assert composite.passes[0].physical_forming_bend_count == 2


def test_long_straight_segment_separates_bend_zones():
    composite = _flower_from_centerlines(
        (
            (
                "P1",
                _strip_outline(
                        [
                                    (0, 0),
                                    (5, 0),
                                    (7, 2),
                                    (25, 20),
                                    (27, 25),
                                    (35, 45),
                        ]
                    ),
                ),
            )
    )

    assert composite.passes[0].physical_forming_bend_count == 2


def test_neutral_length_uses_boundary_average_and_excludes_end_caps():
    composite = _flower_from_outlines((("P0", _strip_outline([(0, 0), (20, 0), (20, 1), (0, 1)])),))
    item = composite.passes[0]

    assert item.expected_neutral_length == 20
    assert item.neutral_line_developed_length == 20
    assert item.neutral_length_error == 0
    assert item.neutral_length_error_percent == 0


def test_vertex_count_changes_do_not_create_false_topology_change():
    composite = _flower_from_centerlines(
        (
            ("P1", _strip_outline([(0, 0), (8, 0), (10, 2), (18, 10)])),
            ("P2", _strip_outline([(0, 0), (7, 0), (8, 0.2), (9, 0.8), (10, 2), (18, 10)])),
        )
    )
    change = profile_step_changes(composite.passes)[0]

    assert composite.passes[0].physical_forming_bend_count == composite.passes[1].physical_forming_bend_count
    assert change["topology_change"] is False
    assert "TOPOLOGY_CHANGE" not in change["classifications"]


def _flower_from_outlines(items):
    entities = []
    profiles = []
    source_handles = []
    for index, (profile_id, points) in enumerate(items):
        handle = f"H{index}"
        primitive = _outline_primitive(handle, points)
        bbox = _bbox(points)
        entities.append(
            CadEntityRecord(
                handle,
                "LWPOLYLINE",
                "FLOWER",
                7,
                "CONTINUOUS",
                "model",
                bbox,
                (primitive,),
                (primitive,),
                tuple((x, y, 0.0) for x, y in points),
                source_handles=(handle,),
            )
        )
        profiles.append(
            ProfileRecord(
                profile_id,
                "S1",
                (handle,),
                "composite_flower_detector",
                "config",
                0.86,
                {
                    "normalized_primitives": (primitive,),
                    "original_primitives": (primitive,),
                    "exact_length": 0.0,
                    "bbox": bbox,
                    "bend_angles": (90.0, 90.0, 90.0, 90.0),
                    "profile_state": "CLOSED_STRIP_PROFILE",
                    "composite_pass_index": index,
                    "composite_pass_count": len(items),
                },
            )
        )
        source_handles.append(handle)
    station = StationRecord(
        "S1",
        1,
        _bbox([point for _pid, points in items for point in points]),
        tuple(source_handles),
        "test",
        "config",
        0.9,
        {"region_type": "COMPOSITE_FLOWER", "sequence_id": 1},
    )
    return build_composite_flowers((station,), tuple(profiles), tuple(entities))[0]


def _flower_from_centerlines(items):
    entities = []
    profiles = []
    source_handles = []
    for index, (profile_id, points) in enumerate(items):
        handle = f"C{index}"
        primitive = CadPrimitive(
            "LWPOLYLINE",
            {"vertices": tuple({"point": (x, y, 0.0), "bulge": 0.0} for x, y in points), "closed": False},
            handle,
        )
        bbox = _bbox(points)
        entities.append(
            CadEntityRecord(
                handle,
                "LWPOLYLINE",
                "FLOWER",
                7,
                "CONTINUOUS",
                "model",
                bbox,
                (primitive,),
                (primitive,),
                tuple((x, y, 0.0) for x, y in points),
                source_handles=(handle,),
            )
        )
        profiles.append(
            ProfileRecord(
                profile_id,
                "S1",
                (handle,),
                "composite_flower_detector",
                "config",
                0.86,
                {
                    "normalized_primitives": (primitive,),
                    "original_primitives": (primitive,),
                    "bbox": bbox,
                    "bend_angles": (30.0, 30.0),
                    "profile_state": "TRUE_CENTERLINE_PROFILE",
                    "composite_pass_index": index,
                    "composite_pass_count": len(items),
                },
            )
        )
        source_handles.append(handle)
    station = StationRecord("S1", 1, _bbox([point for _pid, points in items for point in points]), tuple(source_handles), "test", "config", 0.9, {"region_type": "COMPOSITE_FLOWER"})
    return build_composite_flowers((station,), tuple(profiles), tuple(entities))[0]


def _outline_primitive(handle: str, points) -> CadPrimitive:
    return CadPrimitive(
        "LWPOLYLINE",
        {"vertices": tuple({"point": (x, y, 0.0), "bulge": 0.0} for x, y in points), "closed": True},
        handle,
    )


def _strip_outline(points):
    return tuple((float(x), float(y)) for x, y in points)


def _bbox(points) -> BBox:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))
