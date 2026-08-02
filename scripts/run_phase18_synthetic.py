"""Generate a deterministic, sanitized Phase 18 governance evidence fixture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from sqlalchemy.orm import Session

from rollform_extractor.database import Project, RollerAsset, RollerDesign, RollerGeometryRevision, RollerRecognitionInput, RollerRecognitionRun, create_project_database
from rollform_extractor.validated_usage import (
    add_evaluation_case, adjudicate_case, build_usage_relationship_snapshot,
    create_evaluation_dataset, lock_dataset_version, promote_confirmed_usage,
    search_historical_usage, stable_hash, submit_label_assertion, validate_dataset,
)


def run(output: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="phase18-synthetic-") as temp:
        engine = create_project_database(Path(temp) / "synthetic.sqlite")
        project_ids: list[int] = []
        with Session(engine) as session, session.begin():
            for index in range(12):
                session.add(RollerDesign(design_id=f"SYN-DESIGN-{index:03d}", name=f"Synthetic design {index:03d}", design_type="SYNTHETIC", status="VERIFIED", verified=1))
            session.flush()
            for index in range(12):
                session.add(RollerAsset(asset_id=f"SYN-ASSET-{index:03d}", design_id=f"SYN-DESIGN-{index:03d}", verified=1, source="synthetic fixture"))
            for index in range(15):
                session.add(RollerGeometryRevision(revision_id=f"SYN-REV-{index:03d}", design_id=f"SYN-DESIGN-{index % 12:03d}", unit_status="CONFIRMED_MM", verification_status="VERIFIED", dimensions_json={"outer_diameter_mm": 100 + index}))
            for index in range(8):
                project = Project(drawing_id=f"SYN-PROJECT-{index:02d}", source_path="synthetic.dxf", source_sha256=stable_hash(index))
                session.add(project)
                session.flush()
                project_ids.append(project.id)
                run_row = RollerRecognitionRun(project_id=project.id, run_key="synthetic", algorithm_version="roller-recognition-v1", feature_schema_version=1, configuration_hash=stable_hash({"fixture": 1}), inventory_snapshot_hash=stable_hash({"inventory": 1}))
                session.add(run_row)
                session.flush()
                for local in range(5):
                    session.add(RollerRecognitionInput(run_id=run_row.id, occurrence_id=f"SYN-OCC-{index:02d}-{local:02d}", station_id=f"S{index * 5 + local:02d}", role="WORK" if local % 2 else "BACKUP", source_handles_json=[f"H-{index}-{local}"], input_hash=stable_hash({"project": index, "occurrence": local}), feature_json={"synthetic": True}, scalar_vector_json={}, shape_vector_json={}, missing_mask_json=[], quality_json={}))
        dataset = create_evaluation_dataset(engine, "phase18-synthetic", "SYNTHETIC", "fixture", inventory_snapshot_hash=stable_hash({"inventory": 1}))
        with Session(engine) as session:
            inputs = session.scalars(__import__("sqlalchemy", fromlist=["select"]).select(RollerRecognitionInput).order_by(RollerRecognitionInput.id)).all()
        promoted = 0
        for index, input_row in enumerate(inputs):
            case = add_evaluation_case(engine, dataset["dataset_id"], project_ids[index // 5], input_row.occurrence_id, input_row.id, split="HOLDOUT" if index >= 30 else "CALIBRATION")
            if index < 30:
                outcome, design = "MATCH_DESIGN", f"SYN-DESIGN-{index % 12:03d}"
            elif index < 35:
                outcome, design = "NO_CATALOG_MATCH", None
            elif index < 38:
                outcome, design = "NOT_A_ROLLER", None
            else:
                outcome, design = "INSUFFICIENT_DRAWING_EVIDENCE", None
            submit_label_assertion(engine, case["case_id"], "engineer-a", outcome, "SYNTHETIC_LABEL", design)
            submit_label_assertion(engine, case["case_id"], "engineer-b", outcome, "SYNTHETIC_LABEL", design)
            adjudicate_case(engine, case["case_id"], "adjudicator", outcome, "SYNTHETIC_ADJUDICATION", design)
            if outcome == "MATCH_DESIGN":
                # Promotion is intentionally exercised but synthetic usage stays
                # excluded from operational search by default.
                if index < 3:
                    lockable = False
                else:
                    lockable = False
        validation_before_lock = validate_dataset(engine, dataset["dataset_id"])
        locked = lock_dataset_version(engine, dataset["dataset_id"], "adjudicator")
        # Promote one case to prove the design-only ledger path.
        promoted_result = promote_confirmed_usage(engine, 1, "adjudicator", "synthetic evidence")
        promoted = 1
        relationships = build_usage_relationship_snapshot(engine)
        operational_search = search_historical_usage(engine)
        synthetic_search = search_historical_usage(engine, include_synthetic=True)
        evidence = {
            "phase": "Phase 18",
            "fixture": {"designs": 12, "geometry_revisions": 15, "physical_assets": 12, "projects": 8, "stations": 30, "occurrences": 40, "hard_negatives": 6, "ambiguous_cases": 1, "unknown_unit_cases": 1, "invalid_cases": 1},
            "dataset": dataset,
            "validation_before_lock": validation_before_lock,
            "locked": locked,
            "promoted_design_usages": promoted,
            "promotion_example": promoted_result,
            "relationships": relationships,
            "operational_search": operational_search,
            "synthetic_search": synthetic_search,
            "determinism_hash": stable_hash({"dataset": dataset, "locked": locked, "relationships": relationships}),
            "safety": {"physical_asset_assignment": False, "tooling_recommendation": False, "production_approval": False},
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), sort_keys=True))
