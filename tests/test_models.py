from types import MappingProxyType

import pytest

from rollform_extractor.models import ProfileRecord


def test_model_mappings_are_immutable_copies():
    features = {"width_mm": 42}
    record = ProfileRecord(
        profile_id="P1",
        station_id="S1",
        source_handles=("AB",),
        method="profile_detection",
        configuration_hash="abc123",
        confidence=0.9,
        features=features,
    )

    features["width_mm"] = 99

    assert record.features == MappingProxyType({"width_mm": 42})
    with pytest.raises(TypeError):
        record.features["height_mm"] = 10
