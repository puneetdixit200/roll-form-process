from __future__ import annotations

import json

from rollform_extractor.local_demo_configuration import apply_saved_demo_environment


def test_direct_backend_start_restores_saved_generation_configuration(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text('{"flowers": []}', encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    config = tmp_path / "visual-flower-demo.json"
    config.write_text(
        json.dumps({"dataset": str(dataset), "model": str(model)}),
        encoding="utf-8",
    )
    environ = {"ROLLFORM_DEMO_CONFIG": str(config)}

    applied = apply_saved_demo_environment(environ)

    assert environ["ROLLFORM_FLOWER_PROTOTYPE_DATASET"] == str(dataset)
    assert environ["ROLLFORM_ACTIVE_CLRSG_MODEL"] == str(model)
    assert applied == {
        "ROLLFORM_ACTIVE_CLRSG_MODEL": str(model),
        "ROLLFORM_FLOWER_PROTOTYPE_DATASET": str(dataset),
    }


def test_explicit_generation_configuration_wins_over_saved_value(tmp_path):
    saved = tmp_path / "saved.json"
    explicit = tmp_path / "explicit.json"
    saved.write_text("{}", encoding="utf-8")
    explicit.write_text("{}", encoding="utf-8")
    config = tmp_path / "visual-flower-demo.json"
    config.write_text(json.dumps({"dataset": str(saved)}), encoding="utf-8")
    environ = {
        "ROLLFORM_DEMO_CONFIG": str(config),
        "ROLLFORM_FLOWER_PROTOTYPE_DATASET": str(explicit),
    }

    apply_saved_demo_environment(environ)

    assert environ["ROLLFORM_FLOWER_PROTOTYPE_DATASET"] == str(explicit)
