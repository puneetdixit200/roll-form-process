from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any

from rollform_extractor.models import RollerOccurrenceRecord


@dataclass(frozen=True)
class CatalogThresholds:
    similarity_tolerance: float = 0.1


@dataclass(frozen=True)
class CatalogItem:
    roller_catalog_id: int
    factory_id: str | None = None
    drawing_ids: tuple[str, ...] = ()
    fingerprint_hash: str | None = None
    geometry: Mapping[str, float] | None = None
    condition: str | None = None
    storage_location: str | None = None
    availability: str | None = None


@dataclass(frozen=True)
class CatalogMatch:
    roller_catalog_id: int | None
    method: str
    confidence: float
    manual_review_required: bool
    candidate_ids: tuple[int, ...] = ()
    condition: str | None = None
    storage_location: str | None = None
    availability: str | None = None
    usage: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AssemblyInput:
    assembly_id: str
    station_id: str
    profile_center: tuple[float, float]
    members: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    signature_hash: str
    template: Mapping[str, Any]


@dataclass(frozen=True)
class TemplateMatch:
    template_id: str
    signature_hash: str
    template: Mapping[str, Any]
    created: bool


def match_occurrence(
    occurrence: RollerOccurrenceRecord,
    catalog: Sequence[CatalogItem],
    thresholds: CatalogThresholds,
) -> CatalogMatch:
    for method, matches in (
        ("factory_id", _factory_id_matches(occurrence, catalog)),
        ("drawing_id", _drawing_id_matches(occurrence, catalog)),
        ("fingerprint", _fingerprint_matches(occurrence, catalog)),
    ):
        if matches:
            return _resolved_or_review(occurrence, method, matches, confidence=1.0)

    similar = tuple(item for item in catalog if _similar(occurrence, item, thresholds.similarity_tolerance))
    if similar:
        return _resolved_or_review(occurrence, "similarity", similar, confidence=0.8)

    return CatalogMatch(None, "no_match", 0.0, True, usage=_usage(occurrence))


def detect_assembly_template(assembly: AssemblyInput, templates: Sequence[TemplateRecord]) -> TemplateMatch:
    template = _template_payload(assembly)
    signature_hash = sha256(json.dumps(template, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    for existing in templates:
        if existing.signature_hash == signature_hash:
            return TemplateMatch(existing.template_id, existing.signature_hash, existing.template, False)
    return TemplateMatch(f"Assembly_Template_AT-{signature_hash[:8]}", signature_hash, template, True)


def _resolved_or_review(
    occurrence: RollerOccurrenceRecord,
    method: str,
    matches: tuple[CatalogItem, ...],
    confidence: float,
) -> CatalogMatch:
    ids = tuple(item.roller_catalog_id for item in matches)
    if len(matches) != 1:
        return CatalogMatch(None, method, 0.0, True, ids, usage=_usage(occurrence))
    item = matches[0]
    return CatalogMatch(
        item.roller_catalog_id,
        method,
        confidence,
        False,
        ids,
        item.condition,
        item.storage_location,
        item.availability,
        _usage(occurrence),
    )


def _factory_id_matches(occurrence: RollerOccurrenceRecord, catalog: Sequence[CatalogItem]) -> tuple[CatalogItem, ...]:
    factory_id = occurrence.evidence.get("factory_id") or occurrence.evidence.get("permanent_id")
    if not factory_id:
        return ()
    return tuple(item for item in catalog if item.factory_id == factory_id)


def _drawing_id_matches(occurrence: RollerOccurrenceRecord, catalog: Sequence[CatalogItem]) -> tuple[CatalogItem, ...]:
    drawing_id = occurrence.evidence.get("drawing_id")
    if not drawing_id:
        return ()
    return tuple(item for item in catalog if drawing_id in item.drawing_ids)


def _fingerprint_matches(occurrence: RollerOccurrenceRecord, catalog: Sequence[CatalogItem]) -> tuple[CatalogItem, ...]:
    fingerprint_hash = occurrence.evidence.get("fingerprint_hash")
    if not fingerprint_hash:
        return ()
    return tuple(item for item in catalog if item.fingerprint_hash == fingerprint_hash)


def _similar(occurrence: RollerOccurrenceRecord, item: CatalogItem, tolerance: float) -> bool:
    actual = occurrence.evidence.get("geometry") or _occurrence_geometry(occurrence)
    expected = item.geometry or {}
    keys = tuple(key for key, value in expected.items() if value is not None)
    return bool(keys) and all(
        key in actual
        and actual[key] is not None
        and math.isclose(float(actual[key]), float(expected[key]), abs_tol=tolerance)
        for key in keys
    )


def _occurrence_geometry(occurrence: RollerOccurrenceRecord) -> Mapping[str, float]:
    evidence = occurrence.evidence
    return {
        "diameter": evidence.get("outer_diameter"),
        "outer_diameter": evidence.get("outer_diameter"),
        "width": evidence.get("width"),
        "bore": evidence.get("bore_diameter"),
        "bore_diameter": evidence.get("bore_diameter"),
    }


def _usage(occurrence: RollerOccurrenceRecord) -> Mapping[str, Any]:
    return {"occurrence_id": occurrence.occurrence_id, "station_id": occurrence.station_id, "role": occurrence.role}


def _template_payload(assembly: AssemblyInput) -> Mapping[str, Any]:
    px, py = assembly.profile_center
    return {
        "members": [
            {
                "role": member.get("role"),
                "relative_center": _relative_center(member.get("center", (0.0, 0.0)), px, py),
                "roller_catalog_id": member.get("roller_catalog_id"),
            }
            for member in assembly.members
        ]
    }


def _relative_center(center: Any, px: float, py: float) -> tuple[float, float]:
    x, y = center
    return (round(float(x) - px, 3), round(float(y) - py, 3))
