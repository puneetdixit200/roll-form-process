from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from rollform_extractor.database import (
    Project,
    RecognitionEvaluationCase,
    RecognitionEvaluationDataset,
    RollerDesign,
    RollerGeometryRevision,
    RollerRecognitionInput,
    RollerRecognitionRun,
    create_project_database,
)
from rollform_extractor.validated_usage import (
    add_evaluation_case,
    adjudicate_case,
    build_usage_relationship_snapshot,
    calculate_review_agreement,
    create_evaluation_dataset,
    detect_stale_confirmations,
    lock_dataset_version,
    promote_confirmed_usage,
    search_historical_usage,
    stable_hash,
    submit_label_assertion,
    validate_dataset,
)


def _db(tmp_path: Path):
    engine = create_project_database(tmp_path / "project.sqlite")
    with Session(engine) as session, session.begin():
        project = Project(drawing_id="SYN-PROJECT", source_path="synthetic.dxf", source_sha256="a" * 64)
        session.add(project)
        session.flush()
        session.add(RollerDesign(design_id="RDES-001", name="Synthetic design", status="VERIFIED", verified=1))
        session.add(RollerGeometryRevision(revision_id="REV-001", design_id="RDES-001", unit_status="CONFIRMED_MM", verification_status="VERIFIED"))
        run = RollerRecognitionRun(project_id=project.id, run_key="synthetic", algorithm_version="roller-recognition-v1", feature_schema_version=1, configuration_hash="c" * 64, inventory_snapshot_hash="i" * 64)
        session.add(run)
        session.flush()
        session.add(RollerRecognitionInput(run_id=run.id, occurrence_id="OCC-001", station_id="S01", role="WORK", input_hash="h" * 64, source_handles_json=["H1"], feature_json={}, scalar_vector_json={}, shape_vector_json={}, missing_mask_json=[], quality_json={}))
        session.flush()
        return engine, project.id


def test_label_agreement_adjudication_lock_and_promotion(tmp_path):
    engine, project_id = _db(tmp_path)
    dataset = create_evaluation_dataset(engine, "synthetic", "ENGINEER_LABELLED", "alice", inventory_snapshot_hash="i" * 64)
    case = add_evaluation_case(engine, dataset["dataset_id"], project_id, "OCC-001", recognition_input_id=1)
    assert submit_label_assertion(engine, case["case_id"], "alice", "MATCH_DESIGN", "GEOMETRY_MATCH", "RDES-001")["outcome"] == "MATCH_DESIGN"
    assert calculate_review_agreement(engine, case["case_id"]).state == "PENDING_SECOND_REVIEW"
    submit_label_assertion(engine, case["case_id"], "bob", "MATCH_DESIGN", "DIMENSION_MATCH", "RDES-001")
    assert calculate_review_agreement(engine, case["case_id"]).state == "AGREED"
    adjudicate_case(engine, case["case_id"], "chief", "MATCH_DESIGN", "GEOMETRY_MATCH", "RDES-001", "REV-001")
    assert validate_dataset(engine, dataset["dataset_id"])["valid"]
    lock_dataset_version(engine, dataset["dataset_id"], "chief")
    usage = promote_confirmed_usage(engine, case["case_id"], "chief", "historical evidence")
    assert usage["design_id"] == "RDES-001"
    assert usage["physical_asset_id"] is None
    assert search_historical_usage(engine, design_id="RDES-001")["total"] == 1
    assert build_usage_relationship_snapshot(engine)["relationship_count"] == 1


def test_negative_label_does_not_accept_design_and_locked_data_is_immutable(tmp_path):
    engine, project_id = _db(tmp_path)
    dataset = create_evaluation_dataset(engine, "negative", "SYNTHETIC", "fixture")
    case = add_evaluation_case(engine, dataset["dataset_id"], project_id, "OCC-001", recognition_input_id=1)
    with pytest.raises(ValueError, match="cannot specify"):
        submit_label_assertion(engine, case["case_id"], "alice", "NO_CATALOG_MATCH", "NO_MATCH", "RDES-001")
    submit_label_assertion(engine, case["case_id"], "alice", "NO_CATALOG_MATCH", "NO_MATCH")
    submit_label_assertion(engine, case["case_id"], "bob", "NO_CATALOG_MATCH", "NO_MATCH")
    adjudicate_case(engine, case["case_id"], "chief", "NO_CATALOG_MATCH", "NO_MATCH")
    lock_dataset_version(engine, dataset["dataset_id"], "chief")
    with pytest.raises(ValueError, match="cannot be edited"):
        add_evaluation_case(engine, dataset["dataset_id"], project_id, "OCC-002")


def test_stale_input_is_detected_and_search_excludes_synthetic(tmp_path):
    engine, project_id = _db(tmp_path)
    dataset = create_evaluation_dataset(engine, "stale", "SYNTHETIC", "fixture")
    case = add_evaluation_case(engine, dataset["dataset_id"], project_id, "OCC-001", recognition_input_id=1)
    submit_label_assertion(engine, case["case_id"], "alice", "MATCH_DESIGN", "GEOMETRY_MATCH", "RDES-001")
    submit_label_assertion(engine, case["case_id"], "bob", "MATCH_DESIGN", "GEOMETRY_MATCH", "RDES-001")
    adjudicate_case(engine, case["case_id"], "chief", "MATCH_DESIGN", "GEOMETRY_MATCH", "RDES-001")
    lock_dataset_version(engine, dataset["dataset_id"], "chief")
    promote_confirmed_usage(engine, case["case_id"], "chief")
    assert search_historical_usage(engine)["total"] == 0
    assert search_historical_usage(engine, include_synthetic=True)["total"] == 1
    with Session(engine) as session, session.begin():
        row = session.get(RollerRecognitionInput, 1)
        row.input_hash = "z" * 64
    assert detect_stale_confirmations(engine, project_id) == [{"usage_id": "USE-" + stable_hash({"case": 1, "input": "h" * 64, "design": "RDES-001"})[:12], "status": "STALE_SOURCE", "reason": "recognition_input_hash_changed"}]
