from rollform_extractor.flower_roller_evidence import FLOWER_ROLLER_EVIDENCE_VERSION
from rollform_extractor.strip_length_constraint import STRIP_LENGTH_CONSTRAINT_VERSION
from rollform_extractor.visual_flower_service import _generation_configuration, _roller_station_evidence_hash
from rollform_extractor.visual_profile_schema import VISUAL_ALGORITHM_VERSION


def test_generation_cache_key_configuration_tracks_constant_length_algorithm():
    configuration = _generation_configuration({"station_mode": "EXACT", "exact_station_count": 16})
    assert configuration["visual_algorithm_version"] == VISUAL_ALGORITHM_VERSION
    assert configuration["strip_length_constraint_version"] == STRIP_LENGTH_CONSTRAINT_VERSION
    assert configuration["flower_roller_evidence_version"] == FLOWER_ROLLER_EVIDENCE_VERSION
    assert VISUAL_ALGORITHM_VERSION == "visual_sketch_history_match_v2_constant_length"
    assert STRIP_LENGTH_CONSTRAINT_VERSION == "constant_centerline_length_v1"


def test_generation_configuration_changes_with_inventory_snapshot():
    preferences = {"station_mode": "EXACT", "exact_station_count": 16, "include_roller_evidence": True}
    first = _generation_configuration(preferences, inventory_snapshot_hash="inventory-a")
    second = _generation_configuration(preferences, inventory_snapshot_hash="inventory-b")

    assert first["inventory_snapshot_hash"] == "inventory-a"
    assert second["inventory_snapshot_hash"] == "inventory-b"
    assert first != second


def test_generation_configuration_ignores_inventory_when_roller_evidence_disabled():
    preferences = {"station_mode": "EXACT", "exact_station_count": 16, "include_roller_evidence": False}
    first = _generation_configuration(preferences, inventory_snapshot_hash="inventory-a", roller_station_evidence_hash="history-a")
    second = _generation_configuration(preferences, inventory_snapshot_hash="inventory-b", roller_station_evidence_hash="history-b")

    assert first["inventory_snapshot_hash"] == "DISABLED"
    assert first["roller_station_evidence_hash"] == "DISABLED"
    assert first == second


def test_station_level_roller_evidence_has_independent_cache_hash():
    first = _roller_station_evidence_hash({
        "dataset_hash": "same-flower-data",
        "roller_station_evidence": [{"flower_id": "F1", "pass_id": "P1", "design_id": "RD-1"}],
    })
    second = _roller_station_evidence_hash({
        "dataset_hash": "same-flower-data",
        "roller_station_evidence": [{"flower_id": "F1", "pass_id": "P1", "design_id": "RD-2"}],
    })

    assert first != second
