"""Explainable station-by-station roller *design* evidence.

The module deliberately ranks reusable design evidence, never physical assets
as the result. Inventory records are informational enrichment only.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping
from uuid import uuid4

from rollform_extractor.historical_source_traceability import source_reference_id


FLOWER_ROLLER_EVIDENCE_VERSION = "flower-roller-evidence-v3"
SAFETY_LIMITATION = "Design evidence only; not tooling approval or automatic physical-asset selection."


def _hash(value: Mapping[str, Any]) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _tier(item: Mapping[str, Any]) -> tuple[str, int]:
    confirmation = str(item.get("confirmation_status") or "").upper()
    direct = bool(item.get("source_occurrence_id") or item.get("occurrence_id"))
    recognition = float(item.get("recognition_score") or 0.0)
    if direct and confirmation in {"CONFIRMED", "ENGINEER_CONFIRMED"}:
        return "TIER_1_DIRECT_CONFIRMED_DRAWING_DESIGN", 1
    if direct and recognition:
        return "TIER_2_DIRECT_RECOGNIZED_DRAWING_DESIGN", 2
    if confirmation in {"CONFIRMED", "ENGINEER_CONFIRMED"}:
        return "TIER_3_CONFIRMED_HISTORICAL_USAGE_FROM_MATCHED_PASS", 3
    if recognition:
        return "TIER_4_HISTORICAL_RECOGNITION_CANDIDATE", 4
    if item.get("design_id"):
        return "TIER_5_INVENTORY_GEOMETRY_SIMILARITY", 5
    return "TIER_6_NO_SUPPORTED_DESIGN", 6


def _matches_for_pass(pass_payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    history = pass_payload.get("historical_match") or {}
    matches = list(history.get("top_matches") or [])
    if history.get("best_match") and history["best_match"] not in matches:
        matches.insert(0, history["best_match"])
    valid = [item for item in matches if item.get("source_flower_id") and item.get("source_pass_id")]
    result = []
    for rank, item in enumerate(valid, 1):
        enriched = dict(item)
        enriched.setdefault("match_rank", rank)
        result.append(enriched)
    return result


def _assets_for_design(inventory_assets: Mapping[str, Any], design_id: str) -> list[dict[str, Any]]:
    rows = inventory_assets.get(design_id, []) if isinstance(inventory_assets, Mapping) else []
    return [dict(item) for item in rows]


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _direct_records_for_pass(
    records: Iterable[Mapping[str, Any]],
    pass_payload: Mapping[str, Any],
    pass_count: int,
) -> list[Mapping[str, Any]]:
    """Map a generated pass to the nearest extracted project station.

    The project extraction and generated flower may have different station
    counts, so association uses normalized progression rather than assuming
    index equality. All roller roles/candidates from the nearest station are
    kept together.
    """
    records = [item for item in records if item.get("design_id")]
    if not records:
        return []
    progress = _number(pass_payload.get("progress"))
    if progress is None:
        order = max(1, int(pass_payload.get("order", 1)))
        progress = (order - 1) / max(pass_count - 1, 1)
    with_progress = [(item, _number(item.get("station_progress"))) for item in records]
    with_progress = [(item, value) for item, value in with_progress if value is not None]
    if not with_progress:
        return []
    minimum = min(abs(value - progress) for _, value in with_progress)
    return [item for item, value in with_progress if abs(abs(value - progress) - minimum) <= 1e-12]


def _candidate_item(
    record: Mapping[str, Any],
    *,
    historical_match: Mapping[str, Any] | None = None,
    direct: bool = False,
    dataset_hash: str = "UNCONFIGURED",
) -> dict[str, Any] | None:
    if not record.get("design_id"):
        return None
    tier, tier_order = _tier(record)
    recognition_status = str(record.get("recognition_status") or record.get("candidate_status") or "").upper()
    status = "AMBIGUOUS" if recognition_status == "AMBIGUOUS" else "SUPPORTED" if tier_order < 6 else "INSUFFICIENT_ROLLER_EVIDENCE"
    match = dict(historical_match or {})
    dataset_hash = str(match.get("dataset_hash") or record.get("dataset_hash") or dataset_hash)
    source_flower_id = match.get("source_flower_id") if match else record.get("flower_id")
    source_pass_id = match.get("source_pass_id") if match else record.get("pass_id")
    source_role = str(record.get("role") or "UNKNOWN")
    origin = {
        "origin_kind": "DIRECT_PROJECT" if direct else "HISTORICAL_MATCH",
        "source_reference_id": source_reference_id(
            dataset_hash, str(source_flower_id or "UNKNOWN"), str(source_pass_id or "UNKNOWN"),
            source_role, str(record["design_id"]), record.get("geometry_revision_id"),
        ),
        "source_flower_id": None if direct else source_flower_id,
        "source_pass_id": None if direct else source_pass_id,
        "source_project_id": record.get("source_project_id"),
        "source_occurrence_id": record.get("source_occurrence_id") or record.get("occurrence_id"),
        "source_station_id": record.get("station_id"),
        "match_rank": match.get("match_rank"),
        "evidence_tier": tier,
        "confirmation_status": record.get("confirmation_status"),
        "recognition_score": record.get("recognition_score"),
        "evidence_coverage": record.get("evidence_coverage"),
        "historical_similarity": match.get("overall_score") if match else None,
    }
    if direct:
        origin["source_reference_id"] = None
    warnings = sorted(set(record.get("quality_flags") or []))
    if status == "AMBIGUOUS" and "AMBIGUOUS_ROLLER_DESIGN" not in warnings:
        warnings.append("AMBIGUOUS_ROLLER_DESIGN")
    return {
        "design_id": str(record["design_id"]),
        "geometry_revision_id": record.get("geometry_revision_id"),
        "role": str(record.get("role") or "UNKNOWN"),
        "evidence_tier": tier,
        "_tier_order": tier_order,
        "evidence_status": status,
        "association_method": (
            "PROJECT_STATION_PROGRESS_ALIGNMENT"
            if direct
            else record.get("association_method") or "HISTORICAL_PASS_MATCH"
        ),
        "recognition_score": record.get("recognition_score"),
        "recognition_confidence": record.get("recognition_confidence"),
        "evidence_coverage": record.get("evidence_coverage"),
        "historical_pass_similarity": match.get("overall_score") if match else None,
        "confirmed_usage_count": int(record.get("confirmed_usage_count") or (1 if tier_order in {1, 3} else 0)),
        "distinct_historical_projects": int(record.get("distinct_project_count") or 0),
        "source_flower_id": source_flower_id,
        "source_pass_id": source_pass_id,
        "source_project_id": record.get("source_project_id"),
        "source_occurrence_id": record.get("source_occurrence_id") or record.get("occurrence_id"),
        "source_station_id": record.get("station_id"),
        "warnings": warnings,
        "supporting_origins": [origin],
        "best_support_origin": origin,
        "explanation": (
            {"direct_project_evidence": dict(record)}
            if direct
            else {"historical_match": match, "recorded_association": dict(record)}
        ),
    }


def build_candidate_roller_evidence(
    candidate: Mapping[str, Any],
    *,
    historical_dataset: Mapping[str, Any] | None = None,
    inventory_assets: Mapping[str, Any] | None = None,
    inventory_snapshot_hash: str = "UNCONFIGURED",
    direct_project_evidence: Iterable[Mapping[str, Any]] = (),
    direct_project_evidence_hash: str = "UNCONFIGURED",
) -> dict[str, Any]:
    """Build deterministic station evidence from direct and historical sources.

    Direct roller occurrences/recognition from the uploaded project outrank
    analogous historical usage. Historical station evidence remains useful when
    direct CAD evidence is absent. Weak or ambiguous evidence is preserved as
    reviewable evidence rather than promoted to an automatic tooling decision.
    """
    dataset = dict(historical_dataset or {})
    records = list(dataset.get("roller_station_evidence") or dataset.get("historical_roller_station_evidence") or [])
    direct_records = [dict(item) for item in direct_project_evidence]
    index: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        flower, pass_id = record.get("flower_id"), record.get("pass_id")
        if flower and pass_id:
            index[(str(flower), str(pass_id))].append(record)

    ordered_passes = sorted(
        candidate.get("passes") or [],
        key=lambda item: (int(item.get("order", 0)), str(item.get("pass_id", ""))),
    )
    stations: list[dict[str, Any]] = []
    for pass_payload in ordered_passes:
        historical = _matches_for_pass(pass_payload)
        raw: list[dict[str, Any]] = []
        direct_for_pass = _direct_records_for_pass(direct_records, pass_payload, len(ordered_passes))
        for record in direct_for_pass:
            item = _candidate_item(record, direct=True)
            if item:
                raw.append(item)
        for match in historical:
            for record in index[(str(match["source_flower_id"]), str(match["source_pass_id"]))]:
                item = _candidate_item(record, historical_match=match, dataset_hash=str(dataset.get("dataset_hash") or "UNCONFIGURED"))
                if item:
                    raw.append(item)

        grouped: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        for item in raw:
            key = (item["role"], item["design_id"], item["geometry_revision_id"])
            current = grouped.get(key)
            rank_key = (
                item["_tier_order"],
                -(item["recognition_score"] or 0.0),
                -(item["evidence_coverage"] or 0.0),
                -(item["historical_pass_similarity"] or 0.0),
                item["design_id"],
                item["geometry_revision_id"] or "",
            )
            if current is None:
                item["_rank_key"] = rank_key
                grouped[key] = item
            else:
                current["supporting_origins"].extend(item.get("supporting_origins", []))
                current["supporting_origins"] = sorted(
                    {_origin_key(origin): origin for origin in current["supporting_origins"]}.values(),
                    key=_origin_rank,
                )
                if rank_key < current["_rank_key"]:
                    item["supporting_origins"] = current["supporting_origins"]
                    item["_rank_key"] = rank_key
                    grouped[key] = item

        roles: list[dict[str, Any]] = []
        by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in grouped.values():
            by_role[item["role"]].append(item)
        for role in sorted(by_role):
            candidates = sorted(by_role[role], key=lambda item: item["_rank_key"])
            clean: list[dict[str, Any]] = []
            for rank, item in enumerate(candidates, 1):
                item = dict(item)
                item.pop("_tier_order", None)
                item.pop("_rank_key", None)
                item["rank"] = rank
                origins = item.get("supporting_origins") or []
                historical_match_ranks = {
                    int(origin["match_rank"])
                    for origin in origins
                    if origin.get("origin_kind") == "HISTORICAL_MATCH"
                    and origin.get("match_rank") in {1, 2, 3}
                }
                item["supporting_match_ranks"] = sorted(historical_match_ranks)
                item["top3_support_count"] = len(historical_match_ranks)
                item["best_support_origin"] = min(origins, key=_origin_rank) if origins else None
                item["inventory_assets"] = _assets_for_design(inventory_assets or {}, item["design_id"])
                item["known_asset_count"] = len(item["inventory_assets"])
                item["inventory_verification_status"] = (
                    "VERIFIED_ASSET_RECORDS_EXIST"
                    if any(asset.get("verified") for asset in item["inventory_assets"])
                    else "ASSET_RECORDS_EXIST"
                    if item["inventory_assets"]
                    else "NO_ASSET_RECORD"
                )
                item["limitations"] = [SAFETY_LIMITATION]
                clean.append(item)
            roles.append({"role": role, "candidates": clean})

        if direct_for_pass and historical:
            association = "DIRECT_PROJECT_STATION_AND_HISTORICAL_PASS"
        elif direct_for_pass:
            association = "PROJECT_STATION_PROGRESS_ALIGNMENT"
        elif raw:
            association = "HISTORICAL_PASS_MATCH"
        else:
            association = "UNRESOLVED"
        statuses = {candidate_item.get("evidence_status") for role in roles for candidate_item in role["candidates"]}
        station_status = "AMBIGUOUS" if "AMBIGUOUS" in statuses and statuses <= {"AMBIGUOUS"} else "SUPPORTED" if roles else "INSUFFICIENT_ROLLER_EVIDENCE"
        stations.append(
            {
                "station_index": int(pass_payload.get("order", 0)),
                "pass_id": pass_payload.get("pass_id"),
                "status": station_status,
                "association_method": association,
                "roles": roles,
                "warnings": [] if roles else ["INSUFFICIENT_EVIDENCE_ENGINEER_REVIEW_REQUIRED"],
            }
        )

    payload = {
        "schema_version": 1,
        "algorithm_version": FLOWER_ROLLER_EVIDENCE_VERSION,
        "candidate_id": candidate.get("candidate_id"),
        "historical_dataset_hash": dataset.get("dataset_hash", "UNCONFIGURED"),
        "inventory_snapshot_hash": inventory_snapshot_hash,
        "direct_project_evidence_hash": direct_project_evidence_hash,
        "stations": stations,
        "manufacturing_approval": "NOT_APPROVED",
        "physical_asset_assignment": False,
        "safety_boundary": SAFETY_LIMITATION,
    }
    return payload | {"evidence_bundle_hash": _hash(payload)}


def _origin_rank(origin: Mapping[str, Any]) -> tuple[Any, ...]:
    confirmed = str(origin.get("confirmation_status") or "").upper() in {"CONFIRMED", "ENGINEER_CONFIRMED"}
    try:
        match_rank = int(origin.get("match_rank"))
    except (TypeError, ValueError):
        match_rank = 999999
    return (
        {"TIER_1_DIRECT_CONFIRMED_DRAWING_DESIGN": 1, "TIER_2_DIRECT_RECOGNIZED_DRAWING_DESIGN": 2, "TIER_3_CONFIRMED_HISTORICAL_USAGE_FROM_MATCHED_PASS": 3, "TIER_4_HISTORICAL_RECOGNITION_CANDIDATE": 4, "TIER_5_INVENTORY_GEOMETRY_SIMILARITY": 5}.get(str(origin.get("evidence_tier") or ""), 6),
        0 if confirmed else 1,
        match_rank,
        -float(origin.get("recognition_score") or 0.0),
        -float(origin.get("evidence_coverage") or 0.0),
        -float(origin.get("historical_similarity") or 0.0),
        str(origin.get("source_flower_id") or ""),
        str(origin.get("source_pass_id") or ""),
        str(origin.get("source_reference_id") or ""),
    )


def _origin_key(origin: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        origin.get("origin_kind"), origin.get("source_flower_id"), origin.get("source_pass_id"),
        origin.get("source_project_id"), origin.get("source_occurrence_id"), origin.get("source_station_id"),
        origin.get("evidence_tier"),
    )


REVIEW_DECISIONS = {"ACCEPT_DESIGN_EVIDENCE", "REJECT_DESIGN_EVIDENCE", "NEEDS_REVIEW"}


def create_roller_evidence_review(
    engine: Any,
    candidate_id: str,
    pass_id: str,
    role: str,
    decision: str,
    reviewer: str,
    notes: str = "",
    *,
    selected_design_id: str | None = None,
    selected_revision_id: str | None = None,
    selected_source_reference_id: str | None = None,
) -> dict[str, Any]:
    """Append one validated review event for a station/role evidence snapshot."""
    if decision not in REVIEW_DECISIONS:
        raise ValueError("invalid roller evidence review decision")
    reviewer = reviewer.strip()
    role = role.strip() or "UNKNOWN"
    if not reviewer:
        raise ValueError("reviewer is required")

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from rollform_extractor.database import VisualFlowerCandidateRow, VisualFlowerRollerEvidenceReviewRow

    with Session(engine) as session, session.begin():
        candidate = session.scalar(select(VisualFlowerCandidateRow).where(VisualFlowerCandidateRow.candidate_id == candidate_id))
        if candidate is None:
            raise LookupError("visual candidate not found")
        evidence = (candidate.candidate_json or {}).get("roller_evidence") or {}
        station = next((item for item in evidence.get("stations", []) if item.get("pass_id") == pass_id), None)
        if station is None:
            raise LookupError("roller evidence pass not found")
        role_evidence = next((item for item in station.get("roles", []) if str(item.get("role") or "UNKNOWN") == role), None)
        if role_evidence is None:
            raise LookupError("roller evidence role not found")

        candidates = list(role_evidence.get("candidates") or [])
        selected: Mapping[str, Any] | None = None
        if selected_design_id:
            matches = [
                item for item in candidates
                if str(item.get("design_id")) == str(selected_design_id)
                and (selected_revision_id is None or str(item.get("geometry_revision_id") or "") == str(selected_revision_id))
            ]
            if not matches:
                raise ValueError("selected roller design is not a candidate for this station role")
            selected = matches[0]
        elif decision != "NEEDS_REVIEW":
            if len(candidates) != 1:
                raise ValueError("ambiguous roller evidence review requires selected_design_id")
            selected = candidates[0]

        if selected is not None:
            selected_design_id = str(selected.get("design_id"))
            selected_revision_id = selected.get("geometry_revision_id")
        elif selected_revision_id is not None:
            raise ValueError("selected_revision_id requires selected_design_id")
        if selected_source_reference_id:
            origins = (selected or {}).get("supporting_origins", []) if selected else []
            selected_origin = next((origin for origin in origins if origin.get("source_reference_id") == selected_source_reference_id), None)
            if selected_origin is None:
                raise ValueError("INVALID_SELECTED_HISTORICAL_SOURCE")
        else:
            selected_origin = (selected or {}).get("best_support_origin") if selected else None

        review_id = "vfr-" + uuid4().hex[:20]
        row = VisualFlowerRollerEvidenceReviewRow(
            review_id=review_id,
            candidate_id=candidate_id,
            pass_id=pass_id,
            role=role,
            decision=decision,
            selected_design_id=selected_design_id,
            selected_revision_id=selected_revision_id,
            reviewer=reviewer,
            notes=notes,
            evidence_bundle_hash=evidence.get("evidence_bundle_hash"),
            selected_source_reference_id=(selected_origin or {}).get("source_reference_id"),
            selected_source_flower_id=(selected_origin or {}).get("source_flower_id"),
            selected_source_pass_id=(selected_origin or {}).get("source_pass_id"),
            selected_source_match_rank=(selected_origin or {}).get("match_rank"),
        )
        session.add(row)
        session.flush()
        return {
            "review_id": review_id,
            "candidate_id": candidate_id,
            "pass_id": pass_id,
            "role": role,
            "decision": decision,
            "reviewer": reviewer,
            "selected_design_id": selected_design_id,
            "selected_revision_id": selected_revision_id,
            "selected_source_reference_id": (selected_origin or {}).get("source_reference_id"),
            "evidence_bundle_hash": evidence.get("evidence_bundle_hash"),
            "manufacturing_approval": "NOT_APPROVED",
        }
