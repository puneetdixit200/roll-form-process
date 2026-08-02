"""Hidden-pass reconstruction benchmark with honest per-pass metrics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from rollform_extractor.flower_prototype_dataset import HistoricalFlower, HistoricalPass


@dataclass(frozen=True)
class ReconstructionCase:
    benchmark_id: str
    flower_id: str
    hidden_pass_id: str
    anchor_pass_ids: tuple[str, ...]
    reconstructed_shape: tuple[float, ...]
    metrics: dict[str, Any]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"reconstructed_shape": list(self.reconstructed_shape), "anchor_pass_ids": list(self.anchor_pass_ids)}


def benchmark_flower(flower: HistoricalFlower, *, hide_offsets: tuple[int, ...] = (1, 2, 3)) -> tuple[ReconstructionCase, ...]:
    cases = []
    for offset in hide_offsets:
        index = min(max(1, offset), len(flower.passes) - 2)
        hidden = flower.passes[index]
        previous = flower.passes[index - 1]
        following = flower.passes[index + 1]
        ratio = (hidden.inferred_order - previous.inferred_order) / max(1, following.inferred_order - previous.inferred_order)
        reconstructed = tuple(a + (b - a) * ratio for a, b in zip(previous.shape_vector, following.shape_vector))
        metrics = _metrics(hidden, reconstructed, previous, following, ratio)
        cases.append(ReconstructionCase(f"{flower.flower_id}-hide-{index:03d}", flower.flower_id, hidden.pass_id, (previous.pass_id, following.pass_id), reconstructed, metrics, "PASS" if metrics["shape_rms"] <= 0.15 else "REVIEW_REQUIRED"))
    return tuple(cases)


def benchmark_dataset(flowers: tuple[HistoricalFlower, ...]) -> dict[str, Any]:
    cases = tuple(case for flower in flowers for case in benchmark_flower(flower))
    values = [float(case.metrics["shape_rms"]) for case in cases]
    return {
        "schema_version": 1,
        "algorithm_version": "hidden_pass_interpolation_v1",
        "case_count": len(cases),
        "cases": [case.to_dict() for case in cases],
        "aggregate": {
            "mean_shape_rms": sum(values) / len(values) if values else None,
            "median_shape_rms": sorted(values)[len(values) // 2] if values else None,
            "maximum_shape_rms": max(values) if values else None,
            "pass_acceptance_count": sum(case.status == "PASS" for case in cases),
            "review_required_count": sum(case.status != "PASS" for case in cases),
        },
    }


def _metrics(original: HistoricalPass, reconstructed: tuple[float, ...], previous: HistoricalPass, following: HistoricalPass, ratio: float) -> dict[str, Any]:
    shape_rms = math.sqrt(sum((a - b) ** 2 for a, b in zip(original.shape_vector, reconstructed)) / max(1, len(reconstructed))) if len(original.shape_vector) == len(reconstructed) else 2.0
    width = previous.width + (following.width - previous.width) * ratio
    height = previous.height + (following.height - previous.height) * ratio
    length = previous.developed_length + (following.developed_length - previous.developed_length) * ratio
    bend_count = round(previous.bend_count + (following.bend_count - previous.bend_count) * ratio)
    return {
        "shape_rms": shape_rms,
        "width_error": width - original.width,
        "height_error": height - original.height,
        "developed_length_error": length - original.developed_length,
        "bend_count_difference": bend_count - original.bend_count,
        "topology_match": original.topology == previous.topology == following.topology,
        "source_evidence_coverage": 1.0,
        "method": "linear interpolation between adjacent visible anchors",
    }
