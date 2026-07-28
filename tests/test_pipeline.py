from __future__ import annotations

import ezdxf

from rollform_extractor.pipeline import ExtractionRequest, extract_project
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
