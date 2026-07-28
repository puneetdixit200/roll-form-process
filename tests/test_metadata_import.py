from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from rollform_extractor.database import Project, ProjectCode, ProjectMetadata, ResultProvenance, create_project_database
from rollform_extractor.metadata_import import import_metadata, resolve_project_codes


def test_compound_drawing_name_resolves_related_project_codes():
    result = resolve_project_codes("D0064-D0065-FlowerSequence.dwg")

    assert result.drawing_id == "D0064-D0065-FlowerSequence"
    assert result.related_project_codes == ("D0064", "D0065")


def test_missing_material_values_remain_unknown_without_blocking_geometry(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    _project(engine, "D0064-D0065-FlowerSequence")
    workbook = _xlsx(
        tmp_path / "metadata.xlsx",
        {
            "drawing_id": "D0064-D0065-FlowerSequence",
            "material_grade": None,
            "steel_thickness": "",
            "machine_id": "RF-1",
        },
    )

    summary = import_metadata(workbook, engine)
    metadata = _metadata(engine, "D0064-D0065-FlowerSequence")

    assert summary.imported == 1
    assert metadata["material_grade"] is None
    assert metadata["steel_thickness"] is None
    assert metadata["machine_id"] == "RF-1"


def test_csv_import_supports_approved_metadata_fields_and_source_row_provenance(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    _project(engine, "D0064-D0065-FlowerSequence")
    csv_path = _csv(
        tmp_path / "metadata.csv",
        {
            "drawing_id": "D0064-D0065-FlowerSequence",
            "material_grade": "CR4",
            "steel_thickness": "1.2",
            "strip_width": "58",
            "coil_width": "60",
            "machine_id": "RF-1",
            "shaft_diameter": "40",
            "product_code": "P-64",
            "customer_code": "C-17",
            "production_status": "released",
            "tooling_worked": "yes",
            "known_defects": "edge wave",
            "engineer_notes": "trial ok",
            "copra_project_reference": "COPRA-64",
        },
    )

    summary = import_metadata(csv_path, engine)
    metadata = _metadata(engine, "D0064-D0065-FlowerSequence")
    provenance = _provenance(engine, "D0064-D0065-FlowerSequence", "material_grade")

    assert summary.imported == 1
    assert metadata == {
        "material_grade": "CR4",
        "steel_thickness": "1.2",
        "strip_width": "58",
        "coil_width": "60",
        "machine_id": "RF-1",
        "shaft_diameter": "40",
        "product_code": "P-64",
        "customer_code": "C-17",
        "production_status": "released",
        "tooling_worked": "yes",
        "known_defects": "edge wave",
        "engineer_notes": "trial ok",
        "copra_project_reference": "COPRA-64",
    }
    assert provenance.method == "metadata_import"
    assert provenance.source_handles == [f"{csv_path}:2"]


def test_import_resolves_project_code_when_drawing_id_is_absent(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    project_id = _project(engine, "D0064-D0065-FlowerSequence")
    with Session(engine) as session, session.begin():
        session.add(ProjectCode(code="D0065", project_id=project_id, source="test"))
    workbook = _xlsx(tmp_path / "metadata.xlsx", {"project_code": "D0065", "customer_code": "C-65"})

    summary = import_metadata(workbook, engine)

    assert summary.imported == 1
    assert _metadata(engine, "D0064-D0065-FlowerSequence")["customer_code"] == "C-65"


def test_explicit_drawing_id_wins_over_conflicting_project_code(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    first_id = _project(engine, "D0064-D0065-FlowerSequence")
    second_id = _project(engine, "D9999-Other")
    with Session(engine) as session, session.begin():
        session.add(ProjectCode(code="D0065", project_id=first_id, source="test"))
        session.add(ProjectCode(code="D9999", project_id=second_id, source="test"))
    csv_path = _csv(
        tmp_path / "metadata.csv",
        {"drawing_id": "D9999-Other", "project_code": "D0065", "machine_id": "RF-9"},
    )

    summary = import_metadata(csv_path, engine)

    assert summary.imported == 1
    assert _metadata(engine, "D9999-Other")["machine_id"] == "RF-9"
    assert _metadata(engine, "D0064-D0065-FlowerSequence") == {}


def test_unmatched_and_conflicting_rows_enter_review_without_overwriting(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    _project(engine, "D0064-D0065-FlowerSequence")
    first = _csv(tmp_path / "first.csv", {"drawing_id": "D0064-D0065-FlowerSequence", "machine_id": "RF-1"})
    second = _csv(tmp_path / "second.csv", {"drawing_id": "D0064-D0065-FlowerSequence", "machine_id": "RF-2"})
    missing = _csv(tmp_path / "missing.csv", {"drawing_id": "missing", "machine_id": "RF-X"})

    import_metadata(first, engine)
    conflict = import_metadata(second, engine)
    unmatched = import_metadata(missing, engine)

    assert conflict.imported == 0
    assert conflict.conflicts == ("2:D0064-D0065-FlowerSequence:machine_id",)
    assert unmatched.unmatched == ("2:missing",)
    assert _metadata(engine, "D0064-D0065-FlowerSequence")["machine_id"] == "RF-1"


def _project(engine, drawing_id: str) -> int:
    with Session(engine) as session, session.begin():
        project = Project(drawing_id=drawing_id, source_path=f"{drawing_id}.dxf", source_sha256="hash")
        session.add(project)
        session.flush()
        return project.id


def _metadata(engine, drawing_id: str) -> dict[str, str | None]:
    with Session(engine) as session:
        project = session.scalar(select(Project).where(Project.drawing_id == drawing_id))
        rows = session.scalars(select(ProjectMetadata).where(ProjectMetadata.project_id == project.id)).all()
    return {row.key: row.value for row in rows}


def _provenance(engine, drawing_id: str, field: str) -> ResultProvenance:
    with Session(engine) as session:
        project = session.scalar(select(Project).where(Project.drawing_id == drawing_id))
        return session.scalar(
            select(ResultProvenance)
            .where(ResultProvenance.project_id == project.id)
            .where(ResultProvenance.result_table == "project_metadata")
            .where(ResultProvenance.field_name == field)
        )


def _csv(path: Path, row: dict[str, str | None]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def _xlsx(path: Path, row: dict[str, str | None]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(row))
    sheet.append(list(row.values()))
    workbook.save(path)
    return path
