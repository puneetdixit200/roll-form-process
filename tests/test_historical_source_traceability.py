from rollform_extractor.flower_roller_evidence import build_candidate_roller_evidence
from rollform_extractor.historical_source_traceability import source_reference_id


def test_source_reference_id_is_stable_and_opaque():
    first = source_reference_id("dataset", "F1", "P1", "UPPER", "RD1", "REV1")
    assert first == source_reference_id("dataset", "F1", "P1", "UPPER", "RD1", "REV1")
    assert first.startswith("hsr-")
    assert "/" not in first


def test_grouped_candidate_preserves_all_historical_origins_and_top3_support():
    candidate = {"candidate_id": "C1", "passes": [{
        "pass_id": "generated-1", "order": 1,
        "historical_match": {"top_matches": [
            {"source_flower_id": "F1", "source_pass_id": "P1", "overall_score": .91},
            {"source_flower_id": "F2", "source_pass_id": "P2", "overall_score": .90},
            {"source_flower_id": "F3", "source_pass_id": "P3", "overall_score": .89},
        ]},
    }]}
    dataset = {"dataset_hash": "D", "roller_station_evidence": [
        {"flower_id": "F1", "pass_id": "P1", "role": "UPPER", "design_id": "RD", "geometry_revision_id": "R1", "recognition_score": .9},
        {"flower_id": "F2", "pass_id": "P2", "role": "UPPER", "design_id": "RD", "geometry_revision_id": "R1", "recognition_score": .8},
        {"flower_id": "F3", "pass_id": "P3", "role": "UPPER", "design_id": "RD", "geometry_revision_id": "R1", "recognition_score": .7},
    ]}
    result = build_candidate_roller_evidence(candidate, historical_dataset=dataset)
    item = result["stations"][0]["roles"][0]["candidates"][0]
    assert item["top3_support_count"] == 3
    assert item["supporting_match_ranks"] == [1, 2, 3]
    assert len(item["supporting_origins"]) == 3
    assert len({origin["source_reference_id"] for origin in item["supporting_origins"]}) == 3
    assert result["algorithm_version"] == "flower-roller-evidence-v3"
