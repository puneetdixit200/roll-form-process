from __future__ import annotations

import subprocess

import ezdxf

from rollform_extractor.flower_alignment import align_flowers
from rollform_extractor.flower_generation import generate_candidates
from rollform_extractor.flower_prototype_dataset import HistoricalFlower, HistoricalPass, build_dataset, ingest_private_flower
from rollform_extractor.flower_reconstruction_benchmark import benchmark_dataset
from rollform_extractor.flower_retrieval import target_from_pass, retrieve_historical_flowers


def make_pass(flower: str, order: int, shift: float = 0.0) -> HistoricalPass:
    points = ((shift, 0.0, 0.0), (shift + 2.0, 0.0, 0.0), (shift + 2.0, 1.0 + order * .1, 0.0), (shift, 1.0 + order * .1, 0.0), (shift, 0.0, 0.0))
    shape = tuple(value for point in ((-1.0, -.5), (1.0, -.5), (1.0, .5), (-1.0, .5)) for value in point)
    return HistoricalPass(f"{flower}-p-{order:02d}", flower, f"H{order:02d}", order, points, ((-1.0, -.5), (1.0, -.5), (1.0, .5), (-1.0, .5)), shape, 2.0, 1.0 + order * .1, 6.0, 3.0, (90.0,), (.25,), ("UP_BEND",), "CLOSED_SINGLE_LOOP", (), "source")


def make_flower(name: str, count: int) -> HistoricalFlower:
    passes = tuple(make_pass(name, index, index * .2) for index in range(count))
    return HistoricalFlower(name, "SYNTHETIC_DERIVED", "source", 4, count, passes, "CLOSED_SINGLE_LOOP", ())


def test_retrieval_generation_and_benchmark_are_deterministic():
    flowers = (make_flower("F1", 8), make_flower("F2", 10))
    dataset = build_dataset(flowers, ())
    target = target_from_pass(flowers[1].passes[-1], target_id="T", scale_x=1.01)
    first = [item.to_dict() for item in retrieve_historical_flowers(flowers, target)]
    second = [item.to_dict() for item in retrieve_historical_flowers(flowers, target)]
    assert first == second
    candidates = generate_candidates(dataset, target)
    assert candidates
    assert all(8 <= item.station_count <= 28 for item in candidates)
    assert all(item.passes[-1].source_pass_ids for item in candidates)
    benchmark = benchmark_dataset(flowers)
    assert benchmark["case_count"] == 6
    assert "width_error" in benchmark["cases"][0]["metrics"]


def test_alignment_is_monotonic_and_supports_different_lengths():
    alignment = align_flowers(make_flower("F1", 8), make_flower("F2", 10))
    pairs = [(pair.source_order, pair.target_order) for pair in alignment.pairs if pair.source_order is not None and pair.target_order is not None]
    assert pairs == sorted(pairs)
    assert alignment.status in {"ALIGNED", "PASS_WITH_WARNINGS"}


def test_private_cad_is_not_tracked():
    names = subprocess.check_output(["git", "ls-files", "*.dwg", "*.dxf"], text=True).splitlines()
    assert names == []


def test_composite_flower_ingestion_uses_only_detected_ordered_passes(monkeypatch, tmp_path):
    source = tmp_path / "mixed-drawing.dxf"
    document = ezdxf.new("R2013")
    modelspace = document.modelspace()
    expected = tuple(modelspace.add_polyline3d([(0, 0, 0), (2, index, 0), (4, 0, 0)]) for index in range(3))
    modelspace.add_line((0, 20), (20, 20))
    document.saveas(source)
    monkeypatch.setattr(
        "rollform_extractor.flower_prototype_dataset._detected_composite_pass_entities",
        lambda _document, _path: (expected, True),
    )

    flower = ingest_private_flower(
        source,
        tmp_path / "private",
        "PRIVATE-FLOWER-003",
        source_station_count=3,
        extractor_mode="COMPOSITE_FLOWER",
    )

    assert flower.extractor_mode_used == "COMPOSITE_FLOWER"
    assert len(flower.passes) == 3
    assert [item.inferred_order for item in flower.passes] == [0, 1, 2]
    assert "COMPOSITE_PASS_ORDER_INFERRED_REVIEW_REQUIRED" in flower.quality_flags


def test_station_sequence_ingestion_records_distinct_source_region(monkeypatch, tmp_path):
    source = tmp_path / "two-sequences.dxf"
    document = ezdxf.new("R2013")
    modelspace = document.modelspace()
    first = tuple(modelspace.add_polyline3d([(0, 0, 0), (2, index, 0), (4, 0, 0)]) for index in range(2))
    second = tuple(modelspace.add_polyline3d([(0, 5, 0), (2, 5 + index, 0), (4, 5, 0)]) for index in range(3))
    document.saveas(source)

    def select(_document, _path, selector):
        return (first, "sequence_01") if selector == "1" else (second, "sequence_02")

    monkeypatch.setattr(
        "rollform_extractor.flower_prototype_dataset._detected_station_sequence_pass_entities",
        select,
    )
    flower_1 = ingest_private_flower(source, tmp_path / "private-1", "F1", extractor_mode="STATION_SEQUENCE:1")
    flower_2 = ingest_private_flower(source, tmp_path / "private-2", "F2", extractor_mode="STATION_SEQUENCE:2")

    assert len(flower_1.passes) == 2
    assert len(flower_2.passes) == 3
    assert flower_1.source_region_id == "sequence_01"
    assert flower_2.source_region_id == "sequence_02"
    assert "STATION_SEQUENCE_ORDER_INFERRED_REVIEW_REQUIRED" in flower_1.quality_flags
    assert flower_1.source_sha256 == flower_2.source_sha256
    assert len(build_dataset((flower_1, flower_2), ()).flowers) == 2


def test_dataset_rejects_duplicate_source_region():
    first = make_flower("F1", 8)
    second = HistoricalFlower(
        "F2",
        first.source_classification,
        "same-sha",
        first.source_entity_count,
        first.raw_profile_count,
        first.passes,
        first.topology,
        first.quality_flags,
        source_region_id="sequence_01",
    )
    duplicate = HistoricalFlower(
        "F3",
        second.source_classification,
        second.source_sha256,
        second.source_entity_count,
        second.raw_profile_count,
        second.passes,
        second.topology,
        second.quality_flags,
        source_region_id="sequence_01",
    )

    import pytest

    with pytest.raises(ValueError, match="DUPLICATE_HISTORICAL_SOURCE_REGION"):
        build_dataset((second, duplicate), ())
