"""Private two-seed corpus generation, training, evaluation, and approval.

The module is deliberately local-only. It consumes the redacted private flower
prototype dataset with geometry, generates controlled derived sequences, trains
an existing CLRSG-compatible residual ensemble, and writes only aggregate
metrics suitable for redacted reporting. Private corpus shards and model weights
must remain outside the Git repository.
"""

from __future__ import annotations

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
PRIVATE_TRAINING_VERSION = "private_clrsg_training_v1"
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
    if any((root / marker).exists() for marker in {".git", "pyproject.toml", "frontend"}):
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
    increments = np.asarray([
        _transition_magnitude(passes[index - 1], passes[index])
        for index in range(1, len(passes))
    ], dtype=float)
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
        seeds.append(PrivateSeed(
            flower_id=flower.flower_id,
            topology=str(flower.topology),
            source_hash=str(flower.source_sha256),
            passes=passes,
            schedule=historical_progress_schedule(passes),
        ))
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
    sx = float(rng.uniform(0.80, 1.20))
    sy = float(rng.uniform(0.80, 1.20))
    angle = math.radians(float(rng.uniform(-10.0, 10.0)))
    mirror = bool(rng.integers(0, 2))
    magnitude = float(rng.uniform(0.01, 0.07))
    centered = points - points.mean(axis=0, keepdims=True)
    centered[:, 0] *= sx * (-1.0 if mirror else 1.0)
    centered[:, 1] *= sy
    rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    centered = centered @ rotation.T
    tangent = _tangent(centered)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    field = _smooth_field(rng, len(centered), magnitude)
    if _closed(seed.topology):
        field[0] = field[-1] = 0.0
    transformed = centered + normal * field[:, None]
    transformed -= transformed.mean(axis=0, keepdims=True)
    if _closed(seed.topology) and np.linalg.norm(transformed[0] - transformed[-1]) < 0.05:
        transformed[-1] = transformed[0]
    recipe = {
        "version": "private_profile_transform_v1",
        "uniform_family": "COMPOSITE_MEDIUM_MAGNITUDE",
        "scale_x": round(sx, 8),
        "scale_y": round(sy, 8),
        "rotation_degrees": round(math.degrees(angle), 8),
        "mirror_horizontal": mirror,
        "normal_warp_magnitude": round(magnitude, 8),
        "seed": int(base_seed),
        "sample_index": int(sample_index),
        "source_flower_id": seed.flower_id,
    }
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
    smooth = np.column_stack([
        np.convolve(np.pad(displacement[:, axis], (2, 2), mode="edge"), kernel, mode="valid")
        for axis in range(2)
    ])
    warped = np.asarray([
        source_pass + smooth * float(progress)
        for source_pass, progress in zip(seed.passes, seed.schedule)
    ], dtype=float)
    warped[-1] = target
    teacher = _interp_sequence(warped, seed.schedule, station_count)
    teacher[-1] = target
    return teacher


def deterministic_baseline(target: np.ndarray, station_count: int, topology: str) -> np.ndarray:
    if _closed(topology):
        start = target * 0.82
    else:
        start = np.column_stack([np.linspace(-1.0, 1.0, len(target)), np.zeros(len(target))])
    progress = np.linspace(0.0, 1.0, station_count)
    return np.asarray([start * (1.0 - value) + target * value for value in progress], dtype=float)


def _normalize_slots(sequence: np.ndarray, slots: int = NORMALIZED_SEQUENCE_SLOTS) -> np.ndarray:
    return _interp_sequence(sequence, np.linspace(0.0, 1.0, len(sequence)), slots)


def _split(parent_group: str) -> str:
    value = int(sha256(parent_group.encode()).hexdigest()[:8], 16) % 100
    return "TRAIN" if value < 70 else "VALIDATION" if value < 85 else "TEST"


def _profile_payload(target: np.ndarray, seed: PrivateSeed, profile_id: str) -> dict[str, Any]:
    closed = _closed(seed.topology)
    vertices = [
        {"vertex_id": f"v-{index + 1:03d}", "x": round(float(point[0]), 10), "y": round(float(point[1]), 10)}
        for index, point in enumerate(target)
    ]
    segments = [
        {
            "segment_id": f"s-{index + 1:03d}",
            "type": "LINE",
            "start_vertex_id": vertices[index]["vertex_id"],
            "end_vertex_id": vertices[index + 1]["vertex_id"],
        }
        for index in range(len(vertices) - 1)
    ]
    if closed:
        segments.append({
            "segment_id": f"s-{len(segments) + 1:03d}",
            "type": "LINE",
            "start_vertex_id": vertices[-1]["vertex_id"],
            "end_vertex_id": vertices[0]["vertex_id"],
        })
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "name": "Private derived visual target",
        "topology": "CLOSED_CONTOUR" if closed else "OPEN_PATH",
        "closed": closed,
        "computational_seam_vertex_id": vertices[0]["vertex_id"] if closed else None,
        "vertices": vertices,
        "segments": segments,
        "metadata": {
            "source": "PRIVATE_SYNTHETIC_DERIVED",
            "visual_only": True,
            "source_flower_id": seed.flower_id,
        },
    }


def generate_private_corpus(
    dataset_path: Path,
    output_root: Path,
    *,
    samples_per_seed: int = 100,
    seed: int = 1729,
) -> tuple[SyntheticCorpus, CorpusBuildSummary]:
    output_root = _assert_private_root(output_root)
    seeds = load_private_seeds(dataset_path)
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
                samples.append(SyntheticSample(
                    sample_id=sample_id,
                    classification="PRIVATE_SYNTHETIC_DERIVED",
                    family_id=private_seed.flower_id,
                    parent_group_id=parent,
                    target_profile=profile,
                    station_count=station_count,
                    teacher_sequence=teacher_28.tolist(),
                    baseline_sequence=baseline_28.tolist(),
                    transform_recipe={**recipe, "target_hash": target_key, "residual_rms": residual_rms},
                    progression_schedule={
                        "name": f"HISTORICAL_{private_seed.flower_id}",
                        "teacher_version": PRIVATE_TEACHER_VERSION,
                        "source_station_count": private_seed.station_count,
                    },
                    split=_split(parent),
                    warnings=["PRIVATE_SYNTHETIC_DERIVED_NOT_INDEPENDENT_FACTORY_EVIDENCE"],
                ))
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
    recipe = {
        "generator_version": PRIVATE_CORPUS_VERSION,
        "teacher_version": PRIVATE_TEACHER_VERSION,
        "seed": seed,
        "samples_per_seed": samples_per_seed,
        "seed_ids": [item.flower_id for item in seeds],
        "source_hashes": [item.source_hash for item in seeds],
    }
    manifest = SyntheticCorpusManifest(
        dataset_id="private-corpus-" + stable_hash(recipe)[:16],
        dataset_version=PRIVATE_CORPUS_VERSION,
        generator_version=PRIVATE_CORPUS_VERSION,
        seed=seed,
        classification=PRIVATE_CORPUS_CLASSIFICATION,
        sample_counts=split_counts,
        station_distribution=station_distribution,
        family_distribution=family_distribution,
        classification_distribution={"PRIVATE_SYNTHETIC_DERIVED": len(samples)},
        recipe_hash=stable_hash(recipe),
        privacy={"contains_private_derived_geometry": True, "committable": False},
    )
    corpus = SyntheticCorpus(manifest, samples)
    corpus.write(output_root)
    summary = CorpusBuildSummary(
        dataset_id=manifest.dataset_id,
        dataset_hash=manifest.content_hash,
        generated=generated,
        accepted=len(samples),
        rejected=rejected,
        duplicates=duplicates,
        seed_count=len(seeds),
        pass_count=sum(item.station_count for item in seeds),
        station_counts=tuple(sorted({item.station_count for item in samples})),
        split_counts=split_counts,
    )
    (output_root / "private_summary.json").write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return corpus, summary


def _rms(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(left, dtype=float) - np.asarray(right, dtype=float)) ** 2)))


def _prediction_alpha(status: str) -> float:
    if status == "IN_DISTRIBUTION":
        return 0.85
    if status == "NEAR_DISTRIBUTION":
        return 0.50
    return 0.0


def evaluate_model(model_root: Path, corpus: SyntheticCorpus) -> dict[str, Any]:
    model = load_clrsg_model(model_root)
    groups: dict[str, list[dict[str, Any]]] = {}
    for sample in corpus.samples:
        if sample.split not in {"VALIDATION", "TEST"}:
            continue
        baseline = np.asarray(sample.baseline_sequence, dtype=float)
        teacher = np.asarray(sample.teacher_sequence, dtype=float)
        prediction = model.predict(sample.target_profile, sample.station_count)
        alpha = _prediction_alpha(prediction["ood_status"])
        learned = baseline + alpha * np.asarray(prediction["residual"], dtype=float)
        learned[-1] = teacher[-1]
        row = {
            "sample_id": sample.sample_id,
            "split": sample.split,
            "family_id": sample.family_id,
            "station_count": sample.station_count,
            "baseline_rms": _rms(baseline, teacher),
            "learned_rms": _rms(learned, teacher),
            "ood_status": prediction["ood_status"],
            "ensemble_disagreement": float(prediction["ensemble_disagreement"]),
            "blend_alpha": alpha,
        }
        groups.setdefault(sample.split, []).append(row)

    def aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
        values = list(rows)
        if not values:
            return {"sample_count": 0, "baseline_rms": None, "learned_rms": None, "relative_improvement": None}
        baseline = float(np.mean([item["baseline_rms"] for item in values]))
        learned = float(np.mean([item["learned_rms"] for item in values]))
        improvement = (baseline - learned) / baseline if baseline > 1e-12 else 0.0
        return {
            "sample_count": len(values),
            "baseline_rms": baseline,
            "learned_rms": learned,
            "relative_improvement": improvement,
            "fallback_rate": sum(item["blend_alpha"] == 0.0 for item in values) / len(values),
            "mean_ensemble_disagreement": float(np.mean([item["ensemble_disagreement"] for item in values])),
        }

    validation = aggregate(groups.get("VALIDATION", []))
    test = aggregate(groups.get("TEST", []))
    family_rows: dict[str, list[dict[str, Any]]] = {}
    for rows in groups.values():
        for item in rows:
            family_rows.setdefault(item["family_id"], []).append(item)
    family_metrics = {key: aggregate(value) for key, value in sorted(family_rows.items())}
    approved = (
        test.get("relative_improvement") is not None
        and float(test["relative_improvement"]) >= 0.05
        and float(test.get("fallback_rate") or 0.0) <= 0.50
    )
    return {
        "evaluation_version": "private_clrsg_evaluation_v1",
        "model_id": model.model_id,
        "privacy_classification": model.manifest.get("privacy_classification"),
        "validation": validation,
        "test": test,
        "family_metrics": family_metrics,
        "quality_status": "PASS" if approved else "NO_MEANINGFUL_IMPROVEMENT",
        "approval_recommended": approved,
        "manufacturing_approval": "NOT_APPROVED",
    }


def _refresh_hashes(model_root: Path) -> None:
    hashes: dict[str, str] = {}
    for path in sorted(model_root.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes[str(path.relative_to(model_root))] = sha256(path.read_bytes()).hexdigest()
    (model_root / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")


def train_private_model(
    corpus: SyntheticCorpus,
    model_root: Path,
    *,
    ensemble_members: int = 5,
    seed: int = 1729,
) -> dict[str, Any]:
    model_root = _assert_private_root(model_root)
    started = time.monotonic()
    result = train_clrsg(corpus, model_root, ensemble_members=ensemble_members, seed=seed)
    manifest_path = model_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "privacy_classification": PRIVATE_MODEL_CLASSIFICATION,
        "private_corpus_classification": PRIVATE_CORPUS_CLASSIFICATION,
        "teacher_version": PRIVATE_TEACHER_VERSION,
        "training_version": PRIVATE_TRAINING_VERSION,
        "approval_status": "EVALUATION_REQUIRED",
        "activation_status": "INACTIVE",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    evaluation = evaluate_model(model_root, corpus)
    (model_root / "evaluation_metrics.json").write_text(json.dumps(evaluation, indent=2, sort_keys=True), encoding="utf-8")
    validation = evaluation["validation"]
    (model_root / "validation_metrics.json").write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    training = {
        **result["metrics"],
        "training_version": PRIVATE_TRAINING_VERSION,
        "duration_seconds": time.monotonic() - started,
        "privacy_classification": PRIVATE_MODEL_CLASSIFICATION,
    }
    (model_root / "training_metrics.json").write_text(json.dumps(training, indent=2, sort_keys=True), encoding="utf-8")
    calibration = {
        "method": "NON_PROBABILISTIC_EMPIRICAL_CALIBRATION",
        "status": "DIAGNOSTIC_ONLY",
        "sample_count": int(validation.get("sample_count") or 0),
        "mean_visual_error": validation.get("learned_rms"),
        "warning": "Two real seed flowers do not support probability calibration.",
    }
    (model_root / "calibration.json").write_text(json.dumps(calibration, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    load_clrsg_model(model_root)
    return {
        "model_id": manifest["model_id"],
        "model_root": str(model_root),
        "privacy_classification": PRIVATE_MODEL_CLASSIFICATION,
        "evaluation": evaluation,
        "approval_recommended": evaluation["approval_recommended"],
    }


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
    approval = {
        "model_id": manifest["model_id"],
        "status": manifest["approval_status"],
        "gates": {
            "artifact_hashes": True,
            "private_classification": True,
            "test_relative_improvement_at_least_5_percent": approved,
            "deterministic_fallback_required": True,
        },
        "manufacturing_approval": "NOT_APPROVED",
    }
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
    active = {
        "model_id": manifest["model_id"],
        "algorithm_version": manifest["algorithm_version"],
        "privacy_classification": manifest["privacy_classification"],
        "model_root": str(model_root),
        "production_approval": "NOT_APPROVED",
    }
    (registry_root / "active_model.json").write_text(json.dumps(active, indent=2, sort_keys=True), encoding="utf-8")
    manifest["activation_status"] = "ACTIVE"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _refresh_hashes(model_root)
    return {key: value for key, value in active.items() if key != "model_root"} | {
        "status": "ACTIVE",
        "environment_instruction": "Set ROLLFORM_ACTIVE_CLRSG_MODEL to the approved local model directory.",
    }


def private_plan(dataset_path: Path, *, samples_per_seed: int = 100) -> dict[str, Any]:
    seeds = load_private_seeds(dataset_path)
    return {
        "phase": "Phase 20 private CLRSG",
        "seed_flower_count": len(seeds),
        "private_pass_count": sum(item.station_count for item in seeds),
        "flowers": [
            {
                "flower_id": item.flower_id,
                "station_count": item.station_count,
                "topology": item.topology,
                "schedule_steps": len(item.schedule),
            }
            for item in seeds
        ],
        "proposed_generated_samples": len(seeds) * samples_per_seed,
        "station_range": [8, 28],
        "classification": PRIVATE_CORPUS_CLASSIFICATION,
        "teacher_version": PRIVATE_TEACHER_VERSION,
        "private_paths_redacted": True,
        "manufacturing_approval": "NOT_APPROVED",
    }


def environment_paths() -> dict[str, Path]:
    required = {
        "dataset": os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET"),
        "corpus_root": os.environ.get("ROLLFORM_SYNTHETIC_CORPUS_ROOT"),
        "model_root": os.environ.get("ROLLFORM_MODEL_REGISTRY_ROOT"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("missing private CLRSG environment variables: " + ", ".join(missing))
    return {key: Path(value).expanduser().resolve() for key, value in required.items() if value}
