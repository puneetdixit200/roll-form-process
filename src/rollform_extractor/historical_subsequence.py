"""Deterministic, support-aware contiguous historical pass matching."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from rollform_extractor.historical_profile_matching import compare_generated_to_historical


def _ordered_passes(flower: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return sorted(
        flower.get("passes", []),
        key=lambda item: (
            int(item.get("inferred_order", 0)),
            str(item.get("source_pass_id", item.get("pass_id", ""))),
        ),
    )


def best_contiguous_subsequence(
    generated_passes: Iterable[Mapping[str, Any]],
    historical_flowers: Iterable[Mapping[str, Any]],
    *,
    minimum_length: int | None = None,
    minimum_mean_similarity: float = 0.35,
    minimum_alignment_score: float = 0.40,
    allow_mirror: bool = True,
    allow_rotation: bool = False,
    limit: int = 3,
) -> dict[str, Any] | None:
    """Find supported windows using the individual-pass comparison contract."""
    generated = list(generated_passes)
    if not generated:
        return None
    minimum_length = minimum_length or (2 if len(generated) < 3 else 3)
    if minimum_length > len(generated):
        return {"status": "INSUFFICIENT_HISTORICAL_SUBSEQUENCE_SUPPORT", "top_historical_subsequences": []}

    candidates: list[dict[str, Any]] = []
    for flower in sorted(historical_flowers, key=lambda item: str(item.get("flower_id", ""))):
        source = _ordered_passes(flower)
        for length in range(min(len(generated), len(source)), minimum_length - 1, -1):
            for start_g in range(len(generated) - length + 1):
                for start_s in range(len(source) - length + 1):
                    mapping: list[dict[str, Any]] = []
                    for offset in range(length):
                        generated_item = generated[start_g + offset]
                        source_item = source[start_s + offset]
                        match = compare_generated_to_historical(
                            generated_item["profile"], source_item,
                            generated_progress=float(generated_item.get("progress", 0.0)),
                            historical_progress=float(source_item.get("progress", 0.0)),
                            allow_mirror=allow_mirror, allow_rotation=allow_rotation,
                        )
                        mapping.append({
                            "generated_pass_id": generated_item.get("pass_id"),
                            "generated_order": int(generated_item.get("order", start_g + offset + 1)),
                            "source_pass_id": source_item.get("source_pass_id", source_item.get("pass_id")),
                            "source_order": int(source_item.get("inferred_order", start_s + offset)) + 1,
                            "overall_score": match["overall_score"],
                            "evidence_coverage": match.get("evidence_coverage"),
                            "mirror_used": match.get("mirror_used", False),
                            "rotation_used": match.get("rotation_used", False),
                            "components": match.get("components", {}),
                        })
                    scores = [float(item["overall_score"]) for item in mapping]
                    progress_consistency = sum(
                        max(0.0, 1.0 - abs(
                            float(generated[start_g + i].get("progress", 0.0))
                            - float(source[start_s + i].get("progress", 0.0))
                        )) for i in range(length)
                    ) / length
                    mean = sum(scores) / length
                    alignment = 0.60 * mean + 0.15 * min(scores) + 0.20 * (length / len(generated)) + 0.05 * progress_consistency
                    candidates.append({
                        "status": "SUPPORTED" if mean >= minimum_mean_similarity and alignment >= minimum_alignment_score else "INSUFFICIENT_HISTORICAL_SUBSEQUENCE_SUPPORT",
                        "source_flower_id": flower.get("flower_id"),
                        "generated_start_order": int(generated[start_g].get("order", start_g + 1)),
                        "generated_end_order": int(generated[start_g + length - 1].get("order", start_g + length)),
                        "source_start_order": int(source[start_s].get("inferred_order", start_s)) + 1,
                        "source_end_order": int(source[start_s + length - 1].get("inferred_order", start_s + length - 1)) + 1,
                        "matched_length": length,
                        "generated_coverage": length / len(generated),
                        "source_coverage": length / max(len(source), 1),
                        "alignment_score": alignment,
                        "mean_pass_similarity": mean,
                        "minimum_pass_similarity": min(scores),
                        "progression_consistency": progress_consistency,
                        "generated_pass_ids": [item.get("pass_id") for item in generated[start_g:start_g + length]],
                        "source_pass_ids": [item.get("source_pass_id", item.get("pass_id")) for item in source[start_s:start_s + length]],
                        "mapping": mapping,
                    })

    supported = [item for item in candidates if item["status"] == "SUPPORTED"]
    supported.sort(key=lambda item: (
        -item["alignment_score"], -item["matched_length"], -item["mean_pass_similarity"],
        -item["minimum_pass_similarity"], str(item["source_flower_id"]),
        item["source_start_order"], item["generated_start_order"],
    ))
    top = supported[:max(1, min(limit, 3))]
    if not top:
        return {"status": "INSUFFICIENT_HISTORICAL_SUBSEQUENCE_SUPPORT", "top_historical_subsequences": []}
    return {"status": "SUPPORTED", "best_historical_subsequence": top[0], "top_historical_subsequences": top}
