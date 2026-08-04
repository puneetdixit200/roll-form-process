"""Backend-owned visual sketch generation and historical matching."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any

from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_metrics import compare_profiles
from rollform_extractor.visual_profile_schema import VISUAL_ALGORITHM_VERSION, VisualProfile


def generate_visual_candidates(profile: VisualProfile, historical_flowers: list[dict[str, Any]], *, station_mode: str = "AUTOMATIC", exact_station_count: int | None = None, minimum_station_count: int = 8, maximum_station_count: int = 28, candidate_limit: int = 3, allow_mirror_matching: bool = True, allow_rotation_alignment: bool = False) -> dict[str, Any]:
    minimum_station_count = _station(minimum_station_count); maximum_station_count = _station(maximum_station_count)
    if exact_station_count is not None:
        counts = [_station(exact_station_count)]
    elif station_mode == "RANGE":
        counts = list(dict.fromkeys([minimum_station_count, _nearest_count(historical_flowers), maximum_station_count]))
    else:
        counts = [_nearest_count(historical_flowers)]
    target = canonicalize_profile(profile, samples=256)
    histories = _historical_passes(historical_flowers)
    if not histories:
        return {"schema_version": 1, "algorithm_version": VISUAL_ALGORITHM_VERSION, "target_id": profile.profile_id, "station_counts": counts, "candidate_count": 0, "candidates": [], "warnings": ["NO_HISTORICAL_SUPPORT", "VISUAL_ONLY_NOT_MANUFACTURING_VALIDATION"]}
    retrieval = sorted((_match(target, item, 1.0, allow_mirror_matching, allow_rotation_alignment) for item in histories), key=lambda x: (-x["overall_score"], x["source_flower_id"], x["source_pass_id"]))
    candidates = []
    candidate_counts = counts if len(counts) > 1 else [counts[0]] * min(candidate_limit, 3)
    for index, count in enumerate(candidate_counts[:candidate_limit]):
        style = ("UNIFORM_PROGRESSION", "HISTORICAL_TEMPLATE_001", "HISTORICAL_TEMPLATE_002")[min(index, 2)]
        candidates.append(_candidate(profile, target, histories, retrieval, count, style, index + 1))
    return {"schema_version": 1, "algorithm_version": VISUAL_ALGORITHM_VERSION, "target_id": profile.profile_id, "station_counts": counts, "candidate_count": len(candidates), "candidates": candidates, "warnings": ["VISUAL_ONLY_NOT_MANUFACTURING_VALIDATION", "HISTORICAL_DATASET_CONTAINS_TWO_PRIVATE_FLOWERS"]}


def _candidate(profile, target, histories, retrieval, count, style, rank):
    generated = []
    for index in range(count):
        progress = index / max(count - 1, 1)
        points = _progress_points(target["points"], progress, profile.topology, style)
        if index == count - 1:
            points = target["points"]
        canonical = {**target, "points": [list(p) for p in points]}
        matches = sorted((_match(canonical, item, progress, True, False) for item in histories), key=lambda x: (-x["overall_score"], x["source_flower_id"], x["source_pass_id"]))[:3]
        best = matches[0] if matches else None
        support = "DIRECT_HISTORICAL_TEMPLATE" if best and best["overall_score"] >= .9 else "GENERIC_VISUAL_INTERPOLATION" if style == "UNIFORM_PROGRESSION" else "WARPED_HISTORICAL_TEMPLATE"
        warnings = [] if best and best["overall_score"] >= .35 else ["NO_HISTORICAL_SUPPORT"]
        confidence = _pass_confidence(best, support, warnings)
        generated.append({"pass_id": f"visual-{rank:02d}-{index + 1:03d}", "order": index + 1, "progress": round(progress, 8), "profile": {"points": [list(p) for p in points], "topology": profile.topology}, "generation": {"mode": "VISUAL_SKETCH_V1", "candidate_style": style, "algorithm_version": VISUAL_ALGORITHM_VERSION, "source_flower_ids": [item["source_flower_id"] for item in matches], "source_pass_ids": [item["source_pass_id"] for item in matches], "transformation": {"progress": progress, "support": support}}, "historical_match": {"best_match": best, "top_matches": matches}, "visual_confidence": confidence, "warnings": warnings})
    values = [item["visual_confidence"]["score"] for item in generated]
    smoothness = _smoothness(generated)
    overall = round(max(0.0, min(100.0, .45 * (sum(values) / len(values)) + .20 * min(values) + .15 * (generated[-1]["visual_confidence"]["score"]) + .10 * smoothness + .10 * (sum(1 for item in generated if item["historical_match"]["best_match"]) / len(generated) * 100))), 4)
    return {"candidate_id": "vfg-" + sha256(f"{profile.profile_id}|{count}|{style}".encode()).hexdigest()[:16], "candidate_style": style, "station_count": count, "status": "VISUAL_CLOSED_TEMPLATE_MORPH" if profile.topology == "CLOSED_CONTOUR" else "VISUAL_OPEN_PROGRESSION", "visual_confidence": {"score": overall, "band": _band(overall), "mean_pass_confidence": round(sum(values) / len(values), 4), "minimum_pass_confidence": round(min(values), 4), "progression_smoothness": smoothness, "non_calibrated": True}, "passes": generated, "warnings": ["VISUAL_ONLY_NOT_MANUFACTURING_VALIDATION"], "source_flower_ids": sorted({item["source_flower_id"] for item in retrieval[:2]}), "provenance": {"algorithm_version": VISUAL_ALGORITHM_VERSION, "profile_id": profile.profile_id}}


def _progress_points(target_points, progress, topology, style):
    points = tuple((float(p[0]), float(p[1])) for p in target_points)
    if topology == "CLOSED_CONTOUR":
        return tuple((round(x * (.85 + .15 * progress), 8), round(y * (.85 + .15 * progress), 8)) for x, y in points)
    n = len(points); flat = tuple((index / max(n - 1, 1) * 2.0 - 1.0, 0.0) for index in range(n))
    easing = progress if style == "UNIFORM_PROGRESSION" else 3 * progress * progress - 2 * progress * progress * progress
    return tuple((round(flat[i][0] * (1 - easing) + points[i][0] * easing, 8), round(flat[i][1] * (1 - easing) + points[i][1] * easing, 8)) for i in range(n))


def _historical_passes(flowers):
    items = []
    for flower in flowers:
        passes = flower.get("passes", [])
        for index, item in enumerate(passes):
            vector = item.get("shape_vector", [])
            points = [vector[i:i + 2] for i in range(0, len(vector), 2)]
            if points:
                items.append({"source_flower_id": flower.get("flower_id"), "source_pass_id": item.get("pass_id"), "progress": index / max(len(passes) - 1, 1), "profile": {"points": points, "topology": item.get("topology", flower.get("topology")), "aspect_ratio": float(item.get("width", 1)) / max(float(item.get("height", 1)), 1e-9)}})
    return items


def _match(target, historical, progress, allow_mirror, allow_rotation):
    variants = [historical["profile"]]
    if allow_mirror:
        points = historical["profile"]["points"]
        variants.append({**historical["profile"], "points": [[-p[0], p[1]] for p in points]})
    matches = []
    for mirrored, variant in enumerate(variants):
        result = compare_profiles(target, variant, left_progress=progress, right_progress=historical["progress"])
        result.update({"source_flower_id": historical["source_flower_id"], "source_pass_id": historical["source_pass_id"], "mirror_used": bool(mirrored), "rotation_used": False, "alignment": "CANONICAL"})
        matches.append(result)
    return max(matches, key=lambda x: (x["overall_score"], not x["mirror_used"]))


def _pass_confidence(match, support, warnings):
    raw = (match["overall_score"] if match else 0.0)
    coverage = match["evidence_coverage"] if match else 0.0
    support_factor = {"DIRECT_HISTORICAL_TEMPLATE": 1.0, "WARPED_HISTORICAL_TEMPLATE": .9, "GENERIC_VISUAL_INTERPOLATION": .75}.get(support, .6)
    penalty = .8 ** len(warnings)
    score = max(0.0, min(100.0, 100 * raw * (.5 + .5 * coverage) * support_factor * penalty))
    return {"score": round(score, 4), "band": _band(score), "raw_match": raw, "evidence_coverage": coverage, "support_factor": support_factor, "warning_penalty": penalty, "non_calibrated": True}


def _smoothness(passes):
    if len(passes) < 3: return 100.0
    jumps = []
    for left, right in zip(passes, passes[1:]):
        a, b = left["profile"]["points"], right["profile"]["points"]
        jumps.append(math.sqrt(sum((x[0] - y[0]) ** 2 + (x[1] - y[1]) ** 2 for x, y in zip(a, b)) / max(1, len(a))))
    mean = sum(jumps) / len(jumps)
    value = 100 * (1.0 - min(1.0, max(jumps) / max(mean * 2.5, 1e-9)))
    return round(max(0.0, min(100.0, value)), 4)


def _band(score):
    return "STRONG_VISUAL_SUPPORT" if score >= 85 else "MODERATE_VISUAL_SUPPORT" if score >= 70 else "WEAK_VISUAL_SUPPORT" if score >= 50 else "INSUFFICIENT_VISUAL_SUPPORT"


def _station(value):
    return min(28, max(8, int(value)))


def _nearest_count(flowers):
    counts = [len(item.get("passes", [])) for item in flowers if item.get("passes")]
    return _station(round(sum(counts) / len(counts))) if counts else 8
