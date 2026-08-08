from rollform_extractor.strip_length_constraint import STRIP_LENGTH_CONSTRAINT_VERSION
from rollform_extractor.visual_flower_service import _generation_configuration
from rollform_extractor.visual_profile_schema import VISUAL_ALGORITHM_VERSION


def test_generation_cache_key_configuration_tracks_constant_length_algorithm():
    configuration = _generation_configuration({"station_mode": "EXACT", "exact_station_count": 16})
    assert configuration["visual_algorithm_version"] == VISUAL_ALGORITHM_VERSION
    assert configuration["strip_length_constraint_version"] == STRIP_LENGTH_CONSTRAINT_VERSION
    assert VISUAL_ALGORITHM_VERSION == "visual_sketch_history_match_v2_constant_length"
    assert STRIP_LENGTH_CONSTRAINT_VERSION == "constant_centerline_length_v1"
