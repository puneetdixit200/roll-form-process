from __future__ import annotations

from sqlalchemy import create_engine

from rollform_extractor.database import Base, VisualFlowerCandidateRow, VisualFlowerGenerationRunRow, VisualProfileTargetRow, VisualFlowerRollerEvidenceReviewRow
from rollform_extractor.flower_roller_evidence import create_roller_evidence_review


def test_roller_evidence_review_is_append_only(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'visual.sqlite'}")
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session
    with Session(engine) as session, session.begin():
        target = VisualProfileTargetRow(target_id="target", name="target", schema_version=1, topology="OPEN_PATH")
        session.add(target)
        session.flush()
        run = VisualFlowerGenerationRunRow(run_id="run", target_id=target.id, algorithm_version="test", dataset_hash="dataset", configuration_hash="config", status="READY", result_json={})
        session.add(run)
        session.flush()
        session.add(VisualFlowerCandidateRow(candidate_id="candidate-1", run_id=run.id, candidate_json={"roller_evidence": {"evidence_bundle_hash": "bundle", "stations": [{"pass_id": "pass-1"}]}}, status="READY", visual_confidence=0.5))
    first = create_roller_evidence_review(engine, "candidate-1", "pass-1", "UPPER", "NEEDS_REVIEW", "engineer", "uncertain")
    second = create_roller_evidence_review(engine, "candidate-1", "pass-1", "UPPER", "ACCEPT_DESIGN_EVIDENCE", "engineer", "confirmed by source")
    assert first["review_id"] != second["review_id"]
    with Session(engine) as session:
        assert session.query(VisualFlowerRollerEvidenceReviewRow).count() == 2
