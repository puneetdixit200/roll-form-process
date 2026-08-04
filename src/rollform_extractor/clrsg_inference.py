"""Conservative learned-hybrid inference over the existing visual baseline."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from rollform_extractor.clrsg_model import CLRSGModel, load_clrsg_model
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import VisualProfile


def _interpolate_points(points: list[list[float]], count: int = 128) -> np.ndarray:
    value = np.asarray(points, dtype=float)
    if len(value) == count:
        return value
    source = np.linspace(0, 1, len(value)); target = np.linspace(0, 1, count)
    return np.column_stack([np.interp(target, source, value[:, axis]) for axis in range(2)])


def _apply_delta(points: list[list[float]], delta: np.ndarray, alpha: float) -> list[list[float]]:
    base = _interpolate_points(points)
    corrected = base + alpha * delta
    target = np.linspace(0, 1, len(points))
    source = np.linspace(0, 1, len(corrected))
    return [[round(float(np.interp(t, source, corrected[:, axis])), 8) for axis in range(2)] for t in target]


def _learned_candidate(baseline: dict[str, Any], prediction: dict[str, Any], *, alpha: float, kind: str, target_points: list[list[float]]) -> dict[str, Any]:
    candidate = deepcopy(baseline)
    candidate["candidate_style"] = kind
    candidate["candidate_id"] = "vfg-" + sha256(f"{baseline['candidate_id']}|{kind}|{alpha:.6f}".encode()).hexdigest()[:16]
    candidate["status"] = "LEARNED_SEQUENCE_ACCEPTED" if alpha > 0 else "LEARNED_SEQUENCE_FALLBACK"
    for index, item in enumerate(candidate.get("passes", [])):
        slot = min(27, round(item.get("progress", index / max(1, len(candidate["passes"]) - 1)) * 27))
        delta = prediction["residual"][slot]
        if index == len(candidate["passes"]) - 1:
            item["profile"]["points"] = deepcopy(target_points)
        else:
            item["profile"]["points"] = _apply_delta(item["profile"]["points"], delta, alpha)
        item.setdefault("generation", {})["mode"] = "CLRSG_LEARNED_HYBRID_V1"
        item["generation"]["model_id"] = prediction.get("model_id")
        item["generation"]["blend_alpha"] = alpha
        item["generation"]["ood_status"] = prediction["ood_status"]
    support = max(0.0, min(100.0, 100.0 * (1.0 - min(1.0, prediction["condition_distance"] / 5.0)) * (1.0 - min(1.0, prediction["ensemble_disagreement"] / .25))))
    candidate["visual_confidence"] = {**candidate.get("visual_confidence", {}), "model_support_confidence": round(support, 4), "combined_visual_prototype_confidence": round(.65 * candidate.get("visual_confidence", {}).get("score", 0) + .35 * support, 4), "non_calibrated": True}
    candidate["learned_support"] = {"algorithm_version": "clrsg_visual_sequence_v1", "blend_alpha": alpha, "blend_reason": "conservative residual blend", "ood_status": prediction["ood_status"], "condition_distance": prediction["condition_distance"], "ensemble_disagreement": prediction["ensemble_disagreement"]}
    candidate["warnings"] = list(dict.fromkeys(candidate.get("warnings", []) + ["VISUAL_ONLY_NOT_MANUFACTURING_VALIDATION", "CLRSG_SYNTHETIC_TRAINING_NOT_FACTORY_EVIDENCE"]))
    return candidate


def infer_learned_candidates(profile: VisualProfile, baseline_result: dict[str, Any], model: CLRSGModel | None) -> dict[str, Any]:
    if model is None:
        return {"candidates": [], "status": "MODEL_UNAVAILABLE", "warnings": ["MODEL_UNAVAILABLE"]}
    if profile.topology not in model.manifest.get("supported_topology", []):
        return {"candidates": [], "status": "UNSUPPORTED_TOPOLOGY", "warnings": ["UNSUPPORTED_TOPOLOGY"]}
    target = canonicalize_profile(profile, samples=256)["points"]
    output: list[dict[str, Any]] = []
    for baseline in baseline_result.get("candidates", [])[:2]:
        try:
            prediction = model.predict(profile.to_dict(), int(baseline["station_count"]))
        except (ValueError, np.linalg.LinAlgError):
            continue
        prediction["model_id"] = model.model_id
        if prediction["ood_status"] == "OUT_OF_DISTRIBUTION":
            alpha = 0.0
        elif prediction["ood_status"] == "NEAR_DISTRIBUTION":
            alpha = .5
        else:
            alpha = .85
        output.append(_learned_candidate(baseline, prediction, alpha=alpha, kind="CLRSG_LEARNED_MEAN", target_points=target))
        output.append(_learned_candidate(baseline, prediction, alpha=alpha * .45, kind="CLRSG_CONSERVATIVE_BLEND", target_points=target))
    output.sort(key=lambda item: (-item.get("visual_confidence", {}).get("combined_visual_prototype_confidence", 0), item.get("station_count", 0), item["candidate_style"], item["candidate_id"]))
    return {"candidates": output, "status": "READY" if output else "MODEL_UNAVAILABLE", "warnings": [] if output else ["MODEL_UNAVAILABLE"]}


def load_active_model() -> CLRSGModel | None:
    import os

    configured = os.environ.get("ROLLFORM_ACTIVE_CLRSG_MODEL")
    if not configured:
        return None
    try:
        return load_clrsg_model(Path(configured).expanduser().resolve())
    except (OSError, ValueError, KeyError):
        return None
