"""Deterministic contiguous historical pass matching."""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def best_contiguous_subsequence(
    generated_passes: Iterable[Mapping[str, Any]],
    historical_flowers: Iterable[Mapping[str, Any]],
    *,
    minimum_length: int = 2,
) -> dict[str, Any] | None:
    generated = list(generated_passes)
    best: dict[str, Any] | None = None
    for flower in sorted(historical_flowers, key=lambda item: str(item.get("flower_id", ""))):
        source = sorted(flower.get("passes", []), key=lambda item: (int(item.get("inferred_order", 0)), str(item.get("pass_id", ""))))
        for length in range(min(len(generated), len(source)), minimum_length - 1, -1):
            for start_g in range(0, len(generated) - length + 1):
                for start_s in range(0, len(source) - length + 1):
                    mapping = []
                    for offset in range(length):
                        score = _similarity(generated[start_g + offset].get("shape_vector", []), source[start_s + offset].get("shape_vector", []))
                        mapping.append({"generated_pass_id": generated[start_g + offset].get("pass_id"), "source_pass_id": source[start_s + offset].get("pass_id"), "similarity": round(score, 8)})
                    scores = [item["similarity"] for item in mapping]
                    candidate = {"source_flower_id": flower.get("flower_id"), "generated_start_order": start_g + 1, "generated_end_order": start_g + length, "source_start_order": int(source[start_s].get("inferred_order", start_s)) + 1, "source_end_order": int(source[start_s + length - 1].get("inferred_order", start_s + length - 1)) + 1, "generated_pass_ids": [item.get("pass_id") for item in generated[start_g:start_g + length]], "source_pass_ids": [item.get("pass_id") for item in source[start_s:start_s + length]], "alignment_score": round(sum(scores) / len(scores), 8), "mean_pass_similarity": round(sum(scores) / len(scores), 8), "minimum_pass_similarity": round(min(scores), 8), "mapping": mapping}
                    key = (candidate["alignment_score"], candidate["mean_pass_similarity"], -length, str(candidate["source_flower_id"]), -candidate["source_start_order"], -candidate["generated_start_order"])
                    if best is None or key > best["_key"]:
                        candidate["_key"] = key
                        best = candidate
    if best is None:
        return None
    best.pop("_key", None)
    return best


def _similarity(left: Any, right: Any) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    rms = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) / len(left))
    return max(0.0, min(1.0, 1.0 - rms / max(1.0, math.sqrt(len(left)))))
