from __future__ import annotations

import ezdxf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rollform_extractor.database import ExtractionRun, create_project_database
from rollform_extractor.pipeline import ExtractionRequest, extract_project
from rollform_extractor.pipeline import reprocess_project
from rollform_extractor.validation import validate_project
from tests.cad_factory import make_flower_dxf


def test_extract_creates_dynamic_station_tree_and_reimportable_dxfs(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=8, labels=True, rollers=True)

    summary = extract_project(ExtractionRequest(source, tmp_path / "output"))

    assert summary.station_count == 8
    assert not (summary.project_path / "stations" / "station_09").exists()
    assert (summary.project_path / "project.sqlite").exists()
    assert (summary.project_path / "report.html").exists()
    for path in summary.manifest.dxf_files:
        ezdxf.readfile(path)
    assert validate_project(summary.project_path).valid


def test_reprocess_preserves_sqlite_history_and_review_decisions(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=2, labels=True)
    summary = extract_project(ExtractionRequest(source, tmp_path / "output"))
    review = summary.project_path / "review" / "review_queue.json"
    review.write_text('{"schema_version": 1, "items": [{"status": "done"}]}', encoding="utf-8")

    reprocess_project(summary.project_path)

    engine = create_project_database(summary.project_path / "project.sqlite")
    with Session(engine) as session:
        run_count = session.scalar(select(func.count()).select_from(ExtractionRun))
    assert run_count == 2
    assert "done" in review.read_text(encoding="utf-8")
