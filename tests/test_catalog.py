from __future__ import annotations

from rollform_extractor.catalog import (
    AssemblyInput,
    CatalogItem,
    CatalogThresholds,
    TemplateRecord,
    detect_assembly_template,
    match_occurrence,
)
from rollform_extractor.models import RollerOccurrenceRecord


def test_same_factory_id_links_occurrences_across_projects():
    catalog = (CatalogItem(roller_catalog_id=7, factory_id="FR-17"),)
    first = _occurrence("R1", factory_id="FR-17", drawing_id="D64-R1")
    second = _occurrence("R2", factory_id="FR-17", drawing_id="D65-R9")

    matches = [match_occurrence(item, catalog, _thresholds()) for item in (first, second)]

    assert [match.roller_catalog_id for match in matches] == [7, 7]
    assert [match.method for match in matches] == ["factory_id", "factory_id"]
    assert all(not match.manual_review_required for match in matches)


def test_unique_drawing_id_mapping_matches_before_fingerprint():
    catalog = (
        CatalogItem(roller_catalog_id=1, drawing_ids=("D64-R1",), fingerprint_hash="fp-other"),
        CatalogItem(roller_catalog_id=2, drawing_ids=("D64-R2",), fingerprint_hash="fp-1"),
    )
    occurrence = _occurrence("R1", drawing_id="D64-R1", fingerprint_hash="fp-1")

    match = match_occurrence(occurrence, catalog, _thresholds())

    assert match.roller_catalog_id == 1
    assert match.method == "drawing_id"


def test_exact_fingerprint_match_requires_unique_catalog_candidate():
    catalog = (
        CatalogItem(roller_catalog_id=3, fingerprint_hash="fp-1"),
        CatalogItem(roller_catalog_id=4, fingerprint_hash="fp-2"),
    )
    occurrence = _occurrence("R1", fingerprint_hash="fp-1")

    match = match_occurrence(occurrence, catalog, _thresholds())

    assert match.roller_catalog_id == 3
    assert match.method == "fingerprint"
    assert match.manual_review_required is False


def test_two_similar_catalog_candidates_require_manual_review():
    catalog = (
        CatalogItem(roller_catalog_id=10, geometry={"diameter": 50.0, "width": 18.0, "bore": 12.0}),
        CatalogItem(roller_catalog_id=11, geometry={"diameter": 50.1, "width": 18.0, "bore": 12.0}),
    )
    occurrence = _occurrence("R1", geometry={"diameter": 50.05, "width": 18.0, "bore": 12.0})

    match = match_occurrence(occurrence, catalog, _thresholds(similarity_tolerance=0.2))

    assert match.roller_catalog_id is None
    assert match.manual_review_required
    assert match.candidate_ids == (10, 11)


def test_catalog_match_carries_physical_inventory_fields_and_usage():
    catalog = (
        CatalogItem(
            roller_catalog_id=21,
            factory_id="FR-21",
            condition="usable",
            storage_location="Rack B",
            availability="in_stock",
        ),
    )
    occurrence = _occurrence("R21", factory_id="FR-21")

    match = match_occurrence(occurrence, catalog, _thresholds())

    assert match.roller_catalog_id == 21
    assert match.condition == "usable"
    assert match.storage_location == "Rack B"
    assert match.availability == "in_stock"
    assert match.usage == {"occurrence_id": "R21", "station_id": "S1", "role": "top"}


def test_matching_miss_requires_manual_review_without_claiming_identity():
    match = match_occurrence(_occurrence("R1", drawing_id="D64-R1"), (), _thresholds())

    assert match.roller_catalog_id is None
    assert match.manual_review_required
    assert match.method == "no_match"


def test_similarity_ignores_missing_dimensions_without_crashing():
    catalog = (CatalogItem(roller_catalog_id=31, geometry={"diameter": 50.0, "width": 18.0}),)
    occurrence = _occurrence("R1", geometry={"diameter": 50.0})

    match = match_occurrence(occurrence, catalog, _thresholds())

    assert match.roller_catalog_id is None
    assert match.manual_review_required


def test_similarity_matches_detector_dimension_aliases():
    catalog = (CatalogItem(roller_catalog_id=41, geometry={"diameter": 50.0, "width": 18.0, "bore": 12.0}),)
    occurrence = _occurrence(
        "R1",
        geometry={"outer_diameter_mm": 50.0, "width_mm": 18.0, "bore_diameter_mm": 12.0},
    )

    match = match_occurrence(occurrence, catalog, _thresholds())

    assert match.roller_catalog_id == 41
    assert match.method == "similarity"


def test_assembly_template_signature_deduplicates_repeated_layouts():
    existing = detect_assembly_template(
        _assembly("A1", (("top", 10.0, 13.0, 21), ("bottom", 10.0, -3.0, 22))),
        (),
    )
    repeated = detect_assembly_template(
        _assembly("A2", (("top", 10.0, 13.0, 21), ("bottom", 10.0, -3.0, 22))),
        (TemplateRecord(template_id=existing.template_id, signature_hash=existing.signature_hash, template=existing.template),),
    )

    assert repeated.template_id == existing.template_id
    assert repeated.signature_hash == existing.signature_hash
    assert repeated.created is False


def test_assembly_template_signature_changes_when_roles_or_catalog_ids_change():
    first = detect_assembly_template(_assembly("A1", (("top", 0.0, 8.0, 21),)), ())
    second = detect_assembly_template(_assembly("A2", (("guide", 0.0, 8.0, 21),)), ())
    third = detect_assembly_template(_assembly("A3", (("top", 0.0, 8.0, 99),)), ())

    assert first.signature_hash != second.signature_hash
    assert first.signature_hash != third.signature_hash


def test_assembly_template_signature_changes_when_position_changes():
    first = detect_assembly_template(_assembly("A1", (("top", 0.0, 8.0, 21, "entry"),)), ())
    second = detect_assembly_template(_assembly("A2", (("top", 0.0, 8.0, 21, "exit"),)), ())

    assert first.signature_hash != second.signature_hash
    assert first.template_id != second.template_id


def _occurrence(
    occurrence_id: str,
    *,
    factory_id: str | None = None,
    drawing_id: str | None = None,
    fingerprint_hash: str | None = None,
    geometry: dict[str, float] | None = None,
) -> RollerOccurrenceRecord:
    evidence = {
        "center": (10.0, 25.0),
        "outer_diameter": 50.0,
        "bore_diameter": 12.0,
        "width": 18.0,
    }
    if factory_id:
        evidence["factory_id"] = factory_id
    if drawing_id:
        evidence["drawing_id"] = drawing_id
    if fingerprint_hash:
        evidence["fingerprint_hash"] = fingerprint_hash
    if geometry:
        evidence["geometry"] = geometry
    return RollerOccurrenceRecord(
        occurrence_id=occurrence_id,
        station_id="S1",
        role="top",
        source_handles=(occurrence_id,),
        method="test",
        configuration_hash="cfg",
        confidence=0.9,
        evidence=evidence,
    )


def _assembly(assembly_id: str, members: tuple[tuple, ...]) -> AssemblyInput:
    return AssemblyInput(
        assembly_id=assembly_id,
        station_id="S1",
        profile_center=(10.0, 5.0),
        members=tuple(
            {
                "role": member[0],
                "center": (member[1], member[2]),
                "roller_catalog_id": member[3],
                "position": member[4] if len(member) > 4 else None,
                "source_handles": (member[0],),
                "note": "project-specific annotation",
            }
            for member in members
        ),
    )


def _thresholds(*, similarity_tolerance: float = 0.1) -> CatalogThresholds:
    return CatalogThresholds(similarity_tolerance=similarity_tolerance)
