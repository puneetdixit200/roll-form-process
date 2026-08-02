from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.database import create_project_database
from rollform_extractor.roller_recognition import (
    InventoryRevisionCandidate,
    eligible_inventory_revisions,
    evaluate_recognition,
    prepare_recognition_input,
    recognize_occurrence,
    retrieve_candidates,
)


CONFIG = ExtractionConfig.load().roller_recognition


def occurrence(identifier: str, *, units: str = "CONFIRMED", bore: float | None = 40, role: str | None = "upper_upper", shape=(0.0, 1.0, 0.0, 1.0), physical_fingerprint: str | None = None, shape_fingerprint: str | None = None):
    return SimpleNamespace(
        occurrence_id=identifier,
        station_id="S1",
        role=role,
        source_handles=(f"H-{identifier}",),
        confidence=0.95,
        evidence={
            "outer_diameter_mm": 100.0,
            "bore_diameter_mm": bore,
            "width_mm": 60.0,
            "units_status": units,
            "shape_vector": list(shape),
            "physical_fingerprint": physical_fingerprint,
            "shape_fingerprint": shape_fingerprint,
            "geometry_descriptor": {"design_id": identifier if identifier.startswith("DES-") else ""},
        },
    )


def revision(design: str, revision_id: str, *, diameter=100, bore=40, shape=(0.0, 1.0, 0.0, 1.0), status="VERIFIED", eligibility="VERIFIED_ELIGIBLE", role="upper_upper", confidence=.95, fingerprint=None):
    return InventoryRevisionCandidate(design, design, "WORKING", revision_id, {"outer_diameter_mm": diameter, "bore_diameter_mm": bore, "face_width_mm": 60.0}, {"role": role}, tuple(shape), fingerprint, None, "CONFIRMED", status, eligibility, confidence, (f"alias-{design.lower()}",), role=role)


def test_preparation_keeps_missing_data_explicit_and_fingerprint_deterministic():
    item = prepare_recognition_input("P1", occurrence("O1", bore=None), units_status="CONFIRMED", configuration_hash="cfg")
    assert item.quality == "PARTIAL"
    assert "MISSING_BORE" in item.quality_flags
    assert len(item.input_hash) == 64
    assert item.input_hash == prepare_recognition_input("P1", occurrence("O1", bore=None), units_status="CONFIRMED", configuration_hash="cfg").input_hash


def test_exact_identifier_and_fingerprint_are_separate_evidence():
    exact = revision("DES-1", "REV-1", fingerprint="physical-1")
    with_id = prepare_recognition_input("P", occurrence("DES-1"), units_status="CONFIRMED")
    result = recognize_occurrence(with_id, [exact], CONFIG)
    assert result.status == "EXACT_IDENTIFIER_MATCH"
    assert result.candidates[0].design_id == "DES-1"
    assert result.candidates[0].explanation["candidate_only"] is True
    fingerprint_item = prepare_recognition_input("P", occurrence("O-FP", physical_fingerprint="physical-1"), units_status="CONFIRMED")
    fingerprint_result = recognize_occurrence(fingerprint_item, [exact], CONFIG)
    assert fingerprint_result.status == "EXACT_VERIFIED_FINGERPRINT"
    assert fingerprint_result.candidates[0].components["physical_fingerprint_exact"].available is True


def test_multiple_revisions_return_one_design_candidate_with_revision_evidence():
    item = prepare_recognition_input("P", occurrence("O1"), units_status="CONFIRMED")
    result = recognize_occurrence(item, [revision("DES-1", "REV-2", shape=(0.01, 1, 0, 1)), revision("DES-1", "REV-1")], CONFIG)
    assert len(result.candidates) == 1
    assert result.candidates[0].design_id == "DES-1"
    assert result.candidates[0].geometry_revision_id == "REV-1"


def test_wrong_bore_is_hard_filtered_but_missing_bore_is_not_a_mismatch():
    wrong = revision("DES-WRONG", "REV-W", bore=55)
    item = prepare_recognition_input("P", occurrence("O1"), units_status="CONFIRMED")
    assert not recognize_occurrence(item, [wrong], CONFIG).candidates
    missing = prepare_recognition_input("P", occurrence("O1", bore=None), units_status="CONFIRMED")
    result = recognize_occurrence(missing, [wrong], CONFIG)
    assert result.candidates
    assert result.candidates[0].components["bore_similarity"].available is False


def test_unknown_units_only_allow_shape_matching_and_do_not_make_dimensional_claim():
    item = prepare_recognition_input("P", occurrence("O1", units="UNKNOWN"), units_status="UNKNOWN")
    result = recognize_occurrence(item, [revision("DES-1", "REV-1")], CONFIG)
    assert result.candidates
    assert result.input.quality == "UNKNOWN_UNITS"
    assert result.candidates[0].hard_filters["units"].status == "UNKNOWN"
    assert result.candidates[0].components["diameter_similarity"].available is False


def test_ambiguous_candidates_abstain_and_margin_is_recorded():
    item = prepare_recognition_input("P", occurrence("O1", shape=(0.0, 1.0, 0.0, 1.0)), units_status="CONFIRMED")
    result = recognize_occurrence(item, [revision("DES-A", "REV-A", diameter=100), revision("DES-B", "REV-B", diameter=100)], CONFIG)
    assert result.status == "AMBIGUOUS"
    assert result.abstained is True
    assert result.top_two_margin is not None and result.top_two_margin < .05


def test_low_score_and_invalid_inputs_abstain():
    item = prepare_recognition_input("P", occurrence("O1", shape=(0.0, 0.0, 0.0, 0.0)), units_status="CONFIRMED")
    result = recognize_occurrence(item, [revision("DES-A", "REV-A", diameter=250, bore=100, shape=(1, 1, 1, 1))], CONFIG)
    assert result.abstained
    invalid = prepare_recognition_input("P", occurrence("O2"), units_status="CONFIRMED")
    invalid = replace(invalid, quality_flags=("INVALID_GEOMETRY",), input_hash="")
    assert recognize_occurrence(invalid, [revision("DES-A", "REV-A")], CONFIG).status == "INVALID_INPUT"


def test_eligibility_excludes_superseded_and_unknown_units_without_shape():
    revisions = [revision("DES-1", "R1"), revision("DES-2", "R2", eligibility="SUPERSEDED"), revision("DES-3", "R3", eligibility="UNKNOWN_UNITS_BLOCKED", shape=())]
    assert [item.design_id for item in eligible_inventory_revisions(revisions)] == ["DES-1"]


def test_evaluation_reports_non_abstained_and_false_high_confidence_metrics():
    item = prepare_recognition_input("P", occurrence("O1"), units_status="CONFIRMED")
    result = recognize_occurrence(item, [revision("DES-1", "REV-1")], CONFIG)
    metrics = evaluate_recognition([result], {"O1": "DES-1"})
    assert metrics["top_1_accuracy"] == 1.0
    assert metrics["top_3_recall"] == 1.0
    assert metrics["false_high_confidence_count"] == 0


def test_recognition_schema_tables_are_additive(tmp_path):
    from sqlalchemy import inspect
    names = set(inspect(create_project_database(tmp_path / "recognition.sqlite")).get_table_names())
    assert {"roller_catalog", "roller_occurrences", "roller_designs", "roller_recognition_runs", "roller_recognition_candidates", "roller_recognition_reviews", "roller_recognition_labels", "roller_recognition_metrics"} <= names


def test_recognition_run_persists_candidates_reviews_and_exports(tmp_path):
    from sqlalchemy.orm import Session
    from rollform_extractor.database import Project, RollerDesign, RollerGeometryRevision, RollerOccurrence, Station
    from rollform_extractor.roller_recognition import export_recognition_run, recognize_project, review_candidate

    engine = create_project_database(tmp_path / "project.sqlite")
    with Session(engine) as session, session.begin():
        project = Project(drawing_id="DRAWING-1", source_path="synthetic.dxf", source_sha256="a" * 64)
        session.add(project)
        session.flush()
        session.add(Station(project_id=project.id, station_id="S1", bbox_json={}, source_handles=[], region_type="FORMING_STATION", stage_type="FORMING_STATION"))
        session.flush()
        session.add(RollerDesign(design_id="DES-1", name="Synthetic design", design_type="WORKING", status="CANDIDATE"))
        session.add(RollerGeometryRevision(revision_id="REV-1", design_id="DES-1", dimensions_json={"diameter": {"original_value": 100, "original_unit": "mm", "millimetres": 100}, "bore": {"original_value": 40, "original_unit": "mm", "millimetres": 40}, "width": {"original_value": 60, "original_unit": "mm", "millimetres": 60}, "shape_vector": [0, 1, 0, 1]}, unit_status="CONFIRMED", verification_status="VERIFIED", physical_fingerprint="fp", confidence=.95))
        session.add(RollerOccurrence(project_id=project.id, occurrence_id="O1", station_id="S1", role="upper_upper", source_handles=["H1"], confidence=.95, evidence_json={"outer_diameter_mm": 100, "bore_diameter_mm": 40, "width_mm": 60, "units_status": "CONFIRMED", "shape_vector": [0, 1, 0, 1]}))
        project_id = project.id
    run_id, results = recognize_project(engine, project_id, units_status="CONFIRMED", configuration_hash="cfg", config=CONFIG)
    assert len(results) == 1 and results[0].candidates
    from sqlalchemy import select
    from rollform_extractor.database import RollerRecognitionCandidate, RollerRecognitionReview
    with Session(engine) as session:
        candidate = session.scalar(select(RollerRecognitionCandidate))
        assert candidate and candidate.design_id == "DES-1"
        candidate_id = candidate.id
    review_id = review_candidate(engine, candidate_id, "ACCEPT_CANDIDATE", "synthetic-reviewer", reason_code="GEOMETRY_MATCH")
    assert review_id
    export = export_recognition_run(engine, run_id, tmp_path / "recognition")
    assert (export / "run_summary.json").exists()
    assert (export / "candidates.json").exists()
    assert (export / "candidates.csv").exists()
    assert (export / "abstentions.csv").exists()
    assert (export / "review_queue.csv").exists()
    assert (export / "evaluation.json").exists()
    assert (export / "occurrences" / "O1" / "score_breakdown.csv").exists()
    with Session(engine) as session:
        assert session.scalar(select(RollerRecognitionReview)) is not None
