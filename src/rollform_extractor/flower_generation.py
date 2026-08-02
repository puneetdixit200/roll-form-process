"""History-constrained candidate flower generation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any

from rollform_extractor.flower_prototype_dataset import FlowerPrototypeDataset, HistoricalFlower, HistoricalPass
from rollform_extractor.flower_retrieval import HistoricalRetrievalResult, PrototypeTarget, retrieve_historical_flowers


GENERATION_ALGORITHM_VERSION = "history_constrained_backward_forward_v1"


@dataclass(frozen=True)
class GeneratedPass:
    pass_id: str
    inferred_order: int
    width: float
    height: float
    developed_length: float
    shape_vector: tuple[float, ...]
    source_flower_id: str
    source_pass_ids: tuple[str, ...]
    transformation: dict[str, Any]
    quality_flags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"shape_vector": list(self.shape_vector), "source_pass_ids": list(self.source_pass_ids), "quality_flags": list(self.quality_flags)}


@dataclass(frozen=True)
class GeneratedCandidate:
    candidate_id: str
    candidate_type: str
    source_flower_id: str
    station_count: int
    retrieval: HistoricalRetrievalResult
    passes: tuple[GeneratedPass, ...]
    status: str
    confidence: float
    warnings: tuple[str, ...]
    validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "algorithm_version": GENERATION_ALGORITHM_VERSION,
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "source_flower_id": self.source_flower_id,
            "station_count": self.station_count,
            "retrieval": self.retrieval.to_dict(),
            "passes": [item.to_dict() for item in self.passes],
            "status": self.status,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "validation": self.validation,
        }


def generate_candidates(
    dataset: FlowerPrototypeDataset,
    target: PrototypeTarget,
    *,
    minimum_stations: int = 8,
    maximum_stations: int = 28,
    result_limit: int = 3,
) -> tuple[GeneratedCandidate, ...]:
    minimum_stations = max(8, minimum_stations)
    maximum_stations = min(28, max(minimum_stations, maximum_stations))
    retrievals = retrieve_historical_flowers(dataset.flowers, target, limit=result_limit)
    flowers = {flower.flower_id: flower for flower in dataset.flowers}
    candidates = []
    for rank, retrieval in enumerate(retrievals, start=1):
        source = flowers[retrieval.flower_id]
        count = min(maximum_stations, max(minimum_stations, len(source.passes)))
        candidate_type = "TEMPLATE_ADAPTATION" if rank == 1 else "ALTERNATIVE_TEMPLATE_ADAPTATION"
        candidate = _generate_one(source, retrieval, target, count, candidate_type, rank)
        candidates.append(candidate)
    return tuple(candidates)


def _generate_one(source: HistoricalFlower, retrieval: HistoricalRetrievalResult, target: PrototypeTarget, count: int, candidate_type: str, rank: int) -> GeneratedCandidate:
    passes = []
    for index in range(count):
        progress = index / max(1, count - 1)
        source_position = progress * max(0, len(source.passes) - 1)
        lower_index = min(len(source.passes) - 1, int(math.floor(source_position)))
        upper_index = min(len(source.passes) - 1, int(math.ceil(source_position)))
        lower = source.passes[lower_index]
        upper = source.passes[upper_index]
        ratio = source_position - lower_index
        shape = _interpolate(lower.shape_vector, upper.shape_vector, ratio)
        if index == count - 1:
            shape = target.final_pass.shape_vector
        width = _interpolate_value(lower.width, upper.width, ratio)
        height = _interpolate_value(lower.height, upper.height, ratio)
        developed = _interpolate_value(lower.developed_length, upper.developed_length, ratio)
        if index == count - 1:
            width, height, developed = target.final_pass.width, target.final_pass.height, target.final_pass.developed_length
        flags = list(source.quality_flags)
        if lower.bend_count != upper.bend_count:
            flags.append("PROVISIONAL_UNSUPPORTED_BEND")
        passes.append(GeneratedPass(
            pass_id=f"{candidate_type.lower()}-pass-{index:03d}",
            inferred_order=index,
            width=width,
            height=height,
            developed_length=developed,
            shape_vector=shape,
            source_flower_id=source.flower_id,
            source_pass_ids=tuple(dict.fromkeys((lower.pass_id, upper.pass_id))),
            transformation={"forming_progress": progress, "source_position": source_position, "interpolation_ratio": ratio},
            quality_flags=tuple(sorted(set(flags))),
        ))
    validation = _forward_validate(passes, target.final_pass)
    warnings = list(retrieval.warnings)
    warnings.extend(validation["warnings"])
    confidence = max(0.0, min(1.0, retrieval.score * retrieval.evidence_coverage * (0.85 if warnings else 1.0)))
    status = "INSUFFICIENT_HISTORICAL_SUPPORT" if retrieval.status in {"LOW_HISTORICAL_SUPPORT", "INSUFFICIENT_EVIDENCE", "TOPOLOGY_MISMATCH"} else validation["status"]
    candidate_id = "fgc-" + sha256(f"{source.flower_id}|{target.target_id}|{count}|{candidate_type}".encode()).hexdigest()[:16]
    return GeneratedCandidate(candidate_id, candidate_type, source.flower_id, count, retrieval, tuple(passes), status, confidence, tuple(sorted(set(warnings))), validation)


def _forward_validate(passes: list[GeneratedPass], target: HistoricalPass) -> dict[str, Any]:
    final = passes[-1]
    shape_rms = _rms(final.shape_vector, target.shape_vector)
    length_error = final.developed_length - target.developed_length
    relative_length_error = abs(length_error) / max(abs(target.developed_length), 1e-9)
    widths = [item.width for item in passes]
    heights = [item.height for item in passes]
    warnings: list[str] = []
    if relative_length_error > 0.02:
        warnings.append("INVALID_DEVELOPED_LENGTH")
    if any(item.inferred_order != index for index, item in enumerate(passes)):
        warnings.append("INVALID_STATION_ORDER")
    if any(item.quality_flags for item in passes):
        warnings.append("PASS_QUALITY_WARNINGS")
    status = "PASS_PROTOTYPE_GEOMETRY" if not warnings and shape_rms <= 0.05 else "PASS_WITH_WARNINGS" if shape_rms <= 0.15 else "FINAL_TARGET_MISMATCH"
    return {"status": status, "shape_rms": shape_rms, "developed_length_error": length_error, "developed_length_relative_error": relative_length_error, "width_range": [min(widths), max(widths)], "height_range": [min(heights), max(heights)], "warnings": warnings}


def _interpolate(left: tuple[float, ...], right: tuple[float, ...], ratio: float) -> tuple[float, ...]:
    if len(left) != len(right):
        return left if ratio < 0.5 else right
    return tuple(round(a + (b - a) * ratio, 8) for a, b in zip(left, right))


def _interpolate_value(left: float, right: float, ratio: float) -> float:
    return left + (right - left) * ratio


def _rms(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 2.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))
