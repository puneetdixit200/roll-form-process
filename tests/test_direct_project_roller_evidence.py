from __future__ import annotations

import json

from sqlalchemy.orm import Session

from rollform_extractor.database import (
    Project,
    RollerDesign,
    RollerGeometryRevision,
    RollerRecognitionCandidate,
    RollerRecognitionInput,
    RollerRecognitionRun,
    Station,
    create_project_database,
)
from rollform_extractor.visual_flower_service import _direct_project_roller_evidence


def _workflow(root, *, target_id: str, project_id: str, project_path: str | None) -> None:
    workflow_dir = root / "rollform_workflows" / "rwf-test"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.json").write_text(
        json.dumps({"selected_target_id": target_id, "project_id": project_id}),
        encoding="utf-8",
    )
    project_dir = root / "projects" / project_id
    project_dir.mkdir(parents=True)
    (project_dir / "project_record.json").write_text(
        json.dumps({"summary": {"project_path": project_path} if project_path else {}}),
        encoding="utf-8",
    )


def test_direct_project_recognition_is_exposed_as_station_evidence(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    project_output = tmp_path / "analysis-output"
    project_output.mkdir()
    database_path = project_output / "project.sqlite"
    engine = create_project_database(database_path)

    with Session(engine) as session, session.begin():
        project = Project(
            drawing_id="drawing-1",
            source_path="drawing-1.dxf",
            source_sha256="source-hash",
        )
        session.add(project)
        session.flush()
        session.add_all(
            [
                Station(project_id=project.id, station_id="S1", sequence_index=0),
                Station(project_id=project.id, station_id="S2", sequence_index=1),
                RollerDesign(design_id="RD-1", name="Upper design"),
            ]
        )
        session.flush()
        session.add(
            RollerGeometryRevision(
                revision_id="REV-1",
                design_id="RD-1",
                dimensions_json={},
                unit_status="CONFIRMED",
                verification_status="VERIFIED",
            )
        )
        run = RollerRecognitionRun(
            project_id=project.id,
            run_key="recognition-run",
            algorithm_version="roller-recognition-v1",
            feature_schema_version=1,
            configuration_hash="test",
            inventory_snapshot_hash="inventory",
            status="COMPLETED",
            occurrence_count=1,
            candidate_count=1,
        )
        session.add(run)
        session.flush()
        input_row = RollerRecognitionInput(
            run_id=run.id,
            occurrence_id="occ-2",
            station_id="S2",
            role="UPPER",
            feature_json={"quality_flags": []},
            scalar_vector_json={},
            shape_vector_json={},
            missing_mask_json=[],
            quality_json={},
            source_handles_json=["AB"],
            input_hash="input-hash",
        )
        session.add(input_row)
        session.flush()
        session.add(
            RollerRecognitionCandidate(
                run_id=run.id,
                input_id=input_row.id,
                design_id="RD-1",
                geometry_revision_id="REV-1",
                rank=1,
                overall_score=0.93,
                confidence=0.88,
                evidence_coverage=0.81,
                candidate_status="HIGH_SIMILARITY_CANDIDATE",
                component_scores_json={"shape_similarity": {"score": 0.95}},
                hard_filter_results_json={},
                explanation_json={},
                algorithm_version="roller-recognition-v1",
                configuration_hash="test",
            )
        )
        run_id = run.id

    _workflow(
        root,
        target_id="target-1",
        project_id="drawing-1",
        project_path=str(project_output),
    )
    monkeypatch.setenv("ROLLFORM_WEB_WORKSPACE", str(root))
    monkeypatch.setattr(
        "rollform_extractor.visual_flower_service.recognize_project",
        lambda *args, **kwargs: (run_id, ()),
    )

    records, evidence_hash = _direct_project_roller_evidence(
        "target-1",
        None,
        units_status="CONFIRMED",
    )

    assert len(records) == 1
    assert records[0]["design_id"] == "RD-1"
    assert records[0]["geometry_revision_id"] == "REV-1"
    assert records[0]["station_id"] == "S2"
    assert records[0]["station_progress"] == 1.0
    assert records[0]["role"] == "UPPER"
    assert records[0]["recognition_status"] == "HIGH_SIMILARITY_CANDIDATE"
    assert evidence_hash not in {"UNCONFIGURED", "PROJECT_ANALYSIS_PENDING"}


def test_integrated_target_refreshes_after_background_project_analysis(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    _workflow(root, target_id="target-pending", project_id="drawing-pending", project_path=None)
    monkeypatch.setenv("ROLLFORM_WEB_WORKSPACE", str(root))

    records, evidence_hash = _direct_project_roller_evidence("target-pending", None)

    assert records == []
    assert evidence_hash == "PROJECT_ANALYSIS_PENDING"
