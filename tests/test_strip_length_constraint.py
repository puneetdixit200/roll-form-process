from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from rollform_extractor.clrsg_inference import _learned_candidate
from rollform_extractor.strip_length_constraint import (
    STRIP_LENGTH_RELATIVE_TOLERANCE,
    centerline_length,
    project_constant_strip_length,
)
from rollform_extractor.visual_flower_engine import (
    generate_visual_candidates,
    legacy_progress_points,
)
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


def _open_profile():
    vertices = [
        {"vertex_id": f"v-{index}", "x": x, "y": y}
        for index, (x, y) in enumerate(((-2, 0), (-1, 1), (0, 1), (1, 1), (2, 0)))
    ]
    segments = [
        {
            "segment_id": f"s-{index}",
            "type": "LINE",
            "start_vertex_id": vertices[index]["vertex_id"],
            "end_vertex_id": vertices[index + 1]["vertex_id"],
        }
        for index in range(len(vertices) - 1)
    ]
    return {
        "schema_version": 1,
        "profile_id": "constant-length-open-target",
        "name": "Constant length open target",
        "topology": "OPEN_PATH",
        "closed": False,
        "computational_seam_vertex_id": None,
        "vertices": vertices,
        "segments": segments,
        "metadata": {"source": "PUBLIC_SYNTHETIC_TEST", "visual_only": True},
    }


def _open_history():
    target = canonicalize_profile(validate_profile(_open_profile()), samples=32)
    vector = [value for point in target["points"] for value in point]
    return [
        {
            "flower_id": "SYNTHETIC-LENGTH-HISTORY",
            "topology": "OPEN_PATH",
            "passes": [
                {
                    "pass_id": f"p-{index:02d}",
                    "topology": "OPEN_PATH",
                    "shape_vector": vector,
                    "width": 1,
                    "height": 1,
                }
                for index in range(12)
            ],
        }
    ]


def test_open_projection_preserves_total_and_local_material_lengths():
    target = [[-2.0, 0.0], [-1.0, 1.0], [0.0, 1.0], [1.0, 1.0], [2.0, 0.0]]
    predicted = [[-1.0, 0.0], [-0.5, 0.0], [0.0, 0.0], [0.5, 0.0], [1.0, 0.0]]
    projected, metadata = project_constant_strip_length(predicted, target, "OPEN_PATH")
    assert metadata["satisfied"] is True
    assert metadata["local_segment_lengths_preserved"] is True
    assert abs(centerline_length(projected) - centerline_length(target)) <= 1e-8
    expected = [
        np.linalg.norm(np.asarray(right) - np.asarray(left))
        for left, right in zip(target, target[1:])
    ]
    actual = [
        np.linalg.norm(np.asarray(right) - np.asarray(left))
        for left, right in zip(projected, projected[1:])
    ]
    assert np.allclose(actual, expected, atol=1e-8, rtol=1e-8)


def test_deterministic_open_candidates_keep_final_centerline_length_for_8_16_28():
    profile = validate_profile(_open_profile())
    target = canonicalize_profile(profile, samples=256)["points"]
    expected = centerline_length(target, "OPEN_PATH")
    for station_count in (8, 16, 28):
        result = generate_visual_candidates(
            profile,
            _open_history(),
            station_mode="EXACT",
            exact_station_count=station_count,
            candidate_limit=1,
        )
        candidate = result["candidates"][0]
        assert candidate["geometry_constraints"]["enabled"] is True
        assert candidate["geometry_constraints"]["satisfied"] is True
        assert candidate["geometry_constraints"]["maximum_relative_error"] <= STRIP_LENGTH_RELATIVE_TOLERANCE
        assert candidate["passes"][-1]["profile"]["points"] == [list(point) for point in target]
        for item in candidate["passes"]:
            actual = centerline_length(item["profile"]["points"], "OPEN_PATH")
            assert abs(actual - expected) / expected <= STRIP_LENGTH_RELATIVE_TOLERANCE
            assert item["generation"]["strip_length_constraint"]["satisfied"] is True


def test_closed_candidate_preserves_perimeter_without_collapsing_progression():
    fixture = Path(__file__).parent / "fixtures" / "visual_profiles" / "closed_with_seam.json"
    profile = validate_profile(json.loads(fixture.read_text(encoding="utf-8")))
    closed_history = [
        {
            "flower_id": "SYNTHETIC-CLOSED",
            "topology": "CLOSED_CONTOUR",
            "passes": [
                {
                    "pass_id": "p1",
                    "topology": "CLOSED_CONTOUR",
                    "shape_vector": [0, 0, 1, 0, 1, 1, 0, 1],
                    "width": 1,
                    "height": 1,
                }
            ],
        }
    ]
    result = generate_visual_candidates(
        profile,
        closed_history,
        station_mode="EXACT",
        exact_station_count=8,
        candidate_limit=1,
    )
    candidate = result["candidates"][0]
    target = candidate["passes"][-1]["profile"]["points"]
    expected = centerline_length(target, "CLOSED_CONTOUR")
    assert candidate["geometry_constraints"]["satisfied"] is True
    assert candidate["passes"][0]["profile"]["points"] != target
    for item in candidate["passes"]:
        actual = centerline_length(item["profile"]["points"], "CLOSED_CONTOUR")
        assert abs(actual - expected) / expected <= STRIP_LENGTH_RELATIVE_TOLERANCE


def test_learned_candidate_uses_legacy_residual_reference_then_projects_length():
    profile = validate_profile(_open_profile())
    target = [list(point) for point in canonicalize_profile(profile, samples=256)["points"]]
    baseline_result = generate_visual_candidates(
        profile,
        _open_history(),
        station_mode="EXACT",
        exact_station_count=8,
        candidate_limit=1,
    )
    baseline = baseline_result["candidates"][0]
    residual = np.zeros((28, 128, 2), dtype=float)
    residual[:, :, 1] = 0.08 * np.sin(np.linspace(0.0, 8.0 * np.pi, 128))[None, :]
    prediction = {
        "residual": residual,
        "condition_distance": 0.4,
        "ensemble_disagreement": 0.01,
        "ood_status": "IN_DISTRIBUTION",
        "model_id": "synthetic-clrsg",
    }
    learned = _learned_candidate(
        baseline,
        prediction,
        alpha=0.85,
        kind="CLRSG_LEARNED_MEAN",
        target_points=target,
        topology="OPEN_PATH",
    )
    expected = centerline_length(target, "OPEN_PATH")
    assert learned["learned_support"]["residual_reference"] == "LEGACY_UNCONSTRAINED_BASELINE_V1"
    assert learned["learned_support"]["post_prediction_constraint"] == "constant_centerline_length_v1"
    assert learned["geometry_constraints"]["satisfied"] is True
    for item in learned["passes"]:
        actual = centerline_length(item["profile"]["points"], "OPEN_PATH")
        assert abs(actual - expected) / expected <= STRIP_LENGTH_RELATIVE_TOLERANCE


def test_legacy_baseline_reference_is_unchanged_for_approved_model():
    target = [[-2.0, 0.0], [-1.0, 1.0], [0.0, 1.0], [1.0, 1.0], [2.0, 0.0]]
    flat = legacy_progress_points(target, 0.0, "OPEN_PATH", "UNIFORM_PROGRESSION")
    assert flat == ((-1.0, 0.0), (-0.5, 0.0), (0.0, 0.0), (0.5, 0.0), (1.0, 0.0))
    closed = legacy_progress_points(target, 0.0, "CLOSED_CONTOUR", "UNIFORM_PROGRESSION")
    assert closed[0] == (-1.7, 0.0)
