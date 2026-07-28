from __future__ import annotations

import json

from rollform_extractor.pipeline import ExtractionRequest, extract_project
from tests.cad_factory import make_flower_dxf


def test_manifest_records_export_files_and_hashes(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=2, labels=True, rollers=True)

    summary = extract_project(ExtractionRequest(source, tmp_path / "out"))
    manifest = json.loads((summary.project_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["station_count"] == 2
    assert "stations/station_01/profile.dxf" in manifest["files"]
    assert "stations/station_02/profile.dxf" in manifest["files"]
    assert manifest["files"]["project.json"]["sha256"]
    assert all(path.exists() for path in summary.manifest.dxf_files)
