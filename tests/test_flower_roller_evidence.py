from __future__ import annotations

from rollform_extractor.flower_roller_evidence import build_candidate_roller_evidence
from rollform_extractor.visual_flower_exports import export_visual_run, verify_visual_export


def test_confirmed_historical_usage_outranks_geometry_candidate():
    candidate = {
        "candidate_id": "candidate-1",
        "passes": [
            {
                "pass_id": "pass-01",
                "order": 1,
                "historical_match": {
                    "best_match": {
                        "source_flower_id": "FLOWER-A",
                        "source_pass_id": "pass-03",
                        "overall_score": 0.91,
                    }
                },
            }
        ],
    }
    dataset = {
        "dataset_hash": "dataset-hash",
        "roller_station_evidence": [
            {
                "flower_id": "FLOWER-A",
                "pass_id": "pass-03",
                "role": "UPPER",
                "design_id": "RD-CONFIRMED",
                "geometry_revision_id": "rev-1",
                "confirmation_status": "CONFIRMED",
                "association_method": "EXACT_STATION_ID",
            },
            {
                "flower_id": "FLOWER-A",
                "pass_id": "pass-03",
                "role": "UPPER",
                "design_id": "RD-GEOMETRY",
                "recognition_score": 0.98,
                "evidence_coverage": 0.8,
                "recognition_status": "HIGH_SIMILARITY_CANDIDATE",
                "association_method": "HISTORICAL_PASS_ORDER",
            },
        ],
    }

    evidence = build_candidate_roller_evidence(candidate, historical_dataset=dataset)

    role = evidence["stations"][0]["roles"][0]
    assert role["candidates"][0]["design_id"] == "RD-CONFIRMED"
    assert role["candidates"][0]["evidence_tier"] == "TIER_3_CONFIRMED_HISTORICAL_USAGE_FROM_MATCHED_PASS"
    assert evidence["manufacturing_approval"] == "NOT_APPROVED"


def test_absence_of_supported_evidence_is_explicit_abstention():
    evidence = build_candidate_roller_evidence(
        {"candidate_id": "candidate-1", "passes": [{"pass_id": "pass-01", "order": 1, "historical_match": {}}]},
        historical_dataset={"dataset_hash": "empty"},
    )

    assert evidence["stations"][0]["status"] == "INSUFFICIENT_ROLLER_EVIDENCE"
    assert evidence["stations"][0]["roles"] == []


def test_export_includes_design_only_roller_evidence_csv(tmp_path):
    candidate = {
        "candidate_id": "candidate-1",
        "visual_confidence": {"score": 0.8, "band": "HIGH"},
        "geometry_constraints": {"enabled": True, "satisfied": True, "target_length": 1.0},
        "passes": [{"pass_id": "pass-01", "order": 1, "progress": 0.0, "profile": {"points": [[0, 0], [1, 0]], "topology": "OPEN_PATH"}, "historical_match": {}, "visual_confidence": {"score": 0.8, "band": "HIGH"}, "generation": {"strip_length_constraint": {"actual_length": 1.0, "satisfied": True, "relative_error": 0.0}}, "warnings": []}],
    }
    candidate["roller_evidence"] = build_candidate_roller_evidence(candidate, historical_dataset={"dataset_hash": "empty"})

    export_visual_run({"candidates": [candidate], "source_cad_included": False}, tmp_path)

    assert (tmp_path / "roller_evidence.csv").is_file()
    assert "evidence_tier" in (tmp_path / "roller_evidence.csv").read_text()
    assert verify_visual_export(tmp_path)["checks"]["roller_evidence_csv"] is True
