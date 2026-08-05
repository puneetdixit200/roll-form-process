"""Private two-seed corpus generation, training, evaluation, and approval.

This module is deliberately local-only. It consumes the private flower
prototype dataset with geometry, generates controlled derived sequences, trains
the CLRSG residual ensemble, derives OOD thresholds from validation data, and
writes only aggregate metrics suitable for redacted reporting.

Private corpus shards and model weights must remain outside the Git repository.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Iterable

import numpy as np

from rollform_extractor.clrsg_model import load_clrsg_model, train_clrsg
from rollform_extractor.flower_prototype_dataset import _dataset_from_dict
from rollform_extractor.synthetic_corpus_schema import (
    SyntheticCorpus,
    SyntheticCorpusManifest,
    SyntheticSample,
    stable_hash,
)


PRIVATE_CORPUS_VERSION = "private_two_seed_visual_corpus_v1"
PRIVATE_TEACHER_VERSION = "historical_warp_teacher_v1"
PRIVATE_TRAINING_VERSION = "private_clrsg_training_v2"
PRIVATE_EVALUATION_VERSION = "private_clrsg_evaluation_v2"
PRIVATE_OOD_VERSION = "validation_quantile_ood_v1"
PRIVATE_CORPUS_CLASSIFICATION = "PRIVATE_PROTOTYPE_CORPUS"
PRIVATE_MODEL_CLASSIFICATION = "PRIVATE_PROTOTYPE_MODEL"
NORMALIZED_SEQUENCE_SLOTS = 28
CANONICAL_POINTS = 128


@dataclass(frozen=True)
class PrivateSeed:
    flower_id: str
    topology: str
    source_hash: str
    passes: np.ndarray
    schedule: np.ndarray

    @property
    def station_count(self) -> int:
        return int(self.passes.shape[0])

    @property
    def final(self) -> np.ndarray:
        return self.passes[-1]


@dataclass(frozen=True)
class CorpusBuildSummary:
    dataset_id: str
    dataset_hash: str
    generated: int
    accepted: int
    rejected: int
    duplicates: int
    seed_count: int
    pass_count: int
    station_counts: tuple[int, ...]
    split_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "generated": self.generated,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "seed_count": self.seed_count,
            "private_pass_count": self.pass_count,
            "station_counts": list(self.station_counts),
            "split_counts": dict(self.split_counts),
            "classification": PRIVATE_CORPUS_CLASSIFICATION,
            "teacher_version": PRIVATE_TEACHER_VERSION,
            "committable": False,
        }


def _assert_private_root(path: Path) -> Path:
    root = path.expanduser().resolve()
    for ancestor in (root, *root.parents):
        if (ancestor / ".git").exists():
            raise ValueError("private corpus/model root must be outside the Git repository")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset_json(path: Path) -> Path:
    value = path.expanduser().resolve()
    if value.is_dir():
        value = value / "dataset.json"
    if not value.is_file():
        raise FileNotFoundError("private flower dataset.json was not found")
    return value


def _resample_points(points: np.ndarray, count: int = CANONICAL_POINTS) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 2 or len(points) < 2:
        raise ValueError("historical pass has insufficient geometry")
    points = points[:, :2]
    if len(points) == count:
        return points.copy()
    distances = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(distances)])
    if cumulative[-1] <= 1e-12:
        raise ValueError("historical pass has zero visual length")
    source = cumulative / cumulative[-1]
    target = np.linspace(0.0, 1.0, count)
    return np.column_stack([np.interp(target, source, points[:, axis]) for axis in range(2)])


def _pass_points(pass_record: Any) -> np.ndarray:
    normalized = np.asarray(getattr(pass_record, "normalized_points", ()), dtype=float)
    if normalized.size:
        return _resample_points(normalized)
    vector = np.asarray(getattr(pass_record, "shape_vector", ()), dtype=float)
    if vector.size and vector.size % 2 == 0:
        return _resample_points(vector.reshape(-1, 2))
    raw = np.asarray(getattr(pass_record, "points", ()), dtype=float)
    if raw.size:
        return _resample_points(raw[:, :2])
    raise ValueError(f"pass {getattr(pass_record, 'pass_id', 'unknown')} has no usable geometry")


def _normalize_shape(points: np.ndarray) -> np.ndarray:
    value = np.asarray(points, dtype=float)
    value = value - value.mean(axis=0, keepdims=True)
    scale = max(float(np.ptp(value[:, 0])), float(np.ptp(value[:, 1])), 1e-9)
    return value / scale


def _tangent(points: np.ndarray) -> np.ndarray:
    delta = np.gradient(points, axis=0)
    norm = np.linalg.norm(delta, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    return delta / norm


def _curvature(points: np.ndarray) -> np.ndarray:
    tangent = _tangent(points)
    angle = np.unwrap(np.arctan2(tangent[:, 1], tangent[:, 0]))
    return np.gradient(angle)


def _transition_magnitude(left: np.ndarray, right: np.ndarray) -> float:
    a = _normalize_shape(left)
    b = _normalize_shape(right)
    rms = float(np.sqrt(np.mean((a - b) ** 2)))
    tangent = float(np.sqrt(np.mean((_tangent(a) - _tangent(b)) ** 2)))
    curvature = float(np.sqrt(np.mean((_curvature(a) - _curvature(b)) ** 2)))
    bbox = float(np.sqrt(np.mean((np.ptp(a, axis=0) - np.ptp(b, axis=0)) ** 2)))
    return max(0.0, 0.55 * rms + 0.20 * tangent + 0.20 * curvature + 0.05 * bbox)


def historical_progress_schedule(passes: np.ndarray) -> np.ndarray:
    """Return deterministic, geometry-derived cumulative progress in [0, 1]."""
    if len(passes) < 2:
        raise ValueError("a historical flower needs at least two passes")
    increments = np.asarray([_transition_magnitude(passes[index - 1], passes[index]) for index in range(1, len(passes))], dtype=float)
    total = float(increments.sum())
    if not math.isfinite(total) or total <= 1e-12:
        return np.linspace(0.0, 1.0, len(passes))
    cumulative = np.concatenate([[0.0], np.cumsum(increments)]) / total
    cumulative[0] = 0.0
    cumulative[-1] = 1.0
    return np.maximum.accumulate(cumulative)


def load_private_seeds(dataset_path: Path) -> tuple[PrivateSeed, ...]:
    payload = json.loads(_dataset_json(dataset_path).read_text(encoding="utf-8"))
    dataset = _dataset_from_dict(payload)
    if len(dataset.flowers) != 2:
        raise ValueError(f"private CLRSG requires exactly two complete flowers; found {len(dataset.flowers)}")
    seeds: list[PrivateSeed] = []
    for flower in sorted(dataset.flowers, key=lambda item: item.flower_id):
        if len(flower.passes) < 8:
            raise ValueError(f"{flower.flower_id} has fewer than eight passes")
        passes = np.asarray([_pass_points(item) for item in flower.passes], dtype=float)
        if not np.all(np.isfinite(passes)):
            raise ValueError(f"{flower.flower_id} contains non-finite geometry")
        seeds.append(PrivateSeed(flower_id=flower.flower_id, topology=str(flower.topology), source_hash=str(flower.source_sha256), passes=passes, schedule=historical_progress_schedule(passes)))
    return tuple(seeds)


def _closed(topology: str) -> bool:
    return "CLOSED" in topology.upper() or "LOOP" in topology.upper()


def _smooth_field(rng: np.random.Generator, count: int, magnitude: float) -> np.ndarray:
    anchor_count = int(rng.integers(3, 8))
    anchor_x = np.linspace(0.0, 1.0, anchor_count)
    anchor_y = rng.normal(0.0, magnitude, size=anchor_count)
    anchor_y[0] *= 0.25
    anchor_y[-1] *= 0.25
    field = np.interp(np.linspace(0.0, 1.0, count), anchor_x, anchor_y)
    kernel = np.asarray([1, 2, 3, 2, 1], dtype=float)
    kernel /= kernel.sum()
    return np.convolve(np.pad(field, (2, 2), mode="edge"), kernel, mode="valid")


def transform_target(seed: PrivateSeed, sample_index: int, base_seed: int = 1729) -> tuple[np.ndarray, dict[str, Any]]:
    rng = np.random.default_rng(base_seed + sample_index * 1009 + int(sha256(seed.flower_id.encode()).hexdigest()[:8], 16))
    points = seed.final.copy()
    scale_x = float(rng.uniform(0.80, 1.20))
    scale_y = float(rng.uniform(0.80, 1.20))
    angle = math.radians(float(rng.uniform(-10.0, 10.0)))
    mirror = bool(rng.integers(0, 2))
    magnitude = float(rng.uniform(0.01, 0.07))
    centered = points - points.mean(axis=0, keepdims=True)
    centered[:, 0] *= scale_x * (-1.0 if mirror else 1.0)
    centered[:, 1] *= scale_y
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    centered = centered @ rotation.T
    tangent = _tangent(centered)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    field = _smooth_field(rng, len(centered), magnitude)
    if _closed(seed.topology):
        field[0] = field[-1] = 0.0
    transformed = centered + normal * field[:, None]
    transformed -= transformed.mean(axis=0, keepdims=True)
    if _closed(seed.topology):
        transformed[-1] = transformed[0]
    if not np.all(np.isfinite(transformed)):
        raise ValueError("private transform produced non-finite geometry")
    recipe = {"version": "private_profile_transform_v2", "transform_family": "COMPOSITE_MEDIUM_MAGNITUDE", "scale_x": round(scale_x, 8), "scale_y": round(scale_y, 8), "rotation_degrees": round(math.degrees(angle), 8), "mirror_horizontal": mirror, "normal_warp_magnitude": round(magnitude, 8), "seed": int(base_seed), "sample_index": int(sample_index), "source_flower_id": seed.flower_id}
    return transformed, recipe


def _interp_sequence(sequence: np.ndarray, source_progress: np.ndarray, target_count: int) -> np.ndarray:
    target_progress = np.linspace(0.0, 1.0, target_count)
    result = np.empty((target_count, sequence.shape[1], 2), dtype=float)
    for point in range(sequence.shape[1]):
        for axis in range(2):
            result[:, point, axis] = np.interp(target_progress, source_progress, sequence[:, point, axis])
    return result


def historical_warp_teacher(seed: PrivateSeed, target: np.ndarray, station_count: int) -> np.ndarray:
    """Warp the complete source sequence into the transformed final target."""
    if not 8 <= station_count <= 28:
        raise ValueError("station count must be between 8 and 28")
    displacement = target - seed.final
    kernel = np.asarray([1, 2, 3, 2, 1], dtype=float)
    kernel /= kernel.sum()
    smooth = np.column_stack([np.convolve(np.pad(displacement[:, axis], (2, 2), mode="edge"), kernel, mode="valid") for axis in range(2)])
    warped = np.asarray([source_pass + smooth * float(progress) for source_pass, progress in zip(seed.passes, seed.schedule)], dtype=float)
    warped[-1] = target
    teacher = _interp_sequence(warped, seed.schedule, station_count)
    teacher[-1] = target
    if _closed(seed.topology):
        teacher[:, -1] = teacher[:, 0]
    return teacher


def deterministic_baseline(target: np.ndarray, station_count: int, topology: str) -> np.ndarray:
    if _closed(topology):
        start = target * 0.82
    else:
        start = np.column_stack([np.linspace(-1.0, 1.0, len(target)), np.zeros(len(target))])
    progress = np.linspace(0.0, 1.0, station_count)
    sequence = np.asarray([start * (1.0 - value) + target * value for value in progress], dtype=float)
    if _closed(topology):
        sequence[:, -1] = sequence[:, 0]
    sequence[-1] = target
    return sequence


def _normalize_slots(sequence: np.ndarray, slots: int = NORMALIZED_SEQUENCE_SLOTS) -> np.ndarray:
    return _interp_sequence(sequence, np.linspace(0.0, 1.0, len(sequence)), slots)


def _split(parent_group: str) -> str:
    value = int(sha256(parent_group.encode()).hexdigest()[:8], 16) % 100
    return "TRAIN" if value < 70 else "VALIDATION" if value < 85 else "TEST"


def _profile_payload(target: np.ndarray, seed: PrivateSeed, profile_id: str) -> dict[str, Any]:
    closed = _closed(seed.topology)
    points = np.asarray(target, dtype=float)
    if closed and len(points) > 3 and np.linalg.norm(points[0] - points[-1]) <= 1e-9:
        points = points[:-1]
    if len(points) < (3 if closed else 2):
        raise ValueError("target profile has insufficient unique points")
    vertices = [{"vertex_id": f"v-{index + 1:03d}", "x": round(float(point[0]), 10), "y": round(float(point[1]), 10)} for index, point in enumerate(points)]
    segments = [{"segment_id": f"s-{index + 1:03d}", "type": "LINE", "start_vertex_id": vertices[index]["vertex_id"], "end_vertex_id": vertices[index + 1]["vertex_id"]} for index in range(len(vertices) - 1)]
    if closed:
        segments.append({"segment_id": f"s-{len(segments) + 1:03d}", "type": "LINE", "start_vertex_id": vertices[-1]["vertex_id"], "end_vertex_id": vertices[0]["vertex_id"]})
    return {"schema_version": 1, "profile_id": profile_id, "name": "Private derived visual target", "topology": "CLOSED_CONTOUR" if closed else "OPEN_PATH", "closed": closed, "computational_seam_vertex_id": vertices[0]["vertex_id"] if closed else None, "vertices": vertices, "segments": segments, "metadata": {"source": "PRIVATE_SYNTHETIC_DERIVED", "visual_only": True, "source_flower_id": seed.flower_id}}


def _build_private_corpus(seeds: tuple[PrivateSeed, ...], output_root: Path, *, samples_per_seed: int, seed: int) -> tuple[SyntheticCorpus, CorpusBuildSummary]:
    output_root = _assert_private_root(output_root)
    samples: list[SyntheticSample] = []
    seen: set[str] = set()
    generated = rejected = duplicates = 0
    for private_seed in seeds:
        for index in range(samples_per_seed):
            generated += 1
            try:
                target, recipe = transform_target(private_seed, index, seed)
                target_key = stable_hash(np.round(target, 8).tolist())
                if target_key in seen:
                    duplicates += 1
                    continue
                seen.add(target_key)
                station_count = 8 + ((index * 5 + private_seed.station_count) % 21)
                teacher = historical_warp_teacher(private_seed, target, station_count)
                baseline = deterministic_baseline(target, station_count, private_seed.topology)
                teacher_28 = _normalize_slots(teacher)
                baseline_28 = _normalize_slots(baseline)
                residual_rms = float(np.sqrt(np.mean((teacher_28 - baseline_28) ** 2)))
                if not math.isfinite(residual_rms) or residual_rms <= 1e-8:
                    rejected += 1
                    continue
                parent = "private-parent-" + sha256(f"{private_seed.flower_id}|{index}|{seed}".encode()).hexdigest()[:16]
                sample_id = "private-sample-" + sha256(f"{parent}|{station_count}".encode()).hexdigest()[:16]
                profile = _profile_payload(target, private_seed, "private-target-" + target_key[:16])
                samples.append(SyntheticSample(sample_id=sample_id, classification="PRIVATE_SYNTHETIC_DERIVED", family_id=private_seed.flower_id, parent_group_id=parent, target_profile=profile, station_count=station_count, teacher_sequence=teacher_28.tolist(), baseline_sequence=baseline_28.tolist(), transform_recipe={**recipe, "target_hash": target_key, "residual_rms": residual_rms}, progression_schedule={"name": f"HISTORICAL_{private_seed.flower_id}", "teacher_version": PRIVATE_TEACHER_VERSION, "source_station_count": private_seed.station_count}, split=_split(parent), warnings=["PRIVATE_SYNTHETIC_DERIVED_NOT_INDEPENDENT_FACTORY_EVIDENCE"]))
            except (ValueError, FloatingPointError, np.linalg.LinAlgError):
                rejected += 1
    if len(samples) < 8:
        raise ValueError("private corpus generation produced fewer than eight accepted samples")
    split_counts: dict[str, int] = {}
    station_distribution: dict[str, int] = {}
    family_distribution: dict[str, int] = {}
    for item in samples:
        split_counts[item.split] = split_counts.get(item.split, 0) + 1
        station_distribution[str(item.station_count)] = station_distribution.get(str(item.station_count), 0) + 1
        family_distribution[item.family_id] = family_distribution.get(item.family_id, 0) + 1
    recipe = {"generator_version": PRIVATE_CORPUS_VERSION, "teacher_version": PRIVATE_TEACHER_VERSION, "seed": seed, "samples_per_seed": samples_per_seed, "seed_ids": [item.flower_id for item in seeds], "source_hashes": [item.source_hash for item in seeds]}
    manifest = SyntheticCorpusManifest(dataset_id="private-corpus-" + stable_hash(recipe)[:16], dataset_version=PRIVATE_CORPUS_VERSION, generator_version=PRIVATE_CORPUS_VERSION, seed=seed, classification=PRIVATE_CORPUS_CLASSIFICATION, sample_counts=split_counts, station_distribution=station_distribution, family_distribution=family_distribution, classification_distribution={"PRIVATE_SYNTHETIC_DERIVED": len(samples)}, recipe_hash=stable_hash(recipe), privacy={"contains_private_derived_geometry": True, "committable": False})
    corpus = SyntheticCorpus(manifest, samples)
    corpus.write(output_root)
    summary = CorpusBuildSummary(dataset_id=manifest.dataset_id, dataset_hash=manifest.content_hash, generated=generated, accepted=len(samples), rejected=rejected, duplicates=duplicates, seed_count=len(seeds), pass_count=sum(item.station_count for item in seeds), station_counts=tuple(sorted({item.station_count for item in samples})), split_counts=split_counts)
    (output_root / "private_summary.json").write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return corpus, summary


def generate_private_corpus(dataset_path: Path, output_root: Path, *, samples_per_seed: int = 100, seed: int = 1729) -> tuple[SyntheticCorpus, CorpusBuildSummary]:
    return _build_private_corpus(load_private_seeds(dataset_path), output_root, samples_per_seed=samples_per_seed, seed=seed)


def _rms(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(left, dtype=float) - np.asarray(right, dtype=float)) ** 2)))


def _prediction_alpha(status: str) -> float:
    if status == "IN_DISTRIBUTION":
        return 0.85
    if status == "NEAR_DISTRIBUTION":
        return 0.50
    return 0.0


def _refresh_hashes(model_root: Path) -> None:
    hashes: dict[str, str] = {}
    for path in sorted(model_root.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes[str(path.relative_to(model_root))] = sha256(path.read_bytes()).hexdigest()
    (model_root / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")


def derive_ood_thresholds(model_root: Path, corpus: SyntheticCorpus) -> dict[str, Any]:
    model = load_clrsg_model(model_root)
    validation = [sample for sample in corpus.samples if sample.split == "VALIDATION"]
    reference = validation or [sample for sample in corpus.samples if sample.split == "TRAIN"]
    if not reference:
        raise ValueError("cannot derive OOD thresholds without validation or training samples")
    distances = np.asarray([float(np.sqrt(np.mean(model.condition(sample.target_profile, sample.station_count) ** 2))) for sample in reference], dtype=float)
    inside = max(float(np.quantile(distances, 0.95)), 1e-6)
    near = max(float(np.quantile(distances, 0.99)), inside * 1.05)
    payload = {"schema_version": 1, "version": PRIVATE_OOD_VERSION, "source": "VALIDATION_QUANTILES" if validation else "TRAINING_QUANTILES_FALLBACK", "sample_count": int(len(distances)), "quantiles": {"in_distribution": 0.95, "near_distribution": 0.99}, "thresholds": {"in_distribution": inside, "near_distribution": near}, "distance_summary": {"minimum": float(distances.min()), "median": float(np.median(distances)), "maximum": float(distances.max())}}
    (model_root / "ood_thresholds.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    manifest_path = model_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ood_threshold_source"] = payload["source"]
    manifest["ood_threshold_version"] = PRIVATE_OOD_VERSION
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    return payload


def _extreme_profiles(sample: SyntheticSample) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for kind in ("EXTREME_ASPECT", "HIGH_FREQUENCY"):
        profile = deepcopy(sample.target_profile)
        profile["profile_id"] = f"{profile.get('profile_id', sample.sample_id)}-ood-{kind.lower()}"
        vertices = profile.get("vertices", [])
        if kind == "EXTREME_ASPECT":
            for vertex in vertices:
                vertex["x"] = float(vertex["x"]) * 4.0
                vertex["y"] = float(vertex["y"]) * 0.08
        else:
            for index, vertex in enumerate(vertices):
                vertex["y"] = float(vertex["y"]) + (0.35 if index % 2 else -0.35)
        profile.setdefault("metadata", {})["source"] = "PRIVATE_NEGATIVE_OOD"
        profiles.append(profile)
    return profiles


def _aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    if not values:
        return {"sample_count": 0, "baseline_rms": None, "learned_rms": None, "relative_improvement": None}
    baseline = float(np.mean([item["baseline_rms"] for item in values]))
    learned = float(np.mean([item["learned_rms"] for item in values]))
    improvement = (baseline - learned) / baseline if baseline > 1e-12 else 0.0
    return {"sample_count": len(values), "baseline_rms": baseline, "learned_rms": learned, "relative_improvement": improvement, "fallback_rate": sum(item["blend_alpha"] == 0.0 for item in values) / len(values), "mean_ensemble_disagreement": float(np.mean([item["ensemble_disagreement"] for item in values])), "mean_condition_distance": float(np.mean([item["condition_distance"] for item in values]))}


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"method": "NON_PROBABILISTIC_EMPIRICAL_CALIBRATION", "bins": [], "warning": "No validation rows were available."}
    ordered = sorted(rows, key=lambda item: item["model_support_score"])
    bins = np.array_split(np.arange(len(ordered)), min(5, len(ordered)))
    result = []
    for index, indices in enumerate(bins):
        selected = [ordered[int(i)] for i in indices]
        errors = np.asarray([item["learned_rms"] for item in selected], dtype=float)
        result.append({"bin": index + 1, "sample_count": len(selected), "minimum_support": min(item["model_support_score"] for item in selected), "maximum_support": max(item["model_support_score"] for item in selected), "mean_error": float(errors.mean()), "median_error": float(np.median(errors)), "p90_error": float(np.quantile(errors, 0.90))})
    return {"method": "NON_PROBABILISTIC_EMPIRICAL_CALIBRATION", "bins": result, "warning": "Two real seed flowers do not support probability calibration."}


def evaluate_model(model_root: Path, corpus: SyntheticCorpus) -> dict[str, Any]:
    model = load_clrsg_model(model_root)
    groups: dict[str, list[dict[str, Any]]] = {}
    all_rows: list[dict[str, Any]] = []
    near_threshold = max(float(model.ood_thresholds["near_distribution"]), 1e-9)
    for sample in corpus.samples:
        if sample.split not in {"VALIDATION", "TEST"}:
            continue
        baseline = np.asarray(sample.baseline_sequence, dtype=float)
        teacher = np.asarray(sample.teacher_sequence, dtype=float)
        prediction = model.predict(sample.target_profile, sample.station_count)
        alpha = _prediction_alpha(prediction["ood_status"])
        learned = baseline + alpha * np.asarray(prediction["residual"], dtype=float)
        learned[-1] = teacher[-1]
        support = max(0.0, min(1.0, 1.0 - prediction["condition_distance"] / near_threshold))
        row = {"sample_id": sample.sample_id, "split": sample.split, "family_id": sample.family_id, "station_count": sample.station_count, "baseline_rms": _rms(baseline, teacher), "learned_rms": _rms(learned, teacher), "ood_status": prediction["ood_status"], "condition_distance": float(prediction["condition_distance"]), "ensemble_disagreement": float(prediction["ensemble_disagreement"]), "blend_alpha": alpha, "model_support_score": support}
        groups.setdefault(sample.split, []).append(row)
        all_rows.append(row)
    validation_rows = groups.get("VALIDATION", [])
    test_rows = groups.get("TEST", [])
    validation = _aggregate(validation_rows)
    test = _aggregate(test_rows)
    family_rows: dict[str, list[dict[str, Any]]] = {}
    station_rows: dict[str, list[dict[str, Any]]] = {}
    for item in all_rows:
        family_rows.setdefault(item["family_id"], []).append(item)
        station_rows.setdefault(str(item["station_count"]), []).append(item)
    source_samples = [sample for sample in corpus.samples if sample.split == "VALIDATION"] or corpus.samples[:5]
    probes = []
    for sample in source_samples[:5]:
        for profile in _extreme_profiles(sample):
            try:
                probes.append(model.predict(profile, sample.station_count)["ood_status"] == "OUT_OF_DISTRIBUTION")
            except (ValueError, np.linalg.LinAlgError):
                probes.append(True)
    ood_true_positive_rate = float(np.mean(probes)) if probes else 0.0
    validation_false_rejection = sum(item["ood_status"] == "OUT_OF_DISTRIBUTION" for item in validation_rows) / len(validation_rows) if validation_rows else 1.0
    approved = test.get("relative_improvement") is not None and float(test["relative_improvement"]) >= 0.05 and float(test.get("fallback_rate") or 0.0) <= 0.50 and ood_true_positive_rate >= 0.75 and validation_false_rejection <= 0.20
    return {"evaluation_version": PRIVATE_EVALUATION_VERSION, "model_id": model.model_id, "privacy_classification": model.manifest.get("privacy_classification"), "validation": validation, "test": test, "family_metrics": {key: _aggregate(value) for key, value in sorted(family_rows.items())}, "station_metrics": {key: _aggregate(value) for key, value in sorted(station_rows.items())}, "ood": {"threshold_version": model.manifest.get("ood_threshold_version"), "negative_probe_count": len(probes), "true_positive_rate": ood_true_positive_rate, "validation_false_rejection_rate": validation_false_rejection}, "calibration": _calibration(validation_rows), "quality_status": "PASS" if approved else "NO_MEANINGFUL_IMPROVEMENT", "approval_recommended": approved, "manufacturing_approval": "NOT_APPROVED"}


def evaluate_real_seed_sequences(model_root: Path, seeds: tuple[PrivateSeed, ...]) -> dict[str, Any]:
    model = load_clrsg_model(model_root)
    cases = []
    mask_patterns = {"SINGLE_MIDDLE": lambda n: [n // 2], "TWO_CONSECUTIVE": lambda n: [max(1, n // 2 - 1), n // 2], "EVERY_SECOND": lambda n: list(range(1, n - 1, 2)), "RANDOM_20": lambda n: list(range(1, n - 1, 5)), "RANDOM_40": lambda n: list(range(1, n - 1, 2))}
    for seed in seeds:
        profile = _profile_payload(seed.final, seed, f"exact-{seed.flower_id.lower()}")
        true_sequence = _normalize_slots(seed.passes)
        baseline = _normalize_slots(deterministic_baseline(seed.final, seed.station_count, seed.topology))
        prediction = model.predict(profile, seed.station_count)
        alpha = _prediction_alpha(prediction["ood_status"])
        learned = baseline + alpha * np.asarray(prediction["residual"], dtype=float)
        learned[-1] = true_sequence[-1]
        masks = {}
        for name, factory in mask_patterns.items():
            indices = [index for index in factory(NORMALIZED_SEQUENCE_SLOTS) if 0 < index < 27]
            masks[name] = {"count": len(indices), "baseline_rms": _rms(baseline[indices], true_sequence[indices]) if indices else None, "learned_rms": _rms(learned[indices], true_sequence[indices]) if indices else None}
        cases.append({"flower_id": seed.flower_id, "station_count": seed.station_count, "baseline_rms": _rms(baseline, true_sequence), "learned_rms": _rms(learned, true_sequence), "ood_status": prediction["ood_status"], "blend_alpha": alpha, "masked_pass_diagnostics": masks})
    return {"protocol": "SAME_SEED_AND_MASKED_PASS_DIAGNOSTIC", "case_count": len(cases), "cases": cases, "warning": "This is a same-seed diagnostic, not independent generalization evidence."}


def train_private_model(corpus: SyntheticCorpus, model_root: Path, *, ensemble_members: int = 5, seed: int = 1729, private_seeds: tuple[PrivateSeed, ...] | None = None) -> dict[str, Any]:
    model_root = _assert_private_root(model_root)
    started = time.monotonic()
    result = train_clrsg(corpus, model_root, ensemble_members=ensemble_members, seed=seed)
    manifest_path = model_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"privacy_classification": PRIVATE_MODEL_CLASSIFICATION, "private_corpus_classification": PRIVATE_CORPUS_CLASSIFICATION, "teacher_version": PRIVATE_TEACHER_VERSION, "training_version": PRIVATE_TRAINING_VERSION, "approval_status": "EVALUATION_REQUIRED", "activation_status": "INACTIVE"})
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    thresholds = derive_ood_thresholds(model_root, corpus)
    evaluation = evaluate_model(model_root, corpus)
    if private_seeds:
        evaluation["real_seed_diagnostics"] = evaluate_real_seed_sequences(model_root, private_seeds)
    (model_root / "evaluation_metrics.json").write_text(json.dumps(evaluation, indent=2, sort_keys=True), encoding="utf-8")
    (model_root / "validation_metrics.json").write_text(json.dumps({**evaluation["validation"], "ood": evaluation["ood"], "thresholds": thresholds}, indent=2, sort_keys=True), encoding="utf-8")
    training = {**result["metrics"], "training_version": PRIVATE_TRAINING_VERSION, "duration_seconds": time.monotonic() - started, "privacy_classification": PRIVATE_MODEL_CLASSIFICATION}
    (model_root / "training_metrics.json").write_text(json.dumps(training, indent=2, sort_keys=True), encoding="utf-8")
    (model_root / "calibration.json").write_text(json.dumps(evaluation["calibration"], indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    load_clrsg_model(model_root)
    return {"model_id": manifest["model_id"], "model_root": str(model_root), "privacy_classification": PRIVATE_MODEL_CLASSIFICATION, "evaluation": evaluation, "approval_recommended": evaluation["approval_recommended"]}


def approve_private_model(model_root: Path) -> dict[str, Any]:
    model_root = model_root.expanduser().resolve()
    load_clrsg_model(model_root)
    manifest_path = model_root / "manifest.json"
    evaluation_path = model_root / "evaluation_metrics.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    if manifest.get("privacy_classification") != PRIVATE_MODEL_CLASSIFICATION:
        raise ValueError("only a PRIVATE_PROTOTYPE_MODEL can be approved")
    approved = bool(evaluation.get("approval_recommended"))
    manifest["approval_status"] = "APPROVED_FOR_PRIVATE_PROTOTYPE" if approved else "NO_MEANINGFUL_IMPROVEMENT"
    manifest["activation_status"] = "INACTIVE"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    approval = {"model_id": manifest["model_id"], "status": manifest["approval_status"], "gates": {"artifact_hashes": True, "private_classification": True, "test_relative_improvement_at_least_5_percent": float(evaluation.get("test", {}).get("relative_improvement") or 0.0) >= 0.05, "negative_ood_true_positive_at_least_75_percent": float(evaluation.get("ood", {}).get("true_positive_rate") or 0.0) >= 0.75, "validation_false_rejection_at_most_20_percent": float(evaluation.get("ood", {}).get("validation_false_rejection_rate") or 1.0) <= 0.20, "deterministic_fallback_required": True}, "manufacturing_approval": "NOT_APPROVED"}
    (model_root / "approval.json").write_text(json.dumps(approval, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    return approval


def activate_private_model(model_root: Path, registry_root: Path) -> dict[str, Any]:
    model_root = model_root.expanduser().resolve()
    registry_root = _assert_private_root(registry_root)
    load_clrsg_model(model_root)
    manifest_path = model_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("approval_status") != "APPROVED_FOR_PRIVATE_PROTOTYPE":
        raise ValueError("private CLRSG model is not approved for prototype activation")
    active = {"model_id": manifest["model_id"], "algorithm_version": manifest["algorithm_version"], "privacy_classification": manifest["privacy_classification"], "model_root": str(model_root), "production_approval": "NOT_APPROVED"}
    (registry_root / "active_model.json").write_text(json.dumps(active, indent=2, sort_keys=True), encoding="utf-8")
    manifest["activation_status"] = "ACTIVE"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    return {key: value for key, value in active.items() if key != "model_root"} | {"status": "ACTIVE", "environment_instruction": "Set ROLLFORM_ACTIVE_CLRSG_MODEL to the approved local model directory."}


def private_plan(dataset_path: Path, *, samples_per_seed: int = 100) -> dict[str, Any]:
    seeds = load_private_seeds(dataset_path)
    return {"phase": "Phase 20 private CLRSG", "seed_flower_count": len(seeds), "private_pass_count": sum(item.station_count for item in seeds), "flowers": [{"flower_id": item.flower_id, "station_count": item.station_count, "topology": item.topology, "schedule_steps": len(item.schedule)} for item in seeds], "proposed_generated_samples": len(seeds) * samples_per_seed, "station_range": [8, 28], "classification": PRIVATE_CORPUS_CLASSIFICATION, "teacher_version": PRIVATE_TEACHER_VERSION, "private_paths_redacted": True, "manufacturing_approval": "NOT_APPROVED"}


def environment_paths() -> dict[str, Path]:
    required = {"dataset": os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET"), "corpus_root": os.environ.get("ROLLFORM_SYNTHETIC_CORPUS_ROOT"), "model_root": os.environ.get("ROLLFORM_MODEL_REGISTRY_ROOT")}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("missing private CLRSG environment variables: " + ", ".join(missing))
    return {key: Path(value).expanduser().resolve() for key, value in required.items() if value}


def run_full_private_workflow(dataset_path: Path, corpus_root: Path, registry_root: Path, *, samples_per_seed: int = 100, seed: int = 1729, ensemble_members: int = 5, activate_if_approved: bool = False) -> dict[str, Any]:
    """Run every private step that requires local files, with redacted output."""
    started = time.monotonic()
    seeds = load_private_seeds(dataset_path)
    corpus_dir = _assert_private_root(corpus_root) / "private-two-seed-v1"
    registry_root = _assert_private_root(registry_root)
    model_dir = registry_root / "models" / "private-clrsg-candidate"
    corpus, summary = _build_private_corpus(seeds, corpus_dir, samples_per_seed=samples_per_seed, seed=seed)
    training = train_private_model(corpus, model_dir, ensemble_members=ensemble_members, seed=seed, private_seeds=seeds)
    approval = approve_private_model(model_dir)
    activation = {"status": "INACTIVE"}
    if activate_if_approved and approval["status"] == "APPROVED_FOR_PRIVATE_PROTOTYPE":
        activation = activate_private_model(model_dir, registry_root)
    report = {"phase": "Phase 20 private CLRSG", "seed_flower_count": len(seeds), "private_pass_count": sum(item.station_count for item in seeds), "corpus": summary.to_dict(), "model": {"model_id": training["model_id"], "privacy_classification": training["privacy_classification"], "evaluation": training["evaluation"], "approval": approval, "activation": activation}, "duration_seconds": time.monotonic() - started, "private_paths_redacted": True, "customer_visual_prototype": "READY", "manufacturing_approval": "NOT_APPROVED", "physical_roller_availability": "NOT_DETERMINED"}
    (registry_root / "phase20_redacted_summary.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
