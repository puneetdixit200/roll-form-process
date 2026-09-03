"""Shared, explainable historical profile comparison contract."""
from __future__ import annotations

from typing import Any, Mapping

from rollform_extractor.visual_profile_metrics import compare_profiles


def compare_generated_to_historical(generated_profile: Mapping[str, Any], historical_pass: Mapping[str, Any], *, generated_progress: float, historical_progress: float, allow_mirror: bool = True, allow_rotation: bool = False) -> dict[str, Any]:
    base = historical_pass["profile"]
    variants = [(base, False, False)]
    if allow_rotation:
        points = base.get("points", [])
        for turns in range(1, 4):
            rotated = points
            for _ in range(turns): rotated = [[-point[1], point[0]] for point in rotated]
            variants.append(({**base, "points": rotated}, False, True))
    if allow_mirror:
        variants.append(({**base, "points": [[-p[0], p[1]] for p in base.get("points", [])]}, True, False))
    matches = []
    for variant, mirror_used, rotation_used in variants:
        result = compare_profiles(generated_profile, variant, left_progress=generated_progress, right_progress=historical_progress)
        result.update({"source_flower_id": historical_pass.get("source_flower_id"), "source_pass_id": historical_pass.get("source_pass_id"), "mirror_used": mirror_used, "rotation_used": rotation_used, "alignment": "CANONICAL", "historical_points": [list(point) for point in variant.get("points", [])]})
        matches.append(result)
    return max(matches, key=lambda item: (item["overall_score"], not item["mirror_used"], not item["rotation_used"]))
