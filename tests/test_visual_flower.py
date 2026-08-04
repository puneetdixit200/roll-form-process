from __future__ import annotations

from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import VisualProfileError, validate_profile


def profile(topology="OPEN_PATH"):
    vertices = [{"vertex_id": f"v-{i}", "x": x, "y": y} for i, (x, y) in enumerate(((-2, 0), (-1, 1), (0, 0), (1, 1), (2, 0)))]
    segments = [{"segment_id": f"s-{i}", "type": "LINE", "start_vertex_id": vertices[i]["vertex_id"], "end_vertex_id": vertices[i + 1]["vertex_id"]} for i in range(len(vertices) - 1)]
    return {"schema_version": 1, "profile_id": "synthetic-target", "name": "Synthetic", "topology": topology, "closed": topology == "CLOSED_CONTOUR", "computational_seam_vertex_id": vertices[0]["vertex_id"] if topology == "CLOSED_CONTOUR" else None, "vertices": vertices, "segments": segments, "metadata": {"source": "PUBLIC_SYNTHETIC_TEST", "visual_only": True}}


def historical():
    canonical = canonicalize_profile(validate_profile(profile()), samples=32)
    return [{"flower_id": "SYNTHETIC-FLOWER-001", "topology": "OPEN_PATH", "passes": [{"pass_id": f"p-{i}", "topology": "OPEN_PATH", "shape_vector": [v for point in canonical["points"] for v in point], "width": 1, "height": 1} for i in range(12)]}]


def test_profile_validation_rejects_bad_references_and_accepts_example():
    value = validate_profile(profile())
    assert value.topology == "OPEN_PATH"
    broken = profile(); broken["segments"][0]["end_vertex_id"] = "missing"
    try:
        validate_profile(broken)
    except VisualProfileError as exc:
        assert exc.code == "INVALID_SEGMENT_REFERENCE"
    else:
        raise AssertionError("invalid reference accepted")


def test_translation_normalization_is_stable():
    first = canonicalize_profile(validate_profile(profile()), samples=64)
    translated = profile(); translated["vertices"] = [{**point, "x": point["x"] + 1000, "y": point["y"] - 500} for point in translated["vertices"]]
    assert canonicalize_profile(validate_profile(translated), samples=64)["points"] == first["points"]


def test_visual_generation_supports_exact_station_counts_and_provenance():
    target = validate_profile(profile())
    for count in (8, 16, 28):
        result = generate_visual_candidates(target, historical(), station_mode="EXACT", exact_station_count=count, candidate_limit=1)
        candidate = result["candidates"][0]
        assert candidate["station_count"] == count
        assert len(candidate["passes"]) == count
        assert candidate["passes"][-1]["profile"]["points"] == result["candidates"][0]["passes"][-1]["profile"]["points"]
        assert all("historical_match" in item for item in candidate["passes"])
        assert 0 <= candidate["visual_confidence"]["score"] <= 100
