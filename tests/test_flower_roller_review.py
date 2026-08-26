from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rollform_extractor.database import (
    Base,
    VisualFlowerCandidateRow,
    VisualFlowerGenerationRunRow,
    VisualFlowerRollerEvidenceReviewRow,
    VisualProfileTargetRow,
)
from rollform_extractor.flower_roller_evidence import create_roller_evidence_review


def _engine(tmp_path, *, candidates=None):
    engine = create_engine(f"sqlite:///{tmp_path / 'visual.sqlite'}")
    Base.metadata.create_all(engine)
    role_candidates = candidates or [
        {
            "rank": 1,
            "design_id": "RD-1",
            "geometry_revision_id": "rev-1",
            "evidence_tier": "TIER_3_CONFIRMED_HISTORICAL_USAGE_FROM_MATCHED_PASS",
        }
    ]
    with Session(engine) as session, session.begin():
        target = VisualProfileTargetRow(target_id="target", name="target", schema_version=1, topology="OPEN_PATH")
        session.add(target)
        session.flush()
        run = VisualFlowerGenerationRunRow(
            run_id="run",
            target_id=target.id,
            algorithm_version="test",
            dataset_hash="dataset",
            configuration_hash="config",
            status="READY",
            result_json={},
        )
        session.add(run)
        session.flush()
        session.add(
            VisualFlowerCandidateRow(
                candidate_id="candidate-1",
                run_id=run.id,
                candidate_json={
                    "roller_evidence": {
                        "evidence_bundle_hash": "bundle",
                        "stations": [
                            {
                                "pass_id": "pass-1",
                                "roles": [{"role": "UPPER", "candidates": role_candidates}],
                            }
                        ],
                    }
                },
                status="READY",
                visual_confidence=0.5,
            )
        )
    return engine


def test_identical_roller_evidence_reviews_remain_append_only(tmp_path):
    engine = _engine(tmp_path)

    first = create_roller_evidence_review(
        engine, "candidate-1", "pass-1", "UPPER", "NEEDS_REVIEW", "engineer", "uncertain"
    )
    second = create_roller_evidence_review(
        engine, "candidate-1", "pass-1", "UPPER", "NEEDS_REVIEW", "engineer", "uncertain"
    )

    assert first["review_id"] != second["review_id"]
    with Session(engine) as session:
        assert session.query(VisualFlowerRollerEvidenceReviewRow).count() == 2


def test_single_candidate_accept_records_design_and_revision(tmp_path):
    engine = _engine(tmp_path)

    result = create_roller_evidence_review(
        engine,
        "candidate-1",
        "pass-1",
        "UPPER",
        "ACCEPT_DESIGN_EVIDENCE",
        "engineer",
        "confirmed by source",
    )

    assert result["selected_design_id"] == "RD-1"
    assert result["selected_revision_id"] == "rev-1"
    with Session(engine) as session:
        row = session.query(VisualFlowerRollerEvidenceReviewRow).one()
        assert row.selected_design_id == "RD-1"
        assert row.selected_revision_id == "rev-1"


def test_review_rejects_role_not_present_in_evidence(tmp_path):
    engine = _engine(tmp_path)

    with pytest.raises(LookupError, match="role not found"):
        create_roller_evidence_review(
            engine, "candidate-1", "pass-1", "LOWER", "NEEDS_REVIEW", "engineer"
        )


def test_ambiguous_accept_requires_explicit_design(tmp_path):
    engine = _engine(
        tmp_path,
        candidates=[
            {"rank": 1, "design_id": "RD-1", "geometry_revision_id": "rev-1"},
            {"rank": 2, "design_id": "RD-2", "geometry_revision_id": "rev-2"},
        ],
    )

    with pytest.raises(ValueError, match="requires selected_design_id"):
        create_roller_evidence_review(
            engine, "candidate-1", "pass-1", "UPPER", "ACCEPT_DESIGN_EVIDENCE", "engineer"
        )

    result = create_roller_evidence_review(
        engine,
        "candidate-1",
        "pass-1",
        "UPPER",
        "ACCEPT_DESIGN_EVIDENCE",
        "engineer",
        selected_design_id="RD-2",
        selected_revision_id="rev-2",
    )
    assert result["selected_design_id"] == "RD-2"
    assert result["selected_revision_id"] == "rev-2"
