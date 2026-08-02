"""Deterministic global alignment of canonical passes to drawing stations.

This module deliberately has no report concerns.  It preserves repeated
station occurrences and chooses a monotonic sequence globally rather than
selecting the first visually similar candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class AlignmentCandidate:
    composite_flower_id: str
    pass_id: str
    profile_id: str
    pass_order: int
    candidate_profile_id: str | None
    candidate_station_id: str | None
    candidate_sequence_id: str | None
    candidate_station_order: int | None
    geometry_similarity: float | None = None
    shape_similarity: float | None = None
    developed_length_difference: float | None = None
    bend_signature_difference: float | None = None
    profile_type_compatible: bool | None = None
    units_status: str = "UNCONFIRMED"
    evidence_coverage: float = 0.0
    quality_flags: tuple[str, ...] = ()

    @property
    def score(self) -> float:
        weighted = 0.0
        available_weight = 0.0
        if self.geometry_similarity is not None:
            weighted += float(self.geometry_similarity) * 0.40
            available_weight += 0.40
        if self.shape_similarity is not None:
            weighted += float(self.shape_similarity) * 0.25
            available_weight += 0.25
        if self.developed_length_difference is not None:
            weighted += max(0.0, 1.0 - abs(float(self.developed_length_difference))) * 0.15
            available_weight += 0.15
        if self.bend_signature_difference is not None:
            weighted += max(0.0, 1.0 - abs(float(self.bend_signature_difference))) * 0.10
            available_weight += 0.10
        if self.profile_type_compatible is not None:
            weighted += (1.0 if self.profile_type_compatible else 0.0) * 0.10
            available_weight += 0.10
        return max(0.0, min(1.0, weighted / available_weight if available_weight else 0.0))


@dataclass(frozen=True)
class AlignmentResult:
    matches: tuple[AlignmentCandidate, ...]
    unmatched_pass_ids: tuple[str, ...]
    unmatched_station_ids: tuple[str, ...]
    total_score: float
    status: str
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": [candidate.__dict__ | {"score": candidate.score} for candidate in self.matches],
            "unmatched_pass_ids": list(self.unmatched_pass_ids),
            "unmatched_station_ids": list(self.unmatched_station_ids),
            "total_score": self.total_score,
            "status": self.status,
            "diagnostics": list(self.diagnostics),
        }


def build_alignment_candidates(rows: Iterable[dict[str, Any]]) -> tuple[AlignmentCandidate, ...]:
    return tuple(
        AlignmentCandidate(
            composite_flower_id=str(row.get("composite_flower_id", "")),
            pass_id=str(row.get("pass_id", "")),
            profile_id=str(row.get("profile_id", "")),
            pass_order=int(row.get("pass_order", row.get("inferred_order", 0))),
            candidate_profile_id=row.get("candidate_profile_id", row.get("individual_profile_id")),
            candidate_station_id=row.get("candidate_station_id", row.get("station_id")),
            candidate_sequence_id=row.get("candidate_sequence_id", row.get("sequence_id")),
            candidate_station_order=row.get("candidate_station_order", row.get("inferred_station_order")),
            geometry_similarity=row.get("geometry_similarity", row.get("similarity_score")),
            shape_similarity=row.get("shape_similarity"),
            developed_length_difference=row.get("developed_length_difference"),
            bend_signature_difference=row.get("bend_signature_difference"),
            profile_type_compatible=row.get("profile_type_compatible"),
            units_status=str(row.get("units_status", "UNCONFIRMED")),
            evidence_coverage=float(row.get("evidence_coverage", 0.0)),
            quality_flags=tuple(row.get("quality_flags", ())),
        )
        for row in rows
    )


def align_passes_to_stations(
    pass_ids: Iterable[str],
    station_ids: Iterable[str],
    candidates: Iterable[AlignmentCandidate],
    *,
    gap_penalty: float = 0.30,
    order_violation_penalty: float = 2.0,
    minimum_pair_score: float = 0.40,
) -> AlignmentResult:
    passes = tuple(pass_ids)
    stations = tuple(station_ids)
    by_pass: dict[str, list[AlignmentCandidate]] = {pass_id: [] for pass_id in passes}
    for candidate in candidates:
        if candidate.pass_id in by_pass and candidate.candidate_station_id in stations:
            by_pass[candidate.pass_id].append(candidate)
    for values in by_pass.values():
        values.sort(key=lambda c: (-c.score, -(c.evidence_coverage), c.candidate_station_order if c.candidate_station_order is not None else 10**9, c.candidate_station_id or "", c.candidate_profile_id or ""))

    # Dynamic programming over pass order and station occurrence order.  A
    # station ID is not deduplicated: S14/S15/S16 remain three positions.
    n, m = len(passes), len(stations)
    dp: list[list[tuple[float, tuple[AlignmentCandidate, ...], tuple[str, ...], tuple[str, ...]] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = (0.0, (), (), ())
    for i in range(n + 1):
        for j in range(m + 1):
            state = dp[i][j]
            if state is None:
                continue
            score, matches, gaps_p, gaps_s = state
            if i < n:
                _update(dp, i + 1, j, (score - gap_penalty, matches, gaps_p + (passes[i],), gaps_s), _state_key)
            if j < m:
                _update(dp, i, j + 1, (score - gap_penalty, matches, gaps_p, gaps_s + (stations[j],)), _state_key)
            if i >= n or j >= m:
                continue
            station = stations[j]
            for candidate in by_pass.get(passes[i], ()):
                if candidate.candidate_station_id != station:
                    continue
                if candidate.score < minimum_pair_score:
                    continue
                candidate_order = candidate.candidate_station_order
                if candidate_order is not None and candidate_order != j:
                    # The station tuple is the authoritative occurrence order.
                    continue
                _update(dp, i + 1, j + 1, (score + candidate.score, matches + (candidate,), gaps_p, gaps_s), _state_key)
    final = dp[n][m]
    if final is None:
        return AlignmentResult((), passes, stations, 0.0, "REVIEW_REQUIRED", ("no monotonic alignment exists",))
    score, matches, gaps_p, gaps_s = final
    status = "CONFIRMED" if matches and not gaps_p and not gaps_s else "REVIEW_REQUIRED"
    return AlignmentResult(matches, gaps_p, gaps_s, score, status, ())


def _state_key(state):
    score, matches, gaps_p, gaps_s = state
    tie = tuple((c.candidate_station_order if c.candidate_station_order is not None else 10**9, c.candidate_station_id or "", c.profile_id, c.pass_id) for c in matches)
    return (score, -len(gaps_p) - len(gaps_s), tuple(-x if isinstance(x, int) else x for x in ()), tuple(reversed(tie)))


def _update(dp, i, j, candidate, key):
    existing = dp[i][j]
    if existing is None or key(candidate) > key(existing):
        dp[i][j] = candidate


def validate_alignment(result: AlignmentResult) -> tuple[str, ...]:
    issues = []
    orders = [candidate.candidate_station_order for candidate in result.matches if candidate.candidate_station_order is not None]
    if orders != sorted(orders) or len(orders) != len(set(orders)):
        issues.append("alignment is not monotonic")
    if any(candidate.candidate_station_id is None for candidate in result.matches):
        issues.append("alignment contains a missing station")
    return tuple(issues)
