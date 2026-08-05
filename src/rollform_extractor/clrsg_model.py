"""Small deterministic CLRSG model: PCA residuals plus ridge ensemble."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np

from rollform_extractor.synthetic_corpus_schema import SyntheticCorpus
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


CLRSG_ALGORITHM_VERSION = "clrsg_visual_sequence_v1"
FEATURE_SCHEMA_VERSION = 1
SEQUENCE_SHAPE = (28, 128, 2)
DEFAULT_OOD_THRESHOLDS = {"in_distribution": 2.5, "near_distribution": 4.0}


def _pca(matrix: np.ndarray, max_components: int, variance_target: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mean = matrix.mean(axis=0)
    centered = matrix - mean
    _, singular, vt = np.linalg.svd(centered, full_matrices=False)
    variance = (singular**2) / max(1, matrix.shape[0] - 1)
    ratio = variance / max(variance.sum(), 1e-12)
    cumulative = np.cumsum(ratio)
    count = min(max_components, max(1, int(np.searchsorted(cumulative, variance_target) + 1)))
    components = vt[:count].copy()
    for row in components:
        pivot = int(np.argmax(np.abs(row)))
        if row[pivot] < 0:
            row *= -1
    return mean, components, variance[:count], ratio[:count]


def _encode_profile(profile: dict[str, Any], station_count: int) -> np.ndarray:
    canonical = canonicalize_profile(validate_profile(profile), samples=128)
    points = np.asarray(canonical["points"], dtype=float)
    topology = 1.0 if profile.get("topology") == "CLOSED_CONTOUR" else 0.0
    width, height = float(canonical.get("width") or 0), float(canonical.get("height") or 0)
    aspect = width / max(height, 1e-9)
    extras = np.asarray([topology, station_count / 28.0, aspect, width, height], dtype=float)
    return np.concatenate([points.reshape(-1), extras])


def _ridge(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    augmented = np.concatenate([x, np.ones((len(x), 1))], axis=1)
    identity = np.eye(augmented.shape[1])
    identity[-1, -1] = 0
    return np.linalg.solve(augmented.T @ augmented + lam * identity, augmented.T @ y)


def _privacy_classification(corpus: SyntheticCorpus) -> str:
    if corpus.manifest.classification == "PRIVATE_PROTOTYPE_CORPUS" or corpus.manifest.privacy.get("contains_private_derived_geometry"):
        return "PRIVATE_PROTOTYPE_MODEL"
    return "PUBLIC_TEST_MODEL"


def _read_ood_thresholds(root: Path) -> dict[str, float]:
    path = root / "ood_thresholds.json"
    if not path.is_file():
        return dict(DEFAULT_OOD_THRESHOLDS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    thresholds = payload.get("thresholds", payload)
    inside = float(thresholds["in_distribution"])
    near = float(thresholds["near_distribution"])
    if not np.isfinite(inside) or not np.isfinite(near) or inside <= 0 or near < inside:
        raise ValueError("invalid CLRSG OOD thresholds")
    return {"in_distribution": inside, "near_distribution": near}


@dataclass
class CLRSGModel:
    model_id: str
    feature_names: list[str]
    feature_mean: np.ndarray
    feature_scale: np.ndarray
    target_mean: np.ndarray
    target_components: np.ndarray
    residual_mean: np.ndarray
    residual_components: np.ndarray
    members: list[np.ndarray]
    ood_thresholds: dict[str, float]
    manifest: dict[str, Any]

    def condition(self, profile: dict[str, Any], station_count: int) -> np.ndarray:
        raw = _encode_profile(profile, station_count)
        target_flat = raw[:-5]
        target_z = (target_flat - self.target_mean) @ self.target_components.T
        features = np.concatenate([target_z, raw[-5:]])
        if len(features) != len(self.feature_names):
            raise ValueError("CLRSG feature schema mismatch")
        return (features - self.feature_mean) / self.feature_scale

    def predict(self, profile: dict[str, Any], station_count: int) -> dict[str, Any]:
        x = self.condition(profile, station_count)
        outputs = [np.concatenate([x, [1.0]]) @ member for member in self.members]
        latent = np.asarray(outputs)
        mean_latent = latent.mean(axis=0)
        residual_flat = self.residual_mean + mean_latent @ self.residual_components
        disagreement = float(np.sqrt(np.mean(np.var(latent, axis=0))))
        distance = float(np.sqrt(np.mean(x * x)))
        if distance <= self.ood_thresholds["in_distribution"]:
            ood = "IN_DISTRIBUTION"
        elif distance <= self.ood_thresholds["near_distribution"]:
            ood = "NEAR_DISTRIBUTION"
        else:
            ood = "OUT_OF_DISTRIBUTION"
        return {
            "residual": residual_flat.reshape(SEQUENCE_SHAPE),
            "condition_distance": distance,
            "ensemble_disagreement": disagreement,
            "ood_status": ood,
            "latent_members": len(outputs),
            "ood_thresholds": dict(self.ood_thresholds),
        }


def train_clrsg(corpus: SyntheticCorpus, output: Path, *, ensemble_members: int = 5, seed: int = 1729) -> dict[str, Any]:
    train = [sample for sample in corpus.samples if sample.split == "TRAIN"]
    validation = [sample for sample in corpus.samples if sample.split == "VALIDATION"]
    if len(train) < 4:
        raise ValueError("CLRSG requires at least four training samples")

    target_matrix = np.asarray([_encode_profile(sample.target_profile, sample.station_count)[:-5] for sample in train], dtype=float)
    target_mean, target_components, target_var, target_ratio = _pca(target_matrix, 32, .99)

    def features(items: list[Any]) -> np.ndarray:
        rows = []
        for item in items:
            raw = _encode_profile(item.target_profile, item.station_count)
            rows.append(np.concatenate([(raw[:-5] - target_mean) @ target_components.T, raw[-5:]]))
        return np.asarray(rows)

    x_train_raw = features(train)
    x_validation_raw = features(validation or train[:1])
    feature_mean = x_train_raw.mean(axis=0)
    feature_scale = x_train_raw.std(axis=0)
    feature_scale[feature_scale < 1e-9] = 1.0
    x_train = (x_train_raw - feature_mean) / feature_scale

    baseline = np.asarray([np.asarray(sample.baseline_sequence) for sample in train]).reshape(len(train), -1)
    teacher = np.asarray([np.asarray(sample.teacher_sequence) for sample in train]).reshape(len(train), -1)
    residual = teacher - baseline
    residual_mean, residual_components, residual_var, residual_ratio = _pca(residual, 32, .98)
    latent_targets = (residual - residual_mean) @ residual_components.T

    lambdas = [1e-6, 1e-4, 1e-2, 1, 100]
    selected = lambdas[0]
    validation_curve: list[dict[str, float]] = []
    if validation:
        best = float("inf")
        x_validation = (x_validation_raw - feature_mean) / feature_scale
        validation_residual = np.asarray([np.asarray(sample.teacher_sequence).reshape(-1) - np.asarray(sample.baseline_sequence).reshape(-1) for sample in validation])
        validation_latent = (validation_residual - residual_mean) @ residual_components.T
        for lam in lambdas:
            coefficients = _ridge(x_train, latent_targets, lam)
            error = float(np.mean((np.concatenate([x_validation, np.ones((len(x_validation), 1))], axis=1) @ coefficients - validation_latent) ** 2))
            validation_curve.append({"lambda": float(lam), "latent_mse": error})
            if error < best:
                best, selected = error, lam

    output.mkdir(parents=True, exist_ok=True)
    (output / "ensemble").mkdir(exist_ok=True)
    parent_groups: dict[str, list[int]] = {}
    for index, sample in enumerate(train):
        parent_groups.setdefault(sample.parent_group_id, []).append(index)
    group_names = sorted(parent_groups)
    for member_index in range(ensemble_members):
        rng = np.random.default_rng(seed + member_index)
        sampled_groups = rng.choice(group_names, size=len(group_names), replace=True)
        indices = np.asarray([index for group in sampled_groups for index in parent_groups[str(group)]], dtype=int)
        coefficients = _ridge(x_train[indices], latent_targets[indices], selected)
        np.savez_compressed(output / "ensemble" / f"member-{member_index:03d}.npz", coefficients=coefficients, bootstrap_groups=np.asarray(sampled_groups, dtype="U"))

    feature_names = [f"target_pca_{i:02d}" for i in range(target_components.shape[0])] + ["topology_closed", "station_count_normalized", "aspect_ratio", "width", "height"]
    privacy = _privacy_classification(corpus)
    model_id = "clrsg-" + sha256(f"{corpus.manifest.dataset_id}|{corpus.manifest.content_hash}|{privacy}|{seed}|{selected}".encode()).hexdigest()[:16]
    manifest = {
        "schema_version": 1,
        "model_id": model_id,
        "algorithm_version": CLRSG_ALGORITHM_VERSION,
        "dataset_id": corpus.manifest.dataset_id,
        "dataset_hash": corpus.manifest.content_hash,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "member_count": ensemble_members,
        "station_range": [8, 28],
        "supported_topology": ["OPEN_PATH", "CLOSED_CONTOUR"],
        "privacy_classification": privacy,
        "selected_lambda": selected,
        "sequence_shape": list(SEQUENCE_SHAPE),
        "created_by": "clrsg_training_v1",
        "bootstrap_unit": "PARENT_GROUP",
        "ood_threshold_source": "DEFAULT_PENDING_VALIDATION",
    }
    np.savez_compressed(output / "target_pca.npz", mean=target_mean, components=target_components, explained_variance=target_var, explained_variance_ratio=target_ratio)
    np.savez_compressed(output / "residual_pca.npz", mean=residual_mean, components=residual_components, explained_variance=residual_var, explained_variance_ratio=residual_ratio, feature_mean=feature_mean, feature_scale=feature_scale)
    (output / "feature_schema.json").write_text(json.dumps({"schema_version": FEATURE_SCHEMA_VERSION, "feature_names": feature_names}, indent=2, sort_keys=True), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    metrics = {
        "train_count": len(train),
        "validation_count": len(validation),
        "target_pca_components": int(target_components.shape[0]),
        "residual_pca_components": int(residual_components.shape[0]),
        "selected_lambda": selected,
        "lambda_validation_curve": validation_curve,
        "ensemble_members": ensemble_members,
        "bootstrap_unit": "PARENT_GROUP",
        "validation_status": "DIAGNOSTIC_ONLY",
    }
    for name in ("training_metrics.json", "validation_metrics.json", "evaluation_metrics.json", "calibration.json"):
        (output / name).write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    _write_hashes(output)
    return {"model_id": model_id, "manifest": manifest, "metrics": metrics, "output": str(output)}


def _write_hashes(root: Path) -> None:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    (root / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")


def load_clrsg_model(root: Path) -> CLRSGModel:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("algorithm_version") != CLRSG_ALGORITHM_VERSION:
        raise ValueError("unsupported CLRSG algorithm version")
    if manifest.get("privacy_classification") not in {"PUBLIC_TEST_MODEL", "PRIVATE_PROTOTYPE_MODEL"}:
        raise ValueError("invalid CLRSG privacy classification")
    hashes = json.loads((root / "artifact_hashes.json").read_text(encoding="utf-8"))
    for relative, expected in hashes.items():
        path = root / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"invalid CLRSG artifact hash: {relative}")
    target = np.load(root / "target_pca.npz", allow_pickle=False)
    residual = np.load(root / "residual_pca.npz", allow_pickle=False)
    members = [np.load(path, allow_pickle=False)["coefficients"] for path in sorted((root / "ensemble").glob("member-*.npz"))]
    if len(members) != int(manifest.get("member_count", 0)):
        raise ValueError("CLRSG ensemble member count mismatch")
    schema = json.loads((root / "feature_schema.json").read_text(encoding="utf-8"))
    return CLRSGModel(manifest["model_id"], schema["feature_names"], residual["feature_mean"], residual["feature_scale"], target["mean"], target["components"], residual["mean"], residual["components"], members, _read_ood_thresholds(root), manifest)
