from __future__ import annotations

from scripts.run_visual_flower_demo import _strip_length_checks


def _candidate(second_y: float = 0.0):
    constraint = {
        "enabled": True,
        "satisfied": True,
        "relative_error": 0.0,
    }
    return {
        "candidate_id": "demo-length-candidate",
        "geometry_constraints": {
            "enabled": True,
            "satisfied": True,
        },
        "passes": [
            {
                "order": 1,
                "profile": {
                    "topology": "OPEN_PATH",
                    "points": [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]],
                },
                "generation": {"strip_length_constraint": dict(constraint)},
            },
            {
                "order": 2,
                "profile": {
                    "topology": "OPEN_PATH",
                    "points": [[0.0, 0.0], [0.5, second_y], [1.0, 0.0]],
                },
                "generation": {"strip_length_constraint": dict(constraint)},
            },
        ],
    }


def test_demo_strip_length_check_passes_when_geometry_really_matches():
    checks, summary = _strip_length_checks([_candidate(0.0)])
    assert checks["constant_strip_length_metadata"] is True
    assert checks["constant_strip_length_all_passes"] is True
    assert checks["constant_strip_length_tolerance"] is True
    assert summary["maximum_relative_error"] == 0.0
    assert summary["independently_recomputed"] is True


def test_demo_strip_length_check_rejects_false_positive_metadata():
    candidate = _candidate(0.4)
    checks, summary = _strip_length_checks([candidate])
    assert checks["constant_strip_length_metadata"] is True
    assert checks["constant_strip_length_all_passes"] is False
    assert checks["constant_strip_length_tolerance"] is False
    assert summary["maximum_relative_error"] > 1e-6
