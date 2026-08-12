from __future__ import annotations

import subprocess

from rollform_extractor.flower_alignment import align_flowers
from rollform_extractor.flower_generation import generate_candidates
from rollform_extractor.flower_prototype_dataset import HistoricalFlower, HistoricalPass, build_dataset
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
