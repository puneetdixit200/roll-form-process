"""Explainable visual profile comparison metrics."""

from __future__ import annotations

import math


DEFAULT_VISUAL_WEIGHTS = {"point_rms_similarity": .25, "chamfer_similarity": .20, "tangent_similarity": .15, "curvature_similarity": .15, "corner_signature_similarity": .10, "aspect_ratio_similarity": .05, "topology_compatibility": .05, "sequence_progress_similarity": .05}


def compare_profiles(left: dict, right: dict, *, left_progress: float | None = None, right_progress: float | None = None, weights: dict[str, float] | None = None) -> dict:
    weights = weights or DEFAULT_VISUAL_WEIGHTS
    lp, rp = tuple(tuple(p) for p in left.get("points", ())), tuple(tuple(p) for p in right.get("points", ()))
    topology = left.get("topology") == right.get("topology")
    rms = _rms(lp, rp)
    chamfer = _chamfer(lp, rp)
    hausdorff = _hausdorff(lp, rp)
    aspect = _similarity(left.get("aspect_ratio"), right.get("aspect_ratio"))
    tangent = _tangent_similarity(lp, rp)
    corners = _corner_similarity(lp, rp)
    progress = None if left_progress is None or right_progress is None else max(0.0, 1.0 - abs(left_progress - right_progress))
    components = {
        "point_rms_similarity": (max(0.0, min(1.0, 1.0 - rms)), rms),
        "chamfer_similarity": (max(0.0, min(1.0, 1.0 - chamfer)), chamfer),
        "tangent_similarity": (tangent, None),
        "curvature_similarity": (corners, None),
        "corner_signature_similarity": (corners, None),
        "aspect_ratio_similarity": (aspect, None),
        "topology_compatibility": (1.0 if topology else 0.0, None),
        "sequence_progress_similarity": (progress, None),
    }
    available = {name: (score is not None and (name != "topology_compatibility" or topology)) for name, (score, _) in components.items()}
    total_weight = sum(weights.get(name, 0.0) for name, enabled in available.items() if enabled)
    score = sum((components[name][0] or 0.0) * weights.get(name, 0.0) for name, enabled in available.items() if enabled) / total_weight if total_weight else 0.0
    return {"overall_score": max(0.0, min(1.0, score)), "evidence_coverage": total_weight / sum(weights.values()), "components": {name: {"score": value, "weight": weights.get(name, 0.0), "available": available[name], "raw": raw} for name, (value, raw) in components.items()}, "hausdorff": hausdorff, "topology_match": topology}


def _rms(left, right):
    if not left or not right:
        return 1.0
    n = min(len(left), len(right))
    return math.sqrt(sum((left[i][0] - right[i][0]) ** 2 + (left[i][1] - right[i][1]) ** 2 for i in range(n)) / n)


def _chamfer(left, right):
    if not left or not right:
        return 1.0
    left = left[::4] or left
    right = right[::4] or right
    def one(a, b):
        return sum(min(math.hypot(x - u, y - v) for u, v in b) for x, y in a) / len(a)
    return min(1.0, (one(left, right) + one(right, left)) / 2.0)


def _hausdorff(left, right):
    if not left or not right:
        return 1.0
    left = left[::4] or left
    right = right[::4] or right
    return max(max(min(math.hypot(x - u, y - v) for u, v in right) for x, y in left), max(min(math.hypot(x - u, y - v) for x, y in left) for u, v in right))


def _tangent_similarity(left, right):
    if len(left) < 2 or len(right) < 2:
        return None
    n = min(len(left) - 1, len(right) - 1)
    values = []
    for i in range(n):
        a = math.atan2(left[i + 1][1] - left[i][1], left[i + 1][0] - left[i][0])
        b = math.atan2(right[i + 1][1] - right[i][1], right[i + 1][0] - right[i][0])
        delta = abs((a - b + math.pi) % (2 * math.pi) - math.pi)
        values.append(1.0 - delta / math.pi)
    return sum(values) / len(values)


def _corner_similarity(left, right):
    if len(left) < 3 or len(right) < 3:
        return None
    def turns(points):
        values = []
        for a, b, c in zip(points, points[1:], points[2:]):
            u = math.atan2(b[1] - a[1], b[0] - a[0]); v = math.atan2(c[1] - b[1], c[0] - b[0])
            values.append(abs((v - u + math.pi) % (2 * math.pi) - math.pi))
        return values
    a, b = turns(left), turns(right)
    n = min(len(a), len(b))
    return max(0.0, 1.0 - sum(abs(a[i] - b[i]) for i in range(n)) / max(1, n * math.pi))


def _similarity(left, right):
    if left is None or right is None:
        return None
    return max(0.0, min(1.0, 1.0 - abs(float(left) - float(right)) / max(abs(float(left)), abs(float(right)), 1e-9)))
