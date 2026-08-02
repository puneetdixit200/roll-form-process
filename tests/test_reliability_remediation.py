from __future__ import annotations

import json
from pathlib import Path

from rollform_extractor.pass_alignment import align_passes_to_stations, build_alignment_candidates, validate_alignment
from rollform_extractor.review_apply import apply_review_decisions


def _candidate(pass_id: str, station_id: str, pass_order: int, station_order: int, score: float) -> dict:
    return {
        "composite_flower_id": "CF1",
        "pass_id": pass_id,
        "profile_id": f"{pass_id}-profile",
        "pass_order": pass_order,
        "candidate_profile_id": f"{station_id}-profile",
        "candidate_station_id": station_id,
        "candidate_sequence_id": "SEQ1",
        "candidate_station_order": station_order,
        "geometry_similarity": score,
        "evidence_coverage": 1.0,
    }


def test_alignment_uses_global_monotonic_solution_not_first_candidate():
    rows = [
        _candidate("p0", "S1", 0, 0, 0.70),
        _candidate("p0", "S2", 0, 1, 0.99),
        _candidate("p1", "S1", 1, 0, 0.98),
        _candidate("p1", "S2", 1, 1, 0.70),
    ]
    result = align_passes_to_stations(("p0", "p1"), ("S1", "S2"), build_alignment_candidates(rows), minimum_pair_score=0.0)
    assert [(item.pass_id, item.candidate_station_id) for item in result.matches] == [("p0", "S1"), ("p1", "S2")]
    assert validate_alignment(result) == ()


def test_repeated_station_occurrences_are_not_deduplicated():
    rows = [
        _candidate("p0", "S14", 0, 0, 0.9),
        _candidate("p1", "S15", 1, 1, 0.9),
        _candidate("p2", "S16", 2, 2, 0.9),
    ]
    result = align_passes_to_stations(("p0", "p1", "p2"), ("S14", "S15", "S16"), build_alignment_candidates(rows))
    assert len(result.matches) == 3
    assert [item.candidate_station_id for item in result.matches] == ["S14", "S15", "S16"]


def test_dry_run_review_is_side_effect_free(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"source_sha256": "abc", "profiles": [], "stations": []}), encoding="utf-8")
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"schema_version": 2, "pass_order_decisions": []}), encoding="utf-8")
    result = apply_review_decisions(project, decisions, dry_run=True)
    assert result["dry_run"] is True
    assert not (project / "review").exists()
