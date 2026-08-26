from __future__ import annotations

import math

import ezdxf

from rollform_extractor.visual_cad_profile_detection import detect_profiles
from rollform_extractor.visual_profile_schema import validate_profile


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
    validate_profile(candidate["profile"])


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


def test_endpoints_inside_tolerance_connect_across_spatial_bucket_boundary(tmp_path):
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    # The drawing extent makes the detector tolerance about 2e-6. These two
    # endpoints differ by only 2e-7 but deliberately straddle a quantization
    # rounding boundary that the previous implementation treated as disconnected.
    modelspace.add_line((0, 0), (1.0000009, 0))
    modelspace.add_line((1.0000011, 0), (2, 0))
    path = tmp_path / "near-connected.dxf"
    document.saveas(path)

    candidates = detect_profiles(path)

    assert len(candidates) == 1
    assert candidates[0]["entity_count"] == 2
    validate_profile(candidates[0]["profile"])


def test_lwpolyline_bulge_is_preserved_as_true_arc(tmp_path):
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    bulge = math.tan(math.pi / 8.0)  # +90-degree CCW arc
    modelspace.add_lwpolyline([(1.0, 0.0, bulge), (0.0, 1.0, 0.0)], format="xyb")
    path = tmp_path / "bulge.dxf"
    document.saveas(path)

    candidates = detect_profiles(path)

    assert len(candidates) == 1
    profile = candidates[0]["profile"]
    assert len(profile["segments"]) == 1
    segment = profile["segments"][0]
    assert segment["type"] == "ARC"
    assert segment["clockwise"] is False
    assert segment["radius"] == pytest.approx(1.0, abs=1e-7)
    assert segment["center"]["x"] == pytest.approx(0.0, abs=1e-7)
    assert segment["center"]["y"] == pytest.approx(0.0, abs=1e-7)
    assert "BULGE_ARC_APPROXIMATED_AS_POLYLINE" not in candidates[0]["warnings"]
    validate_profile(profile)
