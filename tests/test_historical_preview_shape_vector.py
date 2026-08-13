from __future__ import annotations

import json
from io import BytesIO

from PIL import Image

from rollform_extractor.visual_flower_service import historical_pass_preview


def test_historical_preview_renders_shape_vector_dataset(monkeypatch, tmp_path):
    dataset = {
        "dataset_id": "fixture",
        "dataset_hash": "fixture-hash",
        "flowers": [
            {
                "flower_id": "PRIVATE-FLOWER-001",
                "passes": [
                    {
                        "pass_id": "PRIVATE-FLOWER-001-pass-001",
                        "shape_vector": [-1.0, 0.0, -0.25, 0.45, 0.5, -0.2, 1.0, 0.1],
                        "topology": "OPEN_PATH",
                        "width": 2.0,
                        "height": 0.65,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    monkeypatch.setenv("ROLLFORM_FLOWER_PROTOTYPE_DATASET", str(path))

    preview = historical_pass_preview(
        "PRIVATE-FLOWER-001",
        "PRIVATE-FLOWER-001-pass-001",
    )

    assert preview is not None
    assert preview.startswith(b"\x89PNG\r\n\x1a\n")

    image = Image.open(BytesIO(preview)).convert("RGB")
    assert image.size == (520, 300)
    assert len(set(image.getdata())) > 2


def test_historical_preview_missing_pass_returns_none(monkeypatch, tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(
        json.dumps({"dataset_hash": "fixture", "flowers": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ROLLFORM_FLOWER_PROTOTYPE_DATASET", str(path))

    assert historical_pass_preview("missing", "missing") is None
