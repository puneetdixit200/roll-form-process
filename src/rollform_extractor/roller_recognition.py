"""Deterministic, explainable roller-design candidate recognition.

This module intentionally returns design candidates only.  It never assigns a
physical roller asset and never recommends a tooling set.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from typing import Any, Iterable, Mapping, Sequence

ROLLER_RECOGNITION_FEATURE_SCHEMA_VERSION = 1
ROLLER_RECOGNITION_ALGORITHM_VERSION = "roller-recognition-v1"
ROLLER_SCALAR_FEATURE_FIELDS = (
    "outer_diameter_mm", "bore_diameter_mm", "face_width_mm", "profile_width_mm",
    "profile_depth_mm", "profile_area_mm2", "groove_count", "mean_curvature",
    "maximum_curvature", "symmetry_score", "extraction_confidence",
)
ROLLER_SHAPE_FEATURE_FIELDS = tuple(f"shape_{index:03d}" for index in range(128))
KNOWN_UNITS = {"mm", "millimetre", "millimeter", "in", "inch", "cm", "m"}


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _hash(value: Any) -> str:
    payload = json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dimension_mm(dimensions: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        item = dimensions.get(name)
        if isinstance(item, Mapping):
            value = _number(item.get("millimetres"))
            if value is not None:
                return value
        value = _number(item)
        if value is not None:
            return value
    return None


@dataclass(frozen=True)
class RollerRecognitionInput:
    schema_version: int
    project_id: str
    occurrence_id: str
    station_id: str | None
    role: str | None
    source_handles: tuple[str, ...]
    source_layers: tuple[str, ...]
    units_status: str
    dimensions: Mapping[str, float | None]
    normalized_dimensions_mm: Mapping[str, float | None]
    geometry_descriptor: Mapping[str, Any]
    shape_vector: tuple[float, ...]
    missing_mask: tuple[bool, ...]
    physical_fingerprint: str | None
    shape_fingerprint: str | None
    extraction_confidence: float
    quality_flags: tuple[str, ...]
    configuration_hash: str
    input_hash: str = ""

    def __post_init__(self) -> None:
        if not self.input_hash:
            object.__setattr__(self, "input_hash", _hash({k: getattr(self, k) for k in self.__dataclass_fields__ if k != "input_hash"}))

    @property
    def quality(self) -> str:
        if "INVALID_GEOMETRY" in self.quality_flags:
            return "INVALID"
        if self.units_status.upper() in {"UNKNOWN", "UNCONFIRMED", "MIXED"}:
            return "UNKNOWN_UNITS"
        available = sum(not missing for missing in self.missing_mask)
        if not self.shape_vector and not any(value is not None for value in self.normalized_dimensions_mm.values()):
            return "INSUFFICIENT"
        if available and all(value is not None for value in self.normalized_dimensions_mm.values()):
            return "COMPLETE"
        if self.shape_vector and not any(value is not None for value in self.normalized_dimensions_mm.values()):
            return "SHAPE_ONLY"
        if any(value is not None for value in self.normalized_dimensions_mm.values()):
            return "PARTIAL"
        return "INSUFFICIENT"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["quality"] = self.quality
        return _json(data)


@dataclass(frozen=True)
class InventoryRevisionCandidate:
    design_id: str
    design_name: str | None
    design_type: str | None
    revision_id: str
    dimensions_mm: Mapping[str, float | None]
    geometry_descriptor: Mapping[str, Any]
    shape_vector: tuple[float, ...]
    physical_fingerprint: str | None
    shape_fingerprint: str | None
    unit_status: str
    verification_status: str
    eligibility: str
    confidence: float
    aliases: tuple[str, ...] = ()
    role: str | None = None
    machine: str | None = None
    superseded: bool = False
    source: str | None = None

    @property
    def candidate_key(self) -> str:
        return f"{self.design_id}:{self.revision_id}"


@dataclass(frozen=True)
class ScoreComponent:
    score: float | None
    weight: float
    available: bool
    reason: str | None = None
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json(asdict(self))


@dataclass(frozen=True)
class HardFilterResult:
    status: str
    reason: str


@dataclass(frozen=True)
class RecognitionCandidate:
    design_id: str
    design_name: str | None
    geometry_revision_id: str
    rank: int
    overall_score: float
    confidence: float
    evidence_coverage: float
    candidate_status: str
    components: Mapping[str, ScoreComponent]
    hard_filters: Mapping[str, HardFilterResult]
    explanation: Mapping[str, Any]
    inventory_verification_status: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["components"] = {name: component.to_dict() for name, component in self.components.items()}
        data["hard_filters"] = {name: asdict(value) for name, value in self.hard_filters.items()}
        return _json(data)


@dataclass(frozen=True)
class RecognitionResult:
    input: RollerRecognitionInput
    candidates: tuple[RecognitionCandidate, ...]
    status: str
    abstained: bool
    top_two_margin: float | None
    algorithm_version: str = ROLLER_RECOGNITION_ALGORITHM_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"input": self.input.to_dict(), "candidates": [item.to_dict() for item in self.candidates], "status": self.status, "abstained": self.abstained, "top_two_margin": self.top_two_margin, "algorithm_version": self.algorithm_version}


def prepare_recognition_input(
    project_id: str,
    occurrence: Any,
    *,
    units_status: str | None = None,
    normalized_dimensions_mm: Mapping[str, float | None] | None = None,
    geometry_descriptor: Mapping[str, Any] | None = None,
    configuration_hash: str = "",
) -> RollerRecognitionInput:
    evidence = _mapping(getattr(occurrence, "evidence", getattr(occurrence, "evidence_json", {})))
    dimensions = {
        "outer_diameter_mm": _number(evidence.get("outer_diameter_mm", evidence.get("diameter"))),
        "bore_diameter_mm": _number(evidence.get("bore_diameter_mm", evidence.get("bore"))),
        "face_width_mm": _number(evidence.get("width_mm", evidence.get("width"))),
        "profile_width_mm": _number(evidence.get("profile_width_mm")),
        "profile_depth_mm": _number(evidence.get("profile_depth_mm")),
        "profile_area_mm2": _number(evidence.get("profile_area_mm2")),
        "groove_count": _number(evidence.get("groove_count")),
        "mean_curvature": _number(evidence.get("mean_curvature")),
        "maximum_curvature": _number(evidence.get("maximum_curvature")),
        "symmetry_score": _number(evidence.get("symmetry_score")),
    }
    units = str(units_status or evidence.get("units_status") or "UNKNOWN").upper()
    normalized = dict(normalized_dimensions_mm or (dimensions if units == "CONFIRMED" else {key: None for key in dimensions}))
    descriptor = dict(geometry_descriptor or _mapping(evidence.get("geometry_descriptor")))
    shape_values = evidence.get("shape_vector", descriptor.get("shape_vector", ()))
    shape = tuple(_number(value) or 0.0 for value in shape_values) if isinstance(shape_values, (list, tuple)) else ()
    mask_values = evidence.get("missing_mask", descriptor.get("missing_mask"))
    missing = tuple(bool(value) for value in mask_values) if isinstance(mask_values, (list, tuple)) else tuple(value is None for value in shape)
    flags = set(str(flag) for flag in evidence.get("quality_flags", ()) or ())
    for name, value in dimensions.items():
        if value is None:
            flags.add({"outer_diameter_mm": "MISSING_DIAMETER", "bore_diameter_mm": "MISSING_BORE", "face_width_mm": "MISSING_WIDTH"}.get(name, "MISSING_GEOMETRY"))
    if units != "CONFIRMED":
        flags.add("UNCONFIRMED_UNITS")
    if not shape and not any(value is not None for value in normalized.values()):
        flags.add("INSUFFICIENT_SOURCE_GEOMETRY")
    source_layers = evidence.get("source_layers", ())
    return RollerRecognitionInput(
        schema_version=ROLLER_RECOGNITION_FEATURE_SCHEMA_VERSION,
        project_id=str(project_id),
        occurrence_id=str(getattr(occurrence, "occurrence_id", getattr(occurrence, "id", "unknown"))),
        station_id=getattr(occurrence, "station_id", None),
        role=getattr(occurrence, "role", None) or evidence.get("candidate_role"),
        source_handles=tuple(str(value) for value in getattr(occurrence, "source_handles", ()) or evidence.get("source_handles", ())),
        source_layers=tuple(str(value) for value in source_layers) if isinstance(source_layers, (list, tuple)) else (),
        units_status=units,
        dimensions=dimensions,
        normalized_dimensions_mm=normalized,
        geometry_descriptor=descriptor,
        shape_vector=shape,
        missing_mask=missing,
        physical_fingerprint=evidence.get("physical_fingerprint"),
        shape_fingerprint=evidence.get("shape_fingerprint"),
        extraction_confidence=_clamp(_number(getattr(occurrence, "confidence", evidence.get("confidence", 0.0))) or 0.0),
        quality_flags=tuple(sorted(flags)),
        configuration_hash=configuration_hash,
    )


def inventory_revision_from_row(row: Any, *, aliases: Sequence[str] = ()) -> InventoryRevisionCandidate:
    dimensions_json = _mapping(getattr(row, "dimensions_json", {}))
    dimensions = {key: _dimension_mm(dimensions_json, key, {"outer_diameter_mm": "diameter", "bore_diameter_mm": "bore", "face_width_mm": "width"}.get(key, key)) for key in ("outer_diameter_mm", "bore_diameter_mm", "face_width_mm", "profile_width_mm", "profile_depth_mm", "profile_area_mm2", "groove_count", "mean_curvature", "maximum_curvature", "symmetry_score")}
    design = getattr(row, "design", None)
    design_id = str(getattr(row, "design_id", getattr(design, "design_id", "")))
    verification = str(getattr(row, "verification_status", "UNVERIFIED") or "UNVERIFIED").upper()
    unit_status = str(getattr(row, "unit_status", "UNKNOWN") or "UNKNOWN").upper()
    if getattr(row, "superseded", False):
        eligibility = "SUPERSEDED"
    elif unit_status != "CONFIRMED":
        eligibility = "UNKNOWN_UNITS_BLOCKED"
    elif verification == "VERIFIED" and getattr(row, "physical_fingerprint", None) is not None:
        eligibility = "VERIFIED_ELIGIBLE"
    elif verification == "VERIFIED":
        eligibility = "REVIEW_REQUIRED"
    else:
        eligibility = "UNVERIFIED_CANDIDATE"
    descriptor = _mapping(dimensions_json.get("geometry_descriptor"))
    shape_vector = dimensions_json.get("shape_vector", descriptor.get("shape_vector", ()))
    return InventoryRevisionCandidate(
        design_id=design_id,
        design_name=getattr(design, "name", None),
        design_type=getattr(design, "design_type", None),
        revision_id=str(getattr(row, "revision_id", "")),
        dimensions_mm=dimensions,
        geometry_descriptor=descriptor,
        shape_vector=tuple(_number(value) or 0.0 for value in shape_vector) if isinstance(shape_vector, (list, tuple)) else (),
        physical_fingerprint=getattr(row, "physical_fingerprint", None),
        shape_fingerprint=getattr(row, "shape_fingerprint", None),
        unit_status=unit_status,
        verification_status=verification,
        eligibility=eligibility,
        confidence=_clamp(_number(getattr(row, "confidence", 0.0)) or 0.0),
        aliases=tuple(aliases),
        role=descriptor.get("role"),
        machine=descriptor.get("machine"),
        superseded=eligibility == "SUPERSEDED",
        source=getattr(row, "source", None),
    )


def eligible_inventory_revisions(revisions: Iterable[InventoryRevisionCandidate], *, allow_unknown_unit_shape_matching: bool = True) -> tuple[InventoryRevisionCandidate, ...]:
    result = []
    for revision in revisions:
        if revision.eligibility in {"VERIFIED_ELIGIBLE", "UNVERIFIED_CANDIDATE"}:
            result.append(revision)
        elif revision.eligibility == "UNKNOWN_UNITS_BLOCKED" and allow_unknown_unit_shape_matching and revision.shape_vector:
            result.append(revision)
    return tuple(sorted(result, key=lambda item: (item.design_id, item.revision_id)))


def _similarity(left: float | None, right: float | None, absolute_tolerance: float) -> ScoreComponent:
    if left is None or right is None:
        return ScoreComponent(None, 0.0, False, "value unavailable")
    scale = max(abs(left), abs(right), absolute_tolerance)
    return ScoreComponent(_clamp(1.0 - abs(left - right) / max(absolute_tolerance, scale)), 1.0, True)


def _shape_similarity(left: Sequence[float], right: Sequence[float], maximum_distance: float) -> ScoreComponent:
    if not left or not right:
        return ScoreComponent(None, 0.0, False, "shape unavailable")
    count = min(len(left), len(right))
    distance = math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(count)) / count)
    return ScoreComponent(_clamp(1.0 - distance / max(maximum_distance, 1e-12)), 1.0, True, evidence=f"normalized_distance={distance:.6f}")


def _config_values(config: Any) -> tuple[Mapping[str, float], Mapping[str, float], Mapping[str, float], bool]:
    if config is None:
        return ({"shape_similarity": .35, "physical_profile_similarity": .20, "diameter_similarity": .10, "bore_similarity": .10, "width_similarity": .10, "groove_similarity": .05, "curvature_similarity": .05, "role_compatibility": .05}, {"diameter_absolute_mm": 1.0, "bore_absolute_mm": .5, "width_absolute_mm": 1.0, "shape_distance_max": .20}, {"exact_candidate": .995, "high_candidate": .90, "medium_candidate": .75, "minimum_candidate": .55, "minimum_evidence_coverage": .40, "automatic_abstention_margin": .05}, True)
    if isinstance(config, Mapping):
        return (_mapping(config.get("weights", {})), _mapping(config.get("tolerances", {})), _mapping(config.get("thresholds", {})), bool(config.get("allow_unknown_unit_shape_matching", True)))
    return (_mapping(getattr(config, "weights", {})), _mapping(getattr(config, "tolerances", {})), _mapping(getattr(config, "thresholds", {})), bool(getattr(config, "allow_unknown_unit_shape_matching", True)))


def score_candidate(input_data: RollerRecognitionInput, candidate: InventoryRevisionCandidate, config: Any = None) -> tuple[float, float, Mapping[str, ScoreComponent], Mapping[str, HardFilterResult]]:
    weights, tolerances, _, _ = _config_values(config)
    hard: dict[str, HardFilterResult] = {}
    if input_data.role and candidate.role:
        hard["role"] = HardFilterResult("PASS" if input_data.role == candidate.role else "FAIL", "role matches" if input_data.role == candidate.role else "role contradicts")
    else:
        hard["role"] = HardFilterResult("UNKNOWN", "role unavailable")
    if input_data.units_status != "CONFIRMED" and not candidate.shape_vector:
        hard["units"] = HardFilterResult("FAIL", "unknown units block dimensional matching")
    else:
        hard["units"] = HardFilterResult("PASS" if input_data.units_status == "CONFIRMED" else "UNKNOWN", "dimensional units confirmed" if input_data.units_status == "CONFIRMED" else "shape-only comparison")
    if candidate.superseded:
        hard["revision"] = HardFilterResult("FAIL", "revision is superseded")
    else:
        hard["revision"] = HardFilterResult("PASS", "revision is eligible")
    for key, name, tolerance_key in (("outer_diameter_mm", "diameter", "diameter_absolute_mm"), ("bore_diameter_mm", "bore", "bore_absolute_mm"), ("face_width_mm", "width", "width_absolute_mm")):
        left = input_data.normalized_dimensions_mm.get(key)
        right = candidate.dimensions_mm.get(key)
        tolerance = float(tolerances.get(tolerance_key, 1.0))
        if left is None or right is None or input_data.units_status != "CONFIRMED":
            hard[name] = HardFilterResult("UNKNOWN", "dimension unavailable for hard comparison")
        elif abs(left - right) <= tolerance:
            hard[name] = HardFilterResult("PASS", "dimension within configured tolerance")
        else:
            hard[name] = HardFilterResult("FAIL", f"dimension differs by {abs(left - right):.6f}")
    components: dict[str, ScoreComponent] = {}
    if input_data.physical_fingerprint and input_data.physical_fingerprint == candidate.physical_fingerprint:
        components["physical_fingerprint_exact"] = ScoreComponent(1.0, 1.0, True, evidence="exact verified physical fingerprint")
    if input_data.shape_fingerprint and input_data.shape_fingerprint == candidate.shape_fingerprint:
        components["shape_fingerprint_exact"] = ScoreComponent(1.0, 1.0, True, evidence="exact verified shape fingerprint")
    shape = _shape_similarity(input_data.shape_vector, candidate.shape_vector, float(tolerances.get("shape_distance_max", .20)))
    components["shape_similarity"] = ScoreComponent(shape.score, float(weights.get("shape_similarity", .35)), shape.available, shape.reason, shape.evidence)
    physical_values = []
    for key in ("outer_diameter_mm", "bore_diameter_mm", "face_width_mm"):
        left, right = input_data.normalized_dimensions_mm.get(key), candidate.dimensions_mm.get(key)
        if left is not None and right is not None:
            physical_values.append(abs(left - right) / max(abs(left), abs(right), 1e-9))
    profile = ScoreComponent(_clamp(1.0 - sum(physical_values) / len(physical_values)) if physical_values else None, float(weights.get("physical_profile_similarity", .20)), bool(physical_values), "dimensional profile unavailable" if not physical_values else None)
    components["physical_profile_similarity"] = profile
    for key, name, tolerance, weight_name in (("outer_diameter_mm", "diameter_similarity", "diameter_absolute_mm", "diameter_similarity"), ("bore_diameter_mm", "bore_similarity", "bore_absolute_mm", "bore_similarity"), ("face_width_mm", "width_similarity", "width_absolute_mm", "width_similarity")):
        item = _similarity(input_data.normalized_dimensions_mm.get(key), candidate.dimensions_mm.get(key), float(tolerances.get(tolerance, 1.0)))
        components[name] = ScoreComponent(item.score, float(weights.get(weight_name, .10)), item.available, item.reason, item.evidence)
    groove = _similarity(input_data.geometry_descriptor.get("groove_count"), candidate.geometry_descriptor.get("groove_count"), .5)
    components["groove_similarity"] = ScoreComponent(groove.score, float(weights.get("groove_similarity", .05)), groove.available, groove.reason)
    curvature = _similarity(input_data.geometry_descriptor.get("mean_curvature"), candidate.geometry_descriptor.get("mean_curvature"), .01)
    components["curvature_similarity"] = ScoreComponent(curvature.score, float(weights.get("curvature_similarity", .05)), curvature.available, curvature.reason)
    role_score = hard["role"].status == "PASS" if hard["role"].status != "UNKNOWN" else None
    components["role_compatibility"] = ScoreComponent(1.0 if role_score else 0.0 if role_score is False else None, float(weights.get("role_compatibility", .05)), role_score is not None, hard["role"].reason)
    available = [item for item in components.values() if item.available and item.score is not None]
    weight_sum = sum(item.weight for item in available)
    score = _clamp(sum(float(item.score) * item.weight for item in available) / weight_sum) if weight_sum else 0.0
    coverage = _clamp(sum(item.weight for item in available) / max(sum(float(value) for value in weights.values()), 1e-9))
    return score, coverage, components, hard


def retrieve_candidates(input_data: RollerRecognitionInput, revisions: Iterable[InventoryRevisionCandidate], *, config: Any = None) -> tuple[InventoryRevisionCandidate, ...]:
    _, _, _, allow_unknown = _config_values(config)
    eligible = eligible_inventory_revisions(revisions, allow_unknown_unit_shape_matching=allow_unknown)
    identifier = str(input_data.geometry_descriptor.get("design_id") or "").lower()
    alias = str(input_data.geometry_descriptor.get("alias") or "").lower()
    exact = [item for item in eligible if identifier and item.design_id.lower() == identifier or alias and alias in {value.lower() for value in item.aliases}]
    remainder = [item for item in eligible if item not in exact]
    scored = sorted(((score_candidate(input_data, item, config)[0], item.design_id, item.revision_id, item) for item in remainder), key=lambda value: (-value[0], value[1], value[2]))
    pool_size = int(getattr(config, "candidate_pool_size", 20) if config is not None and not isinstance(config, Mapping) else _mapping(config).get("candidate_pool_size", 20))
    return tuple(exact + [item for _, _, _, item in scored[:pool_size]])


def recognize_occurrence(input_data: RollerRecognitionInput, revisions: Iterable[InventoryRevisionCandidate], config: Any = None) -> RecognitionResult:
    _, _, thresholds, _ = _config_values(config)
    if "INVALID_GEOMETRY" in input_data.quality_flags:
        return RecognitionResult(input_data, (), "INVALID_INPUT", True, None)
    if input_data.quality in {"INSUFFICIENT", "UNKNOWN_UNITS"} and not input_data.shape_vector:
        return RecognitionResult(input_data, (), "UNKNOWN_UNITS" if input_data.quality == "UNKNOWN_UNITS" else "INSUFFICIENT_EVIDENCE", True, None)
    candidates = []
    for candidate in retrieve_candidates(input_data, revisions, config=config):
        score, coverage, components, hard = score_candidate(input_data, candidate, config)
        if any(value.status == "FAIL" for value in hard.values()):
            continue
        candidates.append((score, coverage, components, hard, candidate))
    candidates.sort(key=lambda value: (-value[0], -value[1], value[4].design_id, value[4].revision_id))
    # The user-facing result is one candidate per reusable design.  Keep the
    # best eligible revision as evidence and preserve that revision identity.
    best_by_design: dict[str, tuple[float, float, Mapping[str, ScoreComponent], Mapping[str, HardFilterResult], InventoryRevisionCandidate]] = {}
    for item in candidates:
        best_by_design.setdefault(item[4].design_id, item)
    candidates = sorted(best_by_design.values(), key=lambda value: (-value[0], -value[1], value[4].design_id, value[4].revision_id))
    if not candidates:
        return RecognitionResult(input_data, (), "NO_MATCH", True, None)
    margin = candidates[0][0] - candidates[1][0] if len(candidates) > 1 else 1.0
    result_limit = int(getattr(config, "result_limit", 5) if config is not None and not isinstance(config, Mapping) else _mapping(config).get("result_limit", 5))
    output = []
    for rank, (score, coverage, components, hard, candidate) in enumerate(candidates[:result_limit], 1):
        exact_id = input_data.geometry_descriptor.get("design_id", "").lower() == candidate.design_id.lower() if isinstance(input_data.geometry_descriptor.get("design_id", ""), str) else False
        exact_fp = any(name.endswith("_exact") and item.available and item.score == 1.0 for name, item in components.items())
        base_status = "EXACT_IDENTIFIER_MATCH" if exact_id else "EXACT_VERIFIED_FINGERPRINT" if exact_fp else "HIGH_SIMILARITY_CANDIDATE" if score >= float(thresholds.get("high_candidate", .90)) else "MEDIUM_SIMILARITY_CANDIDATE" if score >= float(thresholds.get("medium_candidate", .75)) else "LOW_SIMILARITY_CANDIDATE"
        confidence = _clamp(score * .45 + coverage * .25 + min(margin / max(float(thresholds.get("automatic_abstention_margin", .05)), .05), 1.0) * .15 + input_data.extraction_confidence * .10 + candidate.confidence * .05)
        output.append(RecognitionCandidate(candidate.design_id, candidate.design_name, candidate.revision_id, rank, score, confidence, coverage, base_status, components, hard, {"supporting_evidence": [name for name, value in components.items() if value.available and (value.score or 0) >= .8], "missing_evidence": [name for name, value in components.items() if not value.available], "candidate_only": True}, candidate.verification_status))
    minimum = float(thresholds.get("minimum_candidate", .55))
    coverage_min = float(thresholds.get("minimum_evidence_coverage", .40))
    if output[0].overall_score < minimum or output[0].evidence_coverage < coverage_min:
        status = "UNKNOWN_UNITS" if input_data.quality == "UNKNOWN_UNITS" else "INSUFFICIENT_EVIDENCE" if output[0].evidence_coverage < coverage_min else "NO_MATCH"
        return RecognitionResult(input_data, tuple(output), status, True, margin)
    if len(output) > 1 and margin < float(thresholds.get("automatic_abstention_margin", .05)):
        return RecognitionResult(input_data, tuple(RecognitionCandidate(item.design_id, item.design_name, item.geometry_revision_id, item.rank, item.overall_score, item.confidence, item.evidence_coverage, "AMBIGUOUS", item.components, item.hard_filters, item.explanation, item.inventory_verification_status) for item in output), "AMBIGUOUS", True, margin)
    return RecognitionResult(input_data, tuple(output), output[0].candidate_status, False, margin)


def evaluate_recognition(results: Iterable[RecognitionResult], labels: Mapping[str, str], *, dataset_kind: str = "SYNTHETIC") -> dict[str, Any]:
    rows = list(results)
    labelled = [item for item in rows if item.input.occurrence_id in labels]
    top1 = sum(bool(item.candidates and item.candidates[0].design_id == labels[item.input.occurrence_id]) for item in labelled)
    top3 = sum(any(candidate.design_id == labels[item.input.occurrence_id] for candidate in item.candidates[:3]) for item in labelled)
    reciprocal = sum((1 / (index + 1) for item in labelled for index, candidate in enumerate(item.candidates) if candidate.design_id == labels[item.input.occurrence_id]), 0.0)
    abstained = sum(item.abstained for item in labelled)
    accepted = len(labelled) - abstained
    return {"dataset_kind": dataset_kind, "sample_count": len(labelled), "top_1_accuracy": top1 / len(labelled) if labelled else 0.0, "top_3_recall": top3 / len(labelled) if labelled else 0.0, "mean_reciprocal_rank": reciprocal / len(labelled) if labelled else 0.0, "abstention_rate": abstained / len(labelled) if labelled else 0.0, "coverage": accepted / len(labelled) if labelled else 0.0, "accuracy_non_abstained": sum(item.candidates and item.candidates[0].design_id == labels[item.input.occurrence_id] for item in labelled if not item.abstained) / accepted if accepted else 0.0, "false_high_confidence_count": sum(item.candidates and item.candidates[0].confidence >= .90 and item.candidates[0].design_id != labels[item.input.occurrence_id] for item in labelled), "ambiguous_count": sum(item.status == "AMBIGUOUS" for item in labelled)}


def inventory_snapshot_hash(revisions: Iterable[InventoryRevisionCandidate]) -> str:
    return _hash([asdict(item) for item in sorted(revisions, key=lambda value: value.candidate_key)])


def _copy_inventory_snapshot(source_engine: Any, target_engine: Any) -> None:
    """Copy design/revision snapshots into the project DB for FK-safe results."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from rollform_extractor.database import RollerAlias, RollerDesign, RollerGeometryRevision
    with Session(source_engine) as source, Session(target_engine) as target, target.begin():
        for design in source.scalars(select(RollerDesign).order_by(RollerDesign.design_id)):
            if target.get(RollerDesign, design.design_id) is None:
                target.add(RollerDesign(design_id=design.design_id, name=design.name, design_type=design.design_type, manufacturer=design.manufacturer, status=design.status, verified=design.verified, provenance_json={**(design.provenance_json or {}), "recognition_snapshot": True}))
        target.flush()
        for revision in source.scalars(select(RollerGeometryRevision).order_by(RollerGeometryRevision.revision_id)):
            if target.scalar(select(RollerGeometryRevision).where(RollerGeometryRevision.revision_id == revision.revision_id)) is None:
                target.add(RollerGeometryRevision(revision_id=revision.revision_id, design_id=revision.design_id, asset_id=None, dimensions_json=revision.dimensions_json, unit_status=revision.unit_status, measurement_method=revision.measurement_method, source=revision.source, confidence=revision.confidence, verification_status=revision.verification_status, input_file_hash=revision.input_file_hash, algorithm_version=revision.algorithm_version, configuration_hash=revision.configuration_hash, physical_fingerprint=revision.physical_fingerprint, shape_fingerprint=revision.shape_fingerprint, provenance_json={**(revision.provenance_json or {}), "recognition_snapshot": True}))
        target.flush()
        for alias in source.scalars(select(RollerAlias).order_by(RollerAlias.id)):
            if target.scalar(select(RollerAlias).where(RollerAlias.normalized_alias == alias.normalized_alias)) is None and target.get(RollerDesign, alias.design_id) is not None:
                target.add(RollerAlias(design_id=alias.design_id, alias=alias.alias, normalized_alias=alias.normalized_alias, source=alias.source, verified=alias.verified, provenance_json={**(alias.provenance_json or {}), "recognition_snapshot": True}))


def recognize_project(engine: Any, project_id: int, *, inventory_engine: Any | None = None, units_status: str = "UNKNOWN", configuration_hash: str = "", config: Any = None, run_key: str | None = None) -> tuple[int, tuple[RecognitionResult, ...]]:
    """Recognize every occurrence in one project and persist a reproducible run."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from rollform_extractor.database import (
        RollerAlias, RollerDesign, RollerGeometryRevision, RollerOccurrence,
        RollerRecognitionCandidate as DbCandidate, RollerRecognitionInput as DbInput,
        RollerRecognitionRun, ResultProvenance,
    )
    if inventory_engine is not None and inventory_engine is not engine:
        _copy_inventory_snapshot(inventory_engine, engine)
    with Session(engine) as session:
        rows = session.scalars(select(RollerGeometryRevision).order_by(RollerGeometryRevision.revision_id)).all()
        revisions = []
        for row in rows:
            aliases = session.scalars(select(RollerAlias.alias).where(RollerAlias.design_id == row.design_id, RollerAlias.verified == 1)).all()
            design = session.get(RollerDesign, row.design_id)
            view = inventory_revision_from_row(row, aliases=aliases)
            revisions.append(InventoryRevisionCandidate(view.design_id, getattr(design, "name", None), getattr(design, "design_type", None), view.revision_id, view.dimensions_mm, view.geometry_descriptor, view.shape_vector, view.physical_fingerprint, view.shape_fingerprint, view.unit_status, view.verification_status, view.eligibility, view.confidence, view.aliases, view.role, view.machine, view.superseded, view.source))
        occurrences = session.scalars(select(RollerOccurrence).where(RollerOccurrence.project_id == project_id).order_by(RollerOccurrence.occurrence_id)).all()
        snapshot = inventory_snapshot_hash(revisions)
        key = run_key or _hash({"project_id": project_id, "configuration_hash": configuration_hash, "inventory_snapshot_hash": snapshot, "occurrences": [row.occurrence_id for row in occurrences]})
        existing = session.scalar(select(RollerRecognitionRun).where(RollerRecognitionRun.project_id == project_id, RollerRecognitionRun.run_key == key))
        if existing is not None:
            return existing.id, ()
        run = RollerRecognitionRun(project_id=project_id, run_key=key, algorithm_version=ROLLER_RECOGNITION_ALGORITHM_VERSION, feature_schema_version=ROLLER_RECOGNITION_FEATURE_SCHEMA_VERSION, configuration_hash=configuration_hash, inventory_snapshot_hash=snapshot, status="RUNNING", occurrence_count=len(occurrences), diagnostics_json={})
        session.add(run)
        session.flush()
        results = []
        for occurrence in occurrences:
            prepared = prepare_recognition_input(str(project_id), occurrence, units_status=units_status, configuration_hash=configuration_hash)
            result = recognize_occurrence(prepared, revisions, config=config)
            results.append(result)
            db_input = DbInput(run_id=run.id, occurrence_id=prepared.occurrence_id, station_id=prepared.station_id, role=prepared.role, feature_json=prepared.to_dict(), scalar_vector_json={"field_names": list(ROLLER_SCALAR_FEATURE_FIELDS), "values": [prepared.normalized_dimensions_mm.get(key) for key in ROLLER_SCALAR_FEATURE_FIELDS], "missing_mask": [prepared.normalized_dimensions_mm.get(key) is None for key in ROLLER_SCALAR_FEATURE_FIELDS]}, shape_vector_json={"field_names": list(ROLLER_SHAPE_FEATURE_FIELDS[:len(prepared.shape_vector)]), "values": list(prepared.shape_vector)}, missing_mask_json=list(prepared.missing_mask), quality_json={"quality": prepared.quality, "flags": list(prepared.quality_flags)}, physical_fingerprint=prepared.physical_fingerprint, shape_fingerprint=prepared.shape_fingerprint, source_handles_json=list(prepared.source_handles), input_hash=prepared.input_hash)
            session.add(db_input)
            session.flush()
            for candidate in result.candidates:
                session.add(DbCandidate(run_id=run.id, input_id=db_input.id, design_id=candidate.design_id, geometry_revision_id=candidate.geometry_revision_id, rank=candidate.rank, overall_score=candidate.overall_score, confidence=candidate.confidence, evidence_coverage=candidate.evidence_coverage, candidate_status=candidate.candidate_status, component_scores_json={key: value.to_dict() for key, value in candidate.components.items()}, hard_filter_results_json={key: asdict(value) for key, value in candidate.hard_filters.items()}, explanation_json=candidate.explanation, algorithm_version=ROLLER_RECOGNITION_ALGORITHM_VERSION, configuration_hash=configuration_hash))
            session.add(ResultProvenance(project_id=project_id, result_table="roller_recognition_inputs", result_key=prepared.occurrence_id, field_name=None, source_handles=list(prepared.source_handles), method=ROLLER_RECOGNITION_ALGORITHM_VERSION, configuration_hash=configuration_hash, confidence=prepared.extraction_confidence, warning=";".join(prepared.quality_flags) or None))
        run.status = "COMPLETED"
        run.candidate_count = sum(len(item.candidates) for item in results)
        run.diagnostics_json = {"abstained": sum(item.abstained for item in results), "status_counts": {status: sum(item.status == status for item in results) for status in sorted({item.status for item in results})}}
        session.commit()
        return run.id, tuple(results)


def review_candidate(engine: Any, candidate_id: int, decision: str, reviewer: str, *, selected_design_id: str | None = None, selected_revision_id: str | None = None, reason_code: str | None = None, notes: str | None = None) -> int:
    from sqlalchemy.orm import Session
    from rollform_extractor.database import RollerRecognitionCandidate, RollerRecognitionReview
    allowed = {"ACCEPT_CANDIDATE", "REJECT_CANDIDATE", "SELECT_DIFFERENT_DESIGN", "NO_MATCH_CONFIRMED", "INSUFFICIENT_EVIDENCE", "DEFER"}
    if decision not in allowed:
        raise ValueError(f"unsupported recognition decision: {decision}")
    with Session(engine) as session, session.begin():
        candidate = session.get(RollerRecognitionCandidate, candidate_id)
        if candidate is None:
            raise LookupError("recognition candidate not found")
        review = RollerRecognitionReview(candidate_id=candidate_id, decision=decision, selected_design_id=selected_design_id, selected_revision_id=selected_revision_id, reviewer=reviewer, reason_code=reason_code, notes=notes)
        session.add(review)
        session.flush()
        return review.id


def export_recognition_run(engine: Any, run_id: int, output: Any) -> Any:
    import csv
    from pathlib import Path
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from rollform_extractor.database import RollerRecognitionCandidate, RollerRecognitionInput, RollerRecognitionRun
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        run = session.get(RollerRecognitionRun, run_id)
        if run is None:
            raise LookupError("recognition run not found")
        inputs = session.scalars(select(RollerRecognitionInput).where(RollerRecognitionInput.run_id == run_id).order_by(RollerRecognitionInput.occurrence_id)).all()
        candidates = session.scalars(select(RollerRecognitionCandidate).where(RollerRecognitionCandidate.run_id == run_id).order_by(RollerRecognitionCandidate.input_id, RollerRecognitionCandidate.rank)).all()
        summary = {"run_id": run.id, "project_id": run.project_id, "algorithm_version": run.algorithm_version, "feature_schema_version": run.feature_schema_version, "configuration_hash": run.configuration_hash, "inventory_snapshot_hash": run.inventory_snapshot_hash, "status": run.status, "occurrence_count": run.occurrence_count, "candidate_count": run.candidate_count, "diagnostics": run.diagnostics_json}
        (target / "run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (target / "recognition_inputs.json").write_text(json.dumps([item.feature_json for item in inputs], indent=2, sort_keys=True), encoding="utf-8")
        rows = [{"candidate_id": item.id, "input_id": item.input_id, "design_id": item.design_id, "geometry_revision_id": item.geometry_revision_id, "rank": item.rank, "overall_score": item.overall_score, "confidence": item.confidence, "evidence_coverage": item.evidence_coverage, "candidate_status": item.candidate_status, "components": item.component_scores_json, "hard_filters": item.hard_filter_results_json, "explanation": item.explanation_json} for item in candidates]
        (target / "candidates.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        review_rows = [row for row in rows if row["candidate_status"] in {"HIGH_SIMILARITY_CANDIDATE", "MEDIUM_SIMILARITY_CANDIDATE", "AMBIGUOUS"}]
        abstention_rows = [row for row in rows if row["candidate_status"] in {"NO_MATCH", "INSUFFICIENT_EVIDENCE", "UNKNOWN_UNITS", "INVALID_INPUT"}]
        (target / "review_queue.json").write_text(json.dumps(review_rows, indent=2, sort_keys=True), encoding="utf-8")
        (target / "abstentions.csv").write_text("candidate_id,input_id,design_id,rank,overall_score,candidate_status\n" + "\n".join(f"{row['candidate_id']},{row['input_id']},{row['design_id']},{row['rank']},{row['overall_score']},{row['candidate_status']}" for row in abstention_rows) + "\n", encoding="utf-8")
        with (target / "candidates.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["candidate_id", "input_id", "design_id", "geometry_revision_id", "rank", "overall_score", "confidence", "evidence_coverage", "candidate_status"])
            writer.writeheader()
            writer.writerows([{key: row[key] for key in writer.fieldnames} for row in rows])
        with (target / "review_queue.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["candidate_id", "input_id", "design_id", "geometry_revision_id", "rank", "overall_score", "confidence", "evidence_coverage", "candidate_status"])
            writer.writeheader()
            writer.writerows([{key: row[key] for key in writer.fieldnames} for row in review_rows])
        (target / "evaluation.json").write_text(json.dumps({"status": "NOT_RUN", "dataset_kind": None}, indent=2, sort_keys=True), encoding="utf-8")
        input_by_id = {item.id: item for item in inputs}
        for item in inputs:
            occurrence_dir = target / "occurrences" / item.occurrence_id
            occurrence_dir.mkdir(parents=True, exist_ok=True)
            occurrence_rows = [row for row in rows if row["input_id"] == item.id]
            (occurrence_dir / "input_features.json").write_text(json.dumps(item.feature_json, indent=2, sort_keys=True), encoding="utf-8")
            (occurrence_dir / "ranked_candidates.json").write_text(json.dumps(occurrence_rows, indent=2, sort_keys=True), encoding="utf-8")
            (occurrence_dir / "comparison_data.json").write_text(json.dumps({"occurrence_id": item.occurrence_id, "candidates": occurrence_rows}, indent=2, sort_keys=True), encoding="utf-8")
            with (occurrence_dir / "score_breakdown.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["candidate_id", "design_id", "rank", "component", "score", "weight", "available", "reason"])
                for row in occurrence_rows:
                    for name, component in row["components"].items():
                        writer.writerow([row["candidate_id"], row["design_id"], row["rank"], name, component.get("score"), component.get("weight"), component.get("available"), component.get("reason")])
    return target
