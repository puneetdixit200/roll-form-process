"""Conservative learned-hybrid inference over the existing visual baseline."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np

from rollform_extractor.clrsg_model import CLRSGModel, load_clrsg_model
from rollform_extractor.strip_length_constraint import (
    candidate_constraint_summary,
    project_constant_strip_length,
)
from rollform_extractor.visual_flower_engine import legacy_progress_points
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import VisualProfile


def _interpolate_points(points: list[list[float]], count: int = 128) -> np.ndarray:
    value = np.asarray(points, dtype=float)
    if len(value) == count:
        return value
    source = np.linspace(0, 1, len(value))
    target = np.linspace(0, 1, count)
    return np.column_stack(
        [np.interp(target, source, value[:, axis]) for axis in range(2)]
    )


def _apply_delta(
    points: list[list[float]],
    delta: np.ndarray,
    alpha: float,
) -> list[list[float]]:
    base = _interpolate_points(points)
    corrected = base + alpha * delta
    target = np.linspace(0, 1, len(points))
    source = np.linspace(0, 1, len(corrected))
    return [
        [
            round(float(np.interp(t, source, corrected[:, axis])), 8)
            for axis in range(2)
        ]
        for t in target
    ]


def _learned_candidate(
    baseline: dict[str, Any],
    prediction: dict[str, Any],
    *,
    alpha: float,
    kind: str,
    target_points: list[list[float]],
    topology: str,
) -> dict[str, Any]:
    candidate = deepcopy(baseline)
    candidate["candidate_style"] = kind
    candidate["candidate_id"] = "vfg-" + sha256(
        f"{baseline['candidate_id']}|{kind}|{alpha:.6f}|constant-length-v1".encode()
    ).hexdigest()[:16]
    candidate["status"] = (
        "LEARNED_SEQUENCE_ACCEPTED" if alpha > 0 else "LEARNED_SEQUENCE_FALLBACK"
    )
    baseline_style = baseline.get("candidate_style", "UNIFORM_PROGRESSION")

    for index, item in enumerate(candidate.get("passes", [])):
        progress = float(
            item.get(
                "progress",
                index / max(1, len(candidate["passes"]) - 1),
            )
        )
        slot = min(27, round(progress * 27))
        delta = prediction["residual"][slot]

        # CLRSG v1 was trained against the legacy unconstrained baseline.
        # Reconstruct that exact reference, apply the learned residual, then
        # enforce the new centerline invariant. This keeps the approved model's
        # residual reference frame intact.
        raw_baseline = [
            list(point)
            for point in legacy_progress_points(
                target_points,
                progress,
                topology,
                baseline_style,
            )
        ]

        if index == len(candidate["passes"]) - 1:
            constrained_points = deepcopy(target_points)
            _, strip_constraint = project_constant_strip_length(
                constrained_points,
                target_points,
                topology,
            )
            strip_constraint["method"] = "EXACT_FINAL_TARGET"
            strip_constraint["projection_rms"] = 0.0
        else:
            raw_corrected = _apply_delta(raw_baseline, delta, alpha)
            constrained_points, strip_constraint = project_constant_strip_length(
                raw_corrected,
                target_points,
                topology,
            )

        item["profile"]["points"] = constrained_points
        generation = item.setdefault("generation", {})
        generation["mode"] = "CLRSG_LEARNED_HYBRID_V1_CONSTANT_LENGTH"
        generation["model_id"] = prediction.get("model_id")
        generation["blend_alpha"] = alpha
        generation["ood_status"] = prediction["ood_status"]
        generation["residual_reference"] = "LEGACY_UNCONSTRAINED_BASELINE_V1"
        generation["post_prediction_constraint"] = "constant_centerline_length_v1"
        generation["strip_length_constraint"] = strip_constraint
        if not strip_constraint["satisfied"]:
            item["warnings"] = list(
                dict.fromkeys(
                    item.get("warnings", [])
                    + ["STRIP_LENGTH_CONSTRAINT_TOLERANCE_EXCEEDED"]
                )
            )

    support = max(
        0.0,
        min(
            100.0,
            100.0
            * (
                1.0
                - min(
                    1.0,
                    prediction["condition_distance"] / 5.0,
                )
            )
            * (
                1.0
                - min(
                    1.0,
                    prediction["ensemble_disagreement"] / 0.25,
                )
            ),
        ),
    )
    candidate["visual_confidence"] = {
        **candidate.get("visual_confidence", {}),
        "model_support_confidence": round(support, 4),
        "combined_visual_prototype_confidence": round(
            0.65 * candidate.get("visual_confidence", {}).get("score", 0)
            + 0.35 * support,
            4,
        ),
        "non_calibrated": True,
    }
    candidate["learned_support"] = {
        "algorithm_version": "clrsg_visual_sequence_v1",
        "model_id": prediction.get("model_id"),
        "blend_alpha": alpha,
        "blend_reason": "conservative residual blend followed by constant-length projection",
        "ood_status": prediction["ood_status"],
        "condition_distance": prediction["condition_distance"],
        "ensemble_disagreement": prediction["ensemble_disagreement"],
        "residual_reference": "LEGACY_UNCONSTRAINED_BASELINE_V1",
        "post_prediction_constraint": "constant_centerline_length_v1",
    }
    candidate["warnings"] = list(
        dict.fromkeys(
            candidate.get("warnings", [])
            + [
                "VISUAL_ONLY_NOT_MANUFACTURING_VALIDATION",
                "CLRSG_SYNTHETIC_TRAINING_NOT_FACTORY_EVIDENCE",
                "CENTERLINE_STRIP_LENGTH_CONSTRAINED",
            ]
        )
    )
    candidate["geometry_constraints"] = candidate_constraint_summary(candidate)
    return candidate


def infer_learned_candidates(
    profile: VisualProfile,
    baseline_result: dict[str, Any],
    model: CLRSGModel | None,
) -> dict[str, Any]:
    if model is None:
        return {
            "candidates": [],
            "status": "MODEL_UNAVAILABLE",
            "warnings": ["MODEL_UNAVAILABLE"],
        }
    if profile.topology not in model.manifest.get("supported_topology", []):
        return {
            "candidates": [],
            "status": "UNSUPPORTED_TOPOLOGY",
            "warnings": ["UNSUPPORTED_TOPOLOGY"],
        }
    target = canonicalize_profile(profile, samples=256)["points"]
    output: list[dict[str, Any]] = []
    for baseline in baseline_result.get("candidates", [])[:2]:
        try:
            prediction = model.predict(
                profile.to_dict(),
                int(baseline["station_count"]),
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        prediction["model_id"] = model.model_id
        if prediction["ood_status"] == "OUT_OF_DISTRIBUTION":
            alpha = 0.0
        elif prediction["ood_status"] == "NEAR_DISTRIBUTION":
            alpha = 0.5
        else:
            alpha = 0.85
        output.append(
            _learned_candidate(
                baseline,
                prediction,
                alpha=alpha,
                kind="CLRSG_LEARNED_MEAN",
                target_points=target,
                topology=profile.topology,
            )
        )
        output.append(
            _learned_candidate(
                baseline,
                prediction,
                alpha=alpha * 0.45,
                kind="CLRSG_CONSERVATIVE_BLEND",
                target_points=target,
                topology=profile.topology,
            )
        )
    output.sort(
        key=lambda item: (
            -item.get("visual_confidence", {}).get(
                "combined_visual_prototype_confidence",
                0,
            ),
            item.get("station_count", 0),
            item["candidate_style"],
            item["candidate_id"],
        )
    )
    return {
        "candidates": output,
        "status": "READY" if output else "MODEL_UNAVAILABLE",
        "warnings": [] if output else ["MODEL_UNAVAILABLE"],
    }


def load_active_model() -> CLRSGModel | None:
    import os

    configured = os.environ.get("ROLLFORM_ACTIVE_CLRSG_MODEL")
    if not configured:
        return None
    try:
        return load_clrsg_model(Path(configured).expanduser().resolve())
    except (OSError, ValueError, KeyError):
        return None
