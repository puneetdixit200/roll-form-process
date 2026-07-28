from __future__ import annotations

import numpy as np

from rollform_extractor.geometry_normalizer import (
    compose_insert_matrix,
    normalize_primitives,
)
from rollform_extractor.models import CadPrimitive


def test_normalize_line_applies_transform_units_and_samples():
    primitive = CadPrimitive(
        kind="LINE",
        attributes={"start": (0.0, 0.0, 0.0), "end": (2.0, 0.0, 0.0)},
        source_handle="A",
    )
    transform = np.array(
        [
            [0.0, -1.0, 0.0, 10.0],
            [1.0, 0.0, 0.0, 20.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )

    normalized = normalize_primitives([primitive], transform, unit_factor=25.4, spacing=25.4)

    assert normalized.primitives[0].kind == "LINE"
    assert normalized.primitives[0].attributes["start"] == (254.0, 508.0, 0.0)
    assert normalized.primitives[0].attributes["end"] == (254.0, 558.8, 0.0)
    assert normalized.sampled_points == (
        (254.0, 508.0, 0.0),
        (254.0, 533.4, 0.0),
        (254.0, 558.8, 0.0),
    )


def test_normalize_circle_preserves_curve_primitive_and_samples_points():
    primitive = CadPrimitive(
        kind="CIRCLE",
        attributes={"center": (1.0, 1.0, 0.0), "radius": 2.0},
        source_handle="C",
    )

    normalized = normalize_primitives([primitive], np.identity(4), unit_factor=1.0, spacing=2.0)

    assert normalized.primitives[0].kind == "CIRCLE"
    assert normalized.primitives[0].attributes["center"] == (1.0, 1.0, 0.0)
    assert normalized.primitives[0].attributes["radius"] == 2.0
    assert len(normalized.sampled_points) >= 7


def test_normalize_arc_samples_along_arc_not_just_center():
    primitive = CadPrimitive(
        kind="ARC",
        attributes={
            "center": (0.0, 0.0, 0.0),
            "radius": 2.0,
            "start_angle": 0.0,
            "end_angle": 90.0,
        },
        source_handle="A",
    )

    normalized = normalize_primitives([primitive], np.identity(4), unit_factor=1.0, spacing=1.0)

    assert normalized.primitives[0].kind == "ARC"
    assert normalized.sampled_points[0] == (2.0, 0.0, 0.0)
    assert np.allclose(normalized.sampled_points[-1], (0.0, 2.0, 0.0))
    assert len(normalized.sampled_points) >= 4


def test_normalize_ellipse_samples_param_range():
    primitive = CadPrimitive(
        kind="ELLIPSE",
        attributes={
            "center": (0.0, 0.0, 0.0),
            "major_axis": (4.0, 0.0, 0.0),
            "ratio": 0.5,
            "start_param": 0.0,
            "end_param": 1.5707963267948966,
        },
        source_handle="E",
    )

    normalized = normalize_primitives([primitive], np.identity(4), unit_factor=1.0, spacing=1.0)

    assert normalized.primitives[0].kind == "ELLIPSE"
    assert normalized.sampled_points[0] == (4.0, 0.0, 0.0)
    assert np.allclose(normalized.sampled_points[-1], (0.0, 2.0, 0.0))
    assert len(normalized.sampled_points) >= 5


def test_normalize_spline_samples_control_polyline_deterministically():
    primitive = CadPrimitive(
        kind="SPLINE",
        attributes={
            "degree": 2,
            "control_points": ((0.0, 0.0, 0.0), (1.0, 2.0, 0.0), (3.0, 0.0, 0.0)),
            "fit_points": (),
            "knots": (0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            "weights": (1.0, 0.5, 1.0),
        },
        source_handle="S",
    )

    normalized = normalize_primitives([primitive], np.identity(4), unit_factor=1.0, spacing=1.0)

    assert normalized.primitives[0].attributes["weights"] == (1.0, 0.5, 1.0)
    assert normalized.sampled_points[0] == (0.0, 0.0, 0.0)
    assert normalized.sampled_points[-1] == (3.0, 0.0, 0.0)
    assert len(normalized.sampled_points) >= 6


def test_non_uniform_scale_does_not_keep_circle_as_exact_circle():
    primitive = CadPrimitive(
        kind="CIRCLE",
        attributes={"center": (0.0, 0.0, 0.0), "radius": 2.0},
        source_handle="C",
    )
    transform = np.diag([2.0, 3.0, 1.0, 1.0])

    normalized = normalize_primitives([primitive], transform, unit_factor=1.0, spacing=1.0)

    assert normalized.primitives[0].kind == "ELLIPSE"
    assert normalized.primitives[0].attributes["source_kind"] == "CIRCLE"
    assert normalized.primitives[0].attributes["transform_warning"] == "non_uniform_scale"
    assert len(normalized.sampled_points) >= 20


def test_mirrored_arc_does_not_keep_unmirrored_exact_arc():
    primitive = CadPrimitive(
        kind="ARC",
        attributes={
            "center": (0.0, 0.0, 0.0),
            "radius": 2.0,
            "start_angle": 0.0,
            "end_angle": 90.0,
        },
        source_handle="A",
    )
    transform = np.diag([-1.0, 1.0, 1.0, 1.0])

    normalized = normalize_primitives([primitive], transform, unit_factor=1.0, spacing=1.0)

    assert normalized.primitives[0].kind == "ELLIPSE_ARC"
    assert normalized.primitives[0].attributes["source_kind"] == "ARC"
    assert normalized.primitives[0].attributes["transform_warning"] == "orientation_reversing"
    assert normalized.sampled_points[0] == (-2.0, 0.0, 0.0)
    assert np.allclose(normalized.sampled_points[-1], (0.0, 2.0, 0.0))


def test_close_endpoints_are_joined_only_in_sampled_geometry():
    first = CadPrimitive(
        kind="LINE",
        attributes={"start": (0.0, 0.0, 0.0), "end": (1.0, 0.0, 0.0)},
        source_handle="A",
    )
    second = CadPrimitive(
        kind="LINE",
        attributes={"start": (1.04, 0.0, 0.0), "end": (2.0, 0.0, 0.0)},
        source_handle="B",
    )

    normalized = normalize_primitives(
        [first, second],
        np.identity(4),
        unit_factor=1.0,
        spacing=1.0,
        join_tolerance=0.05,
    )

    assert normalized.primitives[1].attributes["start"] == (1.04, 0.0, 0.0)
    assert normalized.sampled_points[2] == (1.0, 0.0, 0.0)


def test_compose_insert_matrix_detects_mirror_rotation_and_scale():
    class Insert:
        class Dxf:
            insert = (10.0, 20.0, 0.0)
            rotation = 90.0
            xscale = -2.0
            yscale = 3.0
            zscale = 1.0

        dxf = Dxf()

    matrix = compose_insert_matrix(Insert(), np.identity(4))

    assert np.round(matrix, 6).tolist() == [
        [-0.0, -3.0, 0.0, 10.0],
        [-2.0, 0.0, 0.0, 20.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    assert np.linalg.det(matrix[:3, :3]) < 0
