from importlib import resources

import pytest

from rollform_extractor.config import ExtractionConfig


def test_default_configuration_has_engineering_tolerances():
    config = ExtractionConfig.load()
    assert config.geometry.endpoint_join_tolerance_mm == 0.05
    assert config.profiles.minimum_score_margin == 0.15


def test_stage_hash_changes_only_for_relevant_configuration():
    baseline = ExtractionConfig.load()
    changed = ExtractionConfig.load(overrides={"profiles": {"minimum_confidence": 0.8}})
    assert baseline.hash_for("profile_detection") != changed.hash_for("profile_detection")
    assert baseline.hash_for("conversion") == changed.hash_for("conversion")


def test_default_configuration_is_packaged_resource():
    assert resources.files("rollform_extractor").joinpath("config/default.yaml").is_file()
    assert ExtractionConfig.load().rollers.minimum_confidence == 0.65


def test_unknown_nested_configuration_key_is_rejected():
    with pytest.raises(KeyError, match="profiles.unused"):
        ExtractionConfig.load(overrides={"profiles": {"unused": 1}})
