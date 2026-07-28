from __future__ import annotations

from rollform_extractor.pipeline import ExtractionRequest, extract_project
from rollform_extractor.validation import validate_project
from tests.cad_factory import make_flower_dxf


def test_validate_reports_manifest_hash_mismatch(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    summary = extract_project(ExtractionRequest(source, tmp_path / "out"))
    (summary.project_path / "project.json").write_text("{}", encoding="utf-8")

    report = validate_project(summary.project_path)

    assert not report.valid
    assert any(issue.code == "hash_mismatch" for issue in report.issues)


def test_validate_reports_missing_original_source(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=1, labels=True)
    summary = extract_project(ExtractionRequest(source, tmp_path / "out"))
    source.unlink()

    report = validate_project(summary.project_path)

    assert not report.valid
    assert any(issue.code == "missing_source" for issue in report.issues)
