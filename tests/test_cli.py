from __future__ import annotations

from rollform_extractor.cli import main
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
