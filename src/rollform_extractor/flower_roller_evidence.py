"""Explainable station-by-station roller *design* evidence.

The module deliberately ranks reusable design evidence, never physical assets
as the result.  Inventory records are informational enrichment only.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


FLOWER_ROLLER_EVIDENCE_VERSION = "flower-roller-evidence-v1"
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
    return [item for item in matches if item.get("source_flower_id") and item.get("source_pass_id")]


def _assets_for_design(inventory_assets: Mapping[str, Any], design_id: str) -> list[dict[str, Any]]:
    rows = inventory_assets.get(design_id, []) if isinstance(inventory_assets, Mapping) else []
    return [dict(item) for item in rows]


def build_candidate_roller_evidence(
    candidate: Mapping[str, Any],
    *,
    historical_dataset: Mapping[str, Any] | None = None,
    inventory_assets: Mapping[str, Any] | None = None,
    inventory_snapshot_hash: str = "UNCONFIGURED",
) -> dict[str, Any]:
    """Build a deterministic evidence snapshot from historical pass links.

    Dataset evidence may be imported from a reviewed historical source using
    ``roller_station_evidence``.  Entries without a defensible pass link are
    intentionally ignored.
    """
    dataset = dict(historical_dataset or {})
    records = list(dataset.get("roller_station_evidence") or dataset.get("historical_roller_station_evidence") or [])
    index: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        flower, pass_id = record.get("flower_id"), record.get("pass_id")
        if flower and pass_id:
            index[(str(flower), str(pass_id))].append(record)
    stations: list[dict[str, Any]] = []
    for pass_payload in sorted(candidate.get("passes") or [], key=lambda item: (int(item.get("order", 0)), str(item.get("pass_id", "")))):
        historical = _matches_for_pass(pass_payload)
        raw: list[dict[str, Any]] = []
        for match in historical:
            similarity = match.get("overall_score")
            for record in index[(str(match["source_flower_id"]), str(match["source_pass_id"]))]:
                if not record.get("design_id"):
                    continue
                tier, tier_order = _tier(record)
                raw.append({
                    "design_id": str(record["design_id"]),
                    "geometry_revision_id": record.get("geometry_revision_id"),
                    "role": str(record.get("role") or "UNKNOWN"),
                    "evidence_tier": tier,
                    "_tier_order": tier_order,
                    "evidence_status": "SUPPORTED" if tier_order < 6 else "INSUFFICIENT_ROLLER_EVIDENCE",
                    "association_method": record.get("association_method") or "HISTORICAL_PASS_MATCH",
                    "recognition_score": record.get("recognition_score"),
                    "recognition_confidence": record.get("recognition_confidence"),
                    "evidence_coverage": record.get("evidence_coverage"),
                    "historical_pass_similarity": similarity,
                    "confirmed_usage_count": int(record.get("confirmed_usage_count") or (1 if tier_order <= 3 else 0)),
                    "distinct_historical_projects": int(record.get("distinct_project_count") or 0),
                    "source_flower_id": match["source_flower_id"],
                    "source_pass_id": match["source_pass_id"],
                    "source_project_id": record.get("source_project_id"),
                    "source_occurrence_id": record.get("source_occurrence_id") or record.get("occurrence_id"),
                    "warnings": sorted(set(record.get("quality_flags") or [])),
                    "explanation": {"historical_match": dict(match), "recorded_association": dict(record)},
                })
        grouped: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        for item in raw:
            key = (item["role"], item["design_id"], item["geometry_revision_id"])
            current = grouped.get(key)
            rank_key = (item["_tier_order"], -(item["recognition_score"] or 0.0), -(item["evidence_coverage"] or 0.0), -(item["historical_pass_similarity"] or 0.0), item["design_id"], item["geometry_revision_id"] or "")
            if current is None or rank_key < current["_rank_key"]:
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
                item.pop("_tier_order", None); item.pop("_rank_key", None)
                item["rank"] = rank
                item["inventory_assets"] = _assets_for_design(inventory_assets or {}, item["design_id"])
                item["known_asset_count"] = len(item["inventory_assets"])
                item["inventory_verification_status"] = "VERIFIED_ASSET_RECORDS_EXIST" if any(asset.get("verified") for asset in item["inventory_assets"]) else "ASSET_RECORDS_EXIST" if item["inventory_assets"] else "NO_ASSET_RECORD"
                item["limitations"] = [SAFETY_LIMITATION]
                clean.append(item)
            roles.append({"role": role, "candidates": clean})
        stations.append({
            "station_index": int(pass_payload.get("order", 0)), "pass_id": pass_payload.get("pass_id"),
            "status": "SUPPORTED" if roles else "INSUFFICIENT_ROLLER_EVIDENCE",
            "association_method": "HISTORICAL_PASS_MATCH" if raw else "UNRESOLVED",
            "roles": roles,
            "warnings": [] if roles else ["INSUFFICIENT_EVIDENCE_ENGINEER_REVIEW_REQUIRED"],
        })
    payload = {"schema_version": 1, "algorithm_version": FLOWER_ROLLER_EVIDENCE_VERSION, "candidate_id": candidate.get("candidate_id"), "historical_dataset_hash": dataset.get("dataset_hash", "UNCONFIGURED"), "inventory_snapshot_hash": inventory_snapshot_hash, "stations": stations, "manufacturing_approval": "NOT_APPROVED", "physical_asset_assignment": False, "safety_boundary": SAFETY_LIMITATION}
    return payload | {"evidence_bundle_hash": _hash(payload)}
