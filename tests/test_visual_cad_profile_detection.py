from __future__ import annotations

import ezdxf

from rollform_extractor.visual_cad_profile_detection import detect_profiles


def test_connected_line_arc_line_is_one_open_profile(tmp_path):
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (10, 0), dxfattribs={"layer": "PROFILE"})
    modelspace.add_arc((10, 5), 5, 270, 360, dxfattribs={"layer": "PROFILE"})
    modelspace.add_line((15, 5), (20, 5), dxfattribs={"layer": "PROFILE"})
    path = tmp_path / "connected.dxf"
    document.saveas(path)

    candidates = detect_profiles(path)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["open_closed"] == "OPEN_PATH"
    assert candidate["entity_count"] == 3
    assert candidate["profile"]["segments"][1]["type"] == "ARC"
    assert candidate["profile"]["metadata"]["source_layers"] == ["PROFILE"]


def test_branching_geometry_is_kept_as_review_required_candidate(tmp_path):
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (10, 0))
    modelspace.add_line((10, 0), (20, 0))
    modelspace.add_line((10, 0), (10, 10))
    path = tmp_path / "branched.dxf"
    document.saveas(path)

    candidates = detect_profiles(path)

    assert len(candidates) == 1
    assert "BRANCHED_PROFILE_REVIEW_REQUIRED" in candidates[0]["warnings"]
