from __future__ import annotations

import ezdxf
import pytest

from rollform_extractor import converter
from rollform_extractor.converter import ConversionUnavailableError
from tests.cad_factory import sha256_file, write_sample_dxf


@pytest.fixture
def sample_dxf(tmp_path):
    return write_sample_dxf(tmp_path / "part.dxf")


def test_dwg_without_converter_fails_with_ascii_dxf_instructions(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")
    monkeypatch.setattr(converter, "discover_converter", lambda: None)
    with pytest.raises(
        ConversionUnavailableError,
        match="AutoCAD 2013 or AutoCAD 2007 ASCII DXF",
    ):
        converter.stage_input(source, tmp_path / "out")


def test_direct_dxf_is_staged_without_modifying_source(sample_dxf, tmp_path):
    before = sha256_file(sample_dxf)
    result = converter.stage_input(sample_dxf, tmp_path / "out")
    assert sha256_file(sample_dxf) == before
    assert result.source_file == sample_dxf
    assert result.converted_file != sample_dxf
    assert ezdxf.readfile(result.converted_file)


def test_malformed_dxf_is_rejected(tmp_path):
    source = tmp_path / "broken.dxf"
    source.write_text("not a dxf", encoding="ascii")
    with pytest.raises(ValueError, match="valid DXF"):
        converter.stage_input(source, tmp_path / "out")
