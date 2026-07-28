from __future__ import annotations

import csv

from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.cli import main
from rollform_extractor.database import Project, ProjectMetadata, create_project_database
from tests.cad_factory import make_flower_dxf


def test_cli_extract_and_validate_return_zero(tmp_path, capsys):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=3, labels=True)
    out = tmp_path / "out"

    assert main(["extract", str(source), str(out)]) == 0
    assert main(["validate", str(out / "flower")]) == 0

    output = capsys.readouterr().out
    assert "stations=3" in output
    assert "valid" in output


def test_cli_inspect_review_and_reprocess_return_zero(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=2, labels=True)
    out = tmp_path / "out"
    main(["extract", str(source), str(out)])

    assert main(["inspect", str(source)]) == 0
    assert main(["review", str(out / "flower")]) == 0
    assert main(["reprocess", str(out / "flower")]) == 0


def test_cli_rejects_unsupported_stage(tmp_path, capsys):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)

    assert main(["extract", str(source), str(tmp_path / "out"), "--stage", "profiles"]) == 2
    assert "not supported" in capsys.readouterr().err


def test_cli_import_metadata_uses_master_database(tmp_path, capsys):
    db_path = tmp_path / "project.sqlite"
    engine = create_project_database(db_path)
    with Session(engine) as session, session.begin():
        session.add(Project(drawing_id="D0064-D0065-FlowerSequence", source_path="source.dxf", source_sha256="hash"))
    metadata_path = tmp_path / "metadata.csv"
    with metadata_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["drawing_id", "material_grade"])
        writer.writeheader()
        writer.writerow({"drawing_id": "D0064-D0065-FlowerSequence", "material_grade": "CR4"})

    assert main(["import-metadata", str(metadata_path), "--master", str(db_path)]) == 0

    with Session(engine) as session:
        row = session.scalar(select(ProjectMetadata).where(ProjectMetadata.key == "material_grade"))
    assert row.value == "CR4"
    assert "imported=1" in capsys.readouterr().out
