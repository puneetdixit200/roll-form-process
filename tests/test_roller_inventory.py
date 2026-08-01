from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from rollform_extractor.database import (
    RollerAsset,
    RollerDesign,
    RollerGeometryRevision,
    RollerImportBatch,
    RollerImportRow,
    RollerReviewDecision,
    create_project_database,
)
from rollform_extractor.roller_inventory import export_inventory, import_inventory, inventory_stats, validate_inventory


def _csv(path: Path, rows: list[dict[str, object]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(asset: str, *, revision: str = "REV-1", unit: str = "mm", verification: str = "VERIFIED", alias: str = "") -> dict[str, object]:
    return {"design_id": "DES-ROLL-01", "design_name": "Synthetic forming roll", "design_type": "WORKING", "manufacturer": "Synthetic", "design_alias": alias, "asset_id": asset, "serial_number": f"SN-{asset}", "condition": "GOOD", "location_id": "LOC-A", "location_name": "Rack A", "revision_id": revision, "diameter": 100, "diameter_unit": unit, "bore": 40, "bore_unit": unit, "width": 60, "width_unit": unit, "measurement_method": "CMM", "geometry_source": "synthetic", "verification_status": verification, "confidence": 0.95}


def test_multiple_assets_share_design_and_geometry_revision_is_asset_specific(tmp_path):
    engine = create_project_database(tmp_path / "inventory.sqlite")
    source = _csv(tmp_path / "inventory.csv", [_row("ASSET-01", revision="REV-1", alias="roll-a"), _row("ASSET-02", revision="REV-2")])

    result = import_inventory(source, engine)
    with Session(engine) as session:
        designs = session.scalar(select(func.count()).select_from(RollerDesign))
        assets = session.scalar(select(func.count()).select_from(RollerAsset))
        revisions = session.scalars(select(RollerGeometryRevision).order_by(RollerGeometryRevision.revision_id)).all()

    assert result.accepted == 2
    assert (designs, assets, len(revisions)) == (1, 2, 2)
    assert {revision.asset_id for revision in revisions} == {1, 2}
    assert revisions[0].unit_status == "CONFIRMED"
    assert revisions[0].physical_fingerprint


def test_unknown_units_are_stored_but_verified_claim_is_rejected(tmp_path):
    engine = create_project_database(tmp_path / "inventory.sqlite")
    source = _csv(tmp_path / "inventory.csv", [_row("ASSET-01", unit="widget", verification="VERIFIED")])

    validation = validate_inventory(source, engine)
    result = import_inventory(source, engine)

    assert "UNKNOWN_UNITS_BLOCK_VERIFICATION" in validation.to_dict()["rows"][0]["normalized"].get("warnings", []) or result.rejected == 1
    assert result.rejected == 1
    assert inventory_stats(engine)["assets"] == 0


def test_duplicate_alias_requires_review_and_same_file_is_idempotent(tmp_path):
    engine = create_project_database(tmp_path / "inventory.sqlite")
    source = _csv(tmp_path / "inventory.csv", [_row("ASSET-01", alias="same"), _row("ASSET-02", alias="same")])

    first = import_inventory(source, engine)
    second = import_inventory(source, engine)
    with Session(engine) as session:
        rows = session.scalars(select(RollerImportRow).where(RollerImportRow.batch_id == first.batch_id)).all()

    assert first.accepted == 1
    assert first.review_required == 1
    assert second.idempotent is True
    assert len(rows) == 2
    assert any(row.status == "REVIEW_REQUIRED" for row in rows)


def test_import_rows_preserve_source_and_review_decision(tmp_path):
    engine = create_project_database(tmp_path / "inventory.sqlite")
    source = _csv(tmp_path / "inventory.csv", [_row("ASSET-01", alias="same"), _row("ASSET-02", alias="same")])
    result = import_inventory(source, engine)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(RollerImportRow).where(RollerImportRow.batch_id == result.batch_id, RollerImportRow.status == "REVIEW_REQUIRED"))
        row.status = "REJECTED"
        session.add(RollerReviewDecision(batch_id=result.batch_id, row_id=row.id, decision="REJECT", reviewer="engineer", notes="alias conflict"))
    with Session(engine) as session:
        decision = session.scalar(select(RollerReviewDecision).where(RollerReviewDecision.batch_id == result.batch_id))
        assert decision.notes == "alias conflict"
        assert source.name in str(session.scalar(select(RollerImportBatch).where(RollerImportBatch.id == result.batch_id)).source_name)


def test_export_inventory_is_safe_and_legacy_schema_is_preserved(tmp_path):
    engine = create_project_database(tmp_path / "inventory.sqlite")
    assert {"roller_catalog", "roller_designs", "roller_assets", "roller_geometry_revisions", "roller_import_batches", "roller_review_decisions"} <= set(inspect(engine).get_table_names())
    source = _csv(tmp_path / "inventory.csv", [_row("ASSET-01", unit="in")])
    import_inventory(source, engine)
    output = export_inventory(engine, tmp_path / "exports")
    assert sum("ASSET-01" in line for line in output.read_text(encoding="utf-8").splitlines()) == 1


def test_inventory_api_validates_imports_and_rejects_path_traversal(tmp_path):
    from rollform_extractor.web.backend.api.app import create_app

    client = TestClient(create_app(tmp_path / "web", auto_run_jobs=False))
    assert client.get("/api/inventory/stats").status_code == 200
    payload = _csv(tmp_path / "api.csv", [_row("ASSET-API")]).read_bytes()
    assert client.post("/api/inventory/validate", files={"file": ("api.csv", payload, "text/csv")}).status_code == 200
    imported = client.post("/api/inventory/import", files={"file": ("api.csv", payload, "text/csv")})
    assert imported.status_code == 200
    assert client.get("/api/inventory/designs").json()[0]["design_id"] == "DES-ROLL-01"
    assert client.get("/api/inventory/geometry-revisions").status_code == 200
    assert client.get("/api/inventory/locations").status_code == 200
    assert client.get("/api/inventory/export").status_code == 200
    assert client.post("/api/inventory/validate", files={"file": ("../../secret.txt", b"x", "text/plain")}).status_code == 400
