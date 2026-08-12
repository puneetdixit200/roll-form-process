import json
from pathlib import Path

from scripts import run_visual_flower_demo as demo


def test_saved_configuration_survives_clean_shell(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.json"
    dataset.write_text('{"flowers": []}', encoding="utf-8")
    model = tmp_path / "model"
    registry = tmp_path / "registry"
    model.mkdir()
    registry.mkdir()
    config = tmp_path / "visual-flower-demo.json"
    monkeypatch.setenv("ROLLFORM_DEMO_CONFIG", str(config))
    for name in demo.CONFIG_KEYS.values():
        monkeypatch.delenv(name, raising=False)

    result = demo.configure(
        str(dataset),
        str(model),
        str(registry),
    )
    runtime = demo._runtime_environment()

    assert result["status"] == "PASS"
    assert config.stat().st_mode & 0o777 == 0o600
    assert runtime["ROLLFORM_FLOWER_PROTOTYPE_DATASET"] == str(dataset)
    assert runtime["ROLLFORM_ACTIVE_CLRSG_MODEL"] == str(model)
    assert runtime["ROLLFORM_MODEL_REGISTRY_ROOT"] == str(registry)
    assert str(dataset) not in json.dumps(result)


def test_shell_configuration_overrides_saved_configuration(tmp_path, monkeypatch):
    saved = tmp_path / "saved-dataset.json"
    explicit = tmp_path / "explicit-dataset.json"
    saved.write_text("{}", encoding="utf-8")
    explicit.write_text("{}", encoding="utf-8")
    config = tmp_path / "visual-flower-demo.json"
    config.write_text(json.dumps({"dataset": str(saved)}), encoding="utf-8")
    monkeypatch.setenv("ROLLFORM_DEMO_CONFIG", str(config))
    monkeypatch.setenv("ROLLFORM_FLOWER_PROTOTYPE_DATASET", str(explicit))

    assert (
        demo._runtime_environment()["ROLLFORM_FLOWER_PROTOTYPE_DATASET"]
        == str(explicit)
    )
