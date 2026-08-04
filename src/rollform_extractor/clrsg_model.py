"""Small deterministic CLRSG model: PCA residuals plus ridge ensemble."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np

from rollform_extractor.synthetic_corpus_schema import SyntheticCorpus, stable_hash
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


CLRSG_ALGORITHM_VERSION = "clrsg_visual_sequence_v1"
FEATURE_SCHEMA_VERSION = 1
SEQUENCE_SHAPE = (28, 128, 2)


def _pca(matrix: np.ndarray, max_components: int, variance_target: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mean = matrix.mean(axis=0)
    centered = matrix - mean
    u, singular, vt = np.linalg.svd(centered, full_matrices=False)
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
    identity = np.eye(augmented.shape[1]); identity[-1, -1] = 0
    return np.linalg.solve(augmented.T @ augmented + lam * identity, augmented.T @ y)


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
        outputs = []
        for member in self.members:
            outputs.append(np.concatenate([x, [1.0]]) @ member)
        latent = np.asarray(outputs)
        mean_latent = latent.mean(axis=0)
        residual_flat = self.residual_mean + mean_latent @ self.residual_components
        disagreement = float(np.sqrt(np.mean(np.var(latent, axis=0))))
        distance = float(np.sqrt(np.mean(x * x)))
        if distance <= self.ood_thresholds.get("in_distribution", 2.5):
            ood = "IN_DISTRIBUTION"
        elif distance <= self.ood_thresholds.get("near_distribution", 4.0):
            ood = "NEAR_DISTRIBUTION"
        else:
            ood = "OUT_OF_DISTRIBUTION"
        return {"residual": residual_flat.reshape(SEQUENCE_SHAPE), "condition_distance": distance, "ensemble_disagreement": disagreement, "ood_status": ood, "latent_members": len(outputs)}


def train_clrsg(corpus: SyntheticCorpus, output: Path, *, ensemble_members: int = 5, seed: int = 1729) -> dict[str, Any]:
    import shutil

    train = [s for s in corpus.samples if s.split == "TRAIN"]
    validation = [s for s in corpus.samples if s.split == "VALIDATION"]
    if len(train) < 4:
        raise ValueError("CLRSG requires at least four training samples")
    target_matrix = np.asarray([_encode_profile(s.target_profile, s.station_count)[:-5] for s in train], dtype=float)
    target_mean, target_components, target_var, target_ratio = _pca(target_matrix, 32, .99)
    def features(items: list[Any]) -> np.ndarray:
        result = []
        for item in items:
            raw = _encode_profile(item.target_profile, item.station_count)
            result.append(np.concatenate([(raw[:-5] - target_mean) @ target_components.T, raw[-5:]]))
        return np.asarray(result)
    x_train_raw = features(train); x_validation_raw = features(validation or train[:1])
    fmean = x_train_raw.mean(axis=0); fscale = x_train_raw.std(axis=0); fscale[fscale < 1e-9] = 1.0
    x_train = (x_train_raw - fmean) / fscale
    baseline = np.asarray([np.asarray(s.baseline_sequence) for s in train]).reshape(len(train), -1)
    teacher = np.asarray([np.asarray(s.teacher_sequence) for s in train]).reshape(len(train), -1)
    residual = teacher - baseline
    residual_mean, residual_components, residual_var, residual_ratio = _pca(residual, 32, .98)
    z = (residual - residual_mean) @ residual_components.T
    lambdas = [1e-6, 1e-4, 1e-2, 1, 100]
    selected = lambdas[0]
    if validation:
        best = float("inf")
        xv = (x_validation_raw - fmean) / fscale
        yv = np.asarray([np.asarray(s.teacher_sequence).reshape(-1) - np.asarray(s.baseline_sequence).reshape(-1) for s in validation])
        zv = (yv - residual_mean) @ residual_components.T
        for lam in lambdas:
            coef = _ridge(x_train, z, lam)
            error = float(np.mean((np.concatenate([xv, np.ones((len(xv), 1))], axis=1) @ coef - zv) ** 2))
            if error < best:
                best, selected = error, lam
    output.mkdir(parents=True, exist_ok=True)
    (output / "ensemble").mkdir(exist_ok=True)
    members: list[np.ndarray] = []
    for member_index in range(ensemble_members):
        rng = np.random.default_rng(seed + member_index)
        indices = rng.integers(0, len(train), size=len(train))
        coef = _ridge(x_train[indices], z[indices], selected)
        members.append(coef)
        np.savez_compressed(output / "ensemble" / f"member-{member_index:03d}.npz", coefficients=coef)
    feature_names = [f"target_pca_{i:02d}" for i in range(target_components.shape[0])] + ["topology_closed", "station_count_normalized", "aspect_ratio", "width", "height"]
    manifest = {
        "schema_version": 1, "model_id": "clrsg-" + sha256(f"{corpus.manifest.dataset_id}|{seed}|{selected}".encode()).hexdigest()[:16],
        "algorithm_version": CLRSG_ALGORITHM_VERSION, "dataset_id": corpus.manifest.dataset_id, "dataset_hash": corpus.manifest.content_hash,
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "member_count": ensemble_members, "station_range": [8, 28],
        "supported_topology": ["OPEN_PATH", "CLOSED_CONTOUR"], "privacy_classification": "PUBLIC_TEST_MODEL", "selected_lambda": selected,
        "sequence_shape": list(SEQUENCE_SHAPE), "created_by": "clrsg_training_v1",
    }
    np.savez_compressed(output / "target_pca.npz", mean=target_mean, components=target_components, explained_variance=target_var, explained_variance_ratio=target_ratio)
    np.savez_compressed(output / "residual_pca.npz", mean=residual_mean, components=residual_components, explained_variance=residual_var, explained_variance_ratio=residual_ratio, feature_mean=fmean, feature_scale=fscale)
    (output / "feature_schema.json").write_text(json.dumps({"schema_version": FEATURE_SCHEMA_VERSION, "feature_names": feature_names}, indent=2, sort_keys=True), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    hashes = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes[str(path.relative_to(output))] = sha256(path.read_bytes()).hexdigest()
    (output / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True), encoding="utf-8")
    metrics = {"train_count": len(train), "validation_count": len(validation), "target_pca_components": int(target_components.shape[0]), "residual_pca_components": int(residual_components.shape[0]), "selected_lambda": selected, "ensemble_members": ensemble_members, "validation_status": "DIAGNOSTIC_ONLY"}
    for name in ("training_metrics.json", "validation_metrics.json", "evaluation_metrics.json", "calibration.json"):
        (output / name).write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    return {"model_id": manifest["model_id"], "manifest": manifest, "metrics": metrics, "output": str(output)}


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
    target = np.load(root / "target_pca.npz", allow_pickle=False); residual = np.load(root / "residual_pca.npz", allow_pickle=False)
    members = [np.load(path, allow_pickle=False)["coefficients"] for path in sorted((root / "ensemble").glob("member-*.npz"))]
    schema = json.loads((root / "feature_schema.json").read_text(encoding="utf-8"))
    return CLRSGModel(manifest["model_id"], schema["feature_names"], residual["feature_mean"], residual["feature_scale"], target["mean"], target["components"], residual["mean"], residual["components"], members, {"in_distribution": 2.5, "near_distribution": 4.0}, manifest)
