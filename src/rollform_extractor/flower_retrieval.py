"""Explainable retrieval of historical flower templates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from rollform_extractor.flower_prototype_dataset import HistoricalFlower, HistoricalPass


@dataclass(frozen=True)
class PrototypeTarget:
    target_id: str
    final_pass: HistoricalPass
    source_classification: str
    derivation: dict[str, Any]
    units_status: str = "UNCONFIRMED"


@dataclass(frozen=True)
class RetrievalComponent:
    score: float | None
    weight: float
    available: bool
    reason: str | None = None


@dataclass(frozen=True)
class HistoricalRetrievalResult:
    flower_id: str
    score: float
    evidence_coverage: float
    status: str
    components: dict[str, RetrievalComponent]
    source_pass_id: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "flower_id": self.flower_id,
            "score": self.score,
            "evidence_coverage": self.evidence_coverage,
            "status": self.status,
            "source_pass_id": self.source_pass_id,
            "components": {key: component.__dict__ for key, component in self.components.items()},
            "warnings": list(self.warnings),
        }


DEFAULT_WEIGHTS = {
    "shape_similarity": 0.40,
    "width_similarity": 0.15,
    "height_similarity": 0.15,
    "developed_length_similarity": 0.10,
    "bend_count_similarity": 0.08,
    "bend_position_similarity": 0.07,
    "topology_compatibility": 0.05,
}


def target_from_pass(pass_record: HistoricalPass, target_id: str, *, scale_x: float = 1.0, scale_y: float = 1.0) -> PrototypeTarget:
    if scale_x == 1.0 and scale_y == 1.0:
        target_pass = pass_record
    else:
        points = tuple((x * scale_x, y * scale_y, z) for x, y, z in pass_record.points)
        target_pass = HistoricalPass(
            **{**pass_record.__dict__, "points": points, "width": pass_record.width * scale_x, "height": pass_record.height * scale_y,
               "outline_perimeter": pass_record.outline_perimeter * ((abs(scale_x) + abs(scale_y)) / 2.0),
               "developed_length": pass_record.developed_length * ((abs(scale_x) + abs(scale_y)) / 2.0)}
        )
    return PrototypeTarget(
        target_id=target_id,
        final_pass=target_pass,
        source_classification="SYNTHETIC_DERIVED" if scale_x != 1.0 or scale_y != 1.0 else "PRIVATE_PROTOTYPE",
        derivation={"parent_pass_id": pass_record.pass_id, "scale_x": scale_x, "scale_y": scale_y},
    )


def retrieve_historical_flowers(
    flowers: Iterable[HistoricalFlower],
    target: PrototypeTarget,
    *,
    limit: int = 3,
    weights: dict[str, float] | None = None,
    minimum_score: float = 0.35,
) -> tuple[HistoricalRetrievalResult, ...]:
    weights = weights or DEFAULT_WEIGHTS
    results = []
    for flower in flowers:
        if not flower.passes:
            continue
        final = flower.passes[-1]
        components = _components(final, target.final_pass, weights)
        available_weight = sum(item.weight for item in components.values() if item.available)
        weighted = sum((item.score or 0.0) * item.weight for item in components.values() if item.available)
        score = weighted / available_weight if available_weight else 0.0
        coverage = available_weight / sum(weights.values()) if weights else 0.0
        warnings = list(flower.quality_flags)
        status = _status(score, coverage, components, minimum_score)
        if target.units_status != "CONFIRMED":
            warnings.append("NO_VERIFIED_DIMENSIONAL_CLAIM")
        results.append(HistoricalRetrievalResult(flower.flower_id, score, coverage, status, components, final.pass_id, tuple(sorted(set(warnings)))))
    return tuple(sorted(results, key=lambda item: (-item.score, -item.evidence_coverage, item.flower_id))[:limit])


def _components(source: HistoricalPass, target: HistoricalPass, weights: dict[str, float]) -> dict[str, RetrievalComponent]:
    values: dict[str, tuple[float | None, str | None]] = {
        "shape_similarity": (_shape_similarity(source.shape_vector, target.shape_vector), None),
        "width_similarity": (_relative_similarity(source.width, target.width), None),
        "height_similarity": (_relative_similarity(source.height, target.height), None),
        "developed_length_similarity": (_relative_similarity(source.developed_length, target.developed_length), None),
        "bend_count_similarity": (_relative_similarity(source.bend_count, target.bend_count), None),
        "bend_position_similarity": (_sequence_similarity(source.bend_positions, target.bend_positions), None),
        "topology_compatibility": (1.0 if source.topology == target.topology else 0.0, None),
    }
    return {key: RetrievalComponent(score=value[0], weight=weights.get(key, 0.0), available=value[0] is not None, reason=value[1]) for key, value in values.items()}


def _status(score: float, coverage: float, components: dict[str, RetrievalComponent], minimum_score: float) -> str:
    topology = components["topology_compatibility"]
    if not topology.available or topology.score == 0.0:
        return "TOPOLOGY_MISMATCH"
    if coverage < 0.40:
        return "INSUFFICIENT_EVIDENCE"
    if score < minimum_score:
        return "LOW_HISTORICAL_SUPPORT"
    if score >= 0.90:
        return "EXACT_HISTORICAL_FINAL" if score >= 0.995 else "HIGH_SIMILARITY_HISTORICAL_FINAL"
    if score >= 0.70:
        return "MEDIUM_SIMILARITY_HISTORICAL_FINAL"
    return "LOW_HISTORICAL_SUPPORT"


def _shape_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    rms = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))
    return max(0.0, min(1.0, 1.0 - rms / 2.0))


def _relative_similarity(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    scale = max(abs(float(left)), abs(float(right)), 1e-9)
    return max(0.0, min(1.0, 1.0 - abs(float(left) - float(right)) / scale))


def _sequence_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    if not left or not right:
        return None
    n = max(len(left), len(right))
    values = []
    for index in range(n):
        a = left[min(index, len(left) - 1)]
        b = right[min(index, len(right) - 1)]
        values.append(max(0.0, 1.0 - abs(a - b)))
    return sum(values) / len(values)
