"""Deterministic variable-length alignment for historical flower passes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from rollform_extractor.flower_prototype_dataset import HistoricalFlower, HistoricalPass


@dataclass(frozen=True)
class PassAlignment:
    source_pass_id: str | None
    target_pass_id: str | None
    source_order: int | None
    target_order: int | None
    cost: float
    evidence: dict[str, float | str | None]


@dataclass(frozen=True)
class FlowerAlignment:
    source_flower_id: str
    target_flower_id: str
    pairs: tuple[PassAlignment, ...]
    total_cost: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_flower_id": self.source_flower_id,
            "target_flower_id": self.target_flower_id,
            "total_cost": self.total_cost,
            "status": self.status,
            "pairs": [pair.__dict__ for pair in self.pairs],
        }


def align_flowers(source: HistoricalFlower, target: HistoricalFlower) -> FlowerAlignment:
    left, right = source.passes, target.passes
    n, m = len(left), len(right)
    dp: list[list[tuple[float, tuple[PassAlignment, ...]] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = (0.0, ())
    for i in range(n + 1):
        for j in range(m + 1):
            state = dp[i][j]
            if state is None:
                continue
            cost, pairs = state
            if i < n:
                _update(dp, i + 1, j, (cost + 0.45, pairs + (_gap(left[i], None),)))
            if j < m:
                _update(dp, i, j + 1, (cost + 0.45, pairs + (_gap(None, right[j]),)))
            if i < n and j < m:
                pair = _pair(left[i], right[j], n, m)
                _update(dp, i + 1, j + 1, (cost + pair.cost, pairs + (pair,)))
    result = dp[n][m]
    if result is None:
        return FlowerAlignment(source.flower_id, target.flower_id, (), float("inf"), "REVIEW_REQUIRED")
    cost, pairs = result
    return FlowerAlignment(source.flower_id, target.flower_id, pairs, cost, "PASS_WITH_WARNINGS" if any(pair.source_pass_id is None or pair.target_pass_id is None for pair in pairs) else "ALIGNED")


def _pair(source: HistoricalPass, target: HistoricalPass, source_count: int, target_count: int) -> PassAlignment:
    shape = _rms(source.shape_vector, target.shape_vector)
    progress = abs(
        source.inferred_order / max(source_count - 1, 1)
        - target.inferred_order / max(target_count - 1, 1)
    )
    width = _relative_distance(source.width, target.width)
    height = _relative_distance(source.height, target.height)
    bend = abs(source.bend_count - target.bend_count) / max(1, source.bend_count, target.bend_count)
    cost = 0.55 * min(1.0, shape / 2.0) + 0.15 * min(1.0, width) + 0.15 * min(1.0, height) + 0.10 * bend + 0.05 * min(1.0, progress / 10.0)
    return PassAlignment(source.pass_id, target.pass_id, source.inferred_order, target.inferred_order, cost, {"shape_rms": shape, "width_relative_error": width, "height_relative_error": height, "bend_count_error": bend})


def _gap(source: HistoricalPass | None, target: HistoricalPass | None) -> PassAlignment:
    return PassAlignment(source.pass_id if source else None, target.pass_id if target else None, source.inferred_order if source else None, target.inferred_order if target else None, 0.45, {"gap": "SOURCE" if target is None else "TARGET"})


def _update(dp, i: int, j: int, value: tuple[float, tuple[PassAlignment, ...]]) -> None:
    previous = dp[i][j]
    if previous is None or _state_key(value) < _state_key(previous):
        dp[i][j] = value


def _state_key(value) -> tuple[Any, ...]:
    cost, pairs = value
    return (round(cost, 12), len(pairs), tuple((pair.source_order if pair.source_order is not None else 10**9, pair.target_order if pair.target_order is not None else 10**9, pair.source_pass_id or "", pair.target_pass_id or "") for pair in pairs))


def _rms(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 2.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left))


def _relative_distance(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1e-9)
