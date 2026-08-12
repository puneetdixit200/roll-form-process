from __future__ import annotations

import csv
import json

from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_flower_exports import export_visual_run, verify_visual_export
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


def _profile():
    vertices = [
        {"vertex_id": f"v-{index}", "x": x, "y": y}
        for index, (x, y) in enumerate(((-2, 0), (-1, 1), (0, 1.2), (1, 1), (2, 0)))
    ]
    return {
        "schema_version": 1,
        "profile_id": "strip-export-target",
        "name": "Strip export target",
        "topology": "OPEN_PATH",
        "closed": False,
        "computational_seam_vertex_id": None,
        "vertices": vertices,
        "segments": [
            {
                "segment_id": f"s-{index}",
                "type": "LINE",
                "start_vertex_id": vertices[index]["vertex_id"],
                "end_vertex_id": vertices[index + 1]["vertex_id"],
            }
            for index in range(len(vertices) - 1)
        ],
        "metadata": {"source": "PUBLIC_SYNTHETIC_TEST", "visual_only": True},
    }


def _history():
    canonical = canonicalize_profile(validate_profile(_profile()), samples=32)
    vector = [value for point in canonical["points"] for value in point]
    return [
        {
            "flower_id": "SYNTHETIC-EXPORT-HISTORY",
            "topology": "OPEN_PATH",
            "passes": [
                {
                    "pass_id": f"p-{index}",
                    "topology": "OPEN_PATH",
                    "shape_vector": vector,
                    "width": 1,
                    "height": 1,
                }
                for index in range(12)
            ],
        }
    ]


def test_exports_include_constant_strip_length_evidence(tmp_path):
    result = generate_visual_candidates(
        validate_profile(_profile()),
        _history(),
        station_mode="EXACT",
        exact_station_count=8,
        candidate_limit=1,
    )
    export_visual_run(result, tmp_path)
    verification = verify_visual_export(tmp_path)
    assert verification["status"] == "PASS"
    assert verification["checks"]["constant_strip_length"] is True
    assert verification["checks"]["html_strip_length"] is True

    with (tmp_path / "passes.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert all(row["strip_length_satisfied"] == "True" for row in rows)
    assert all(float(row["strip_length_relative_error"]) <= 1e-6 for row in rows)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["constant_strip_length"]["enabled"] is True
    assert manifest["constant_strip_length"]["all_candidates_satisfied"] is True
