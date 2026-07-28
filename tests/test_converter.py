from __future__ import annotations

from pathlib import Path
import subprocess

import ezdxf
import pytest

from rollform_extractor import converter
from rollform_extractor.converter import ConversionUnavailableError, ConverterSpec
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


def test_libredwg_converts_from_temp_copy_not_original(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")
    before = sha256_file(source)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        input_path = Path(command[-1])
        assert input_path != source
        assert input_path.read_bytes() == b"AC1027"
        write_sample_dxf(Path(command[2]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        converter, "discover_converter", lambda: ConverterSpec("libredwg", Path("dwg2dxf"))
    )
    monkeypatch.setattr(converter.subprocess, "run", fake_run)

    result = converter.stage_input(source, tmp_path / "out")

    assert result.converter == "libredwg"
    assert calls[0][0] == "dwg2dxf"
    assert sha256_file(source) == before


def test_converter_failure_still_checks_source_immutability(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")

    def corrupt_then_fail(executable, source_path, staged):
        source_path.write_bytes(b"changed")
        raise ConversionUnavailableError("converter failed")

    monkeypatch.setattr(
        converter, "discover_converter", lambda: ConverterSpec("libredwg", Path("dwg2dxf"))
    )
    monkeypatch.setattr(converter, "_run_libredwg", corrupt_then_fail)

    with pytest.raises(RuntimeError, match="source file was modified"):
        converter.stage_input(source, tmp_path / "out")


def test_libredwg_failure_keeps_ascii_dxf_guidance(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "bad dwg")

    monkeypatch.setattr(
        converter, "discover_converter", lambda: ConverterSpec("libredwg", Path("dwg2dxf"))
    )
    monkeypatch.setattr(converter.subprocess, "run", fake_run)

    with pytest.raises(ConversionUnavailableError) as excinfo:
        converter.stage_input(source, tmp_path / "out")

    message = str(excinfo.value)
    assert "AutoCAD 2013 or AutoCAD 2007 ASCII DXF" in message
    assert "bad dwg" in message


def test_oda_retries_ac1021_after_ac1027_failure(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")
    versions = []

    def fake_run(command, **kwargs):
        versions.append(command[3])
        input_dir = Path(command[1])
        assert input_dir != source.parent
        assert (input_dir / "part.dwg").read_bytes() == b"AC1027"
        assert command[4:7] == ["DXF", "0", "1"]
        if command[3] == "AC1021":
            write_sample_dxf(Path(command[2]) / "part.dxf")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "first failed")

    monkeypatch.setattr(
        converter, "discover_converter", lambda: ConverterSpec("oda", Path("ODAFileConverter"))
    )
    monkeypatch.setattr(converter.subprocess, "run", fake_run)

    result = converter.stage_input(source, tmp_path / "out")

    assert result.converter == "oda"
    assert versions == ["AC1027", "AC1021"]
