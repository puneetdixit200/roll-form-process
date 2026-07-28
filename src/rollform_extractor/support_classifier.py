from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from rollform_extractor.dxf_reader import DrawingInspection
from rollform_extractor.models import BBox, CadEntityRecord


@dataclass(frozen=True)
class ClassifiedEntityRecord:
    source: CadEntityRecord
    classification: str
    support_evidence: tuple[str, ...] = ()
    support_confidence: float = 0.0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.source, name)

    @property
    def attributes(self) -> Mapping[str, Any]:
        return {
            **dict(self.source.attributes),
            "support_classification": {
                "classification": self.classification,
                "evidence": self.support_evidence,
                "confidence": self.support_confidence,
            },
        }


@dataclass(frozen=True)
class SupportClassification:
    entities: tuple[ClassifiedEntityRecord, ...]
    method: str
    configuration_hash: str


def classify_support(
    entities: Iterable[CadEntityRecord], inspection: DrawingInspection, config
) -> SupportClassification:
    records = tuple(entities)
    drawing_bounds = _bounds(entity.bbox for entity in records if entity.layout.lower() == "model")
    table_handles = _table_handles(records)
    classified = tuple(
        _classify(entity, inspection, drawing_bounds, table_handles)
        for entity in records
    )
    return SupportClassification(
        entities=classified,
        method="support_classifier",
        configuration_hash=config.hash_for("support_classification"),
    )


def _classify(
    entity: CadEntityRecord,
    inspection: DrawingInspection,
    drawing_bounds: BBox | None,
    table_handles: set[str],
) -> ClassifiedEntityRecord:
    evidence: list[str] = []
    text = _entity_text(entity)
    layer = entity.layer.upper()
    layer_info = inspection.layers.get(entity.layer)
    linetype = (entity.line_type or (layer_info.linetype if layer_info else "") or "").upper()

    layout_info = inspection.layouts.get(entity.layout)
    if not layout_info.is_modelspace if layout_info else entity.layout.lower() != "model":
        evidence.append("paper_space")
    if entity.entity_type == "DIMENSION":
        evidence.append("entity_type:DIMENSION")
    if entity.entity_type in {"TEXT", "MTEXT"} and _support_text(text):
        evidence.append("title_or_revision_text")
    if any(token in layer for token in ("NOTE", "TEXT", "TITLE", "BORDER", "FRAME", "REV", "LOGO", "TABLE")):
        evidence.append(f"layer:{entity.layer}")
    if any(token in layer for token in ("CENTER", "CENTRE", "CONSTRUCTION")):
        evidence.append(f"construction_layer:{entity.layer}")
    if any(token in linetype for token in ("CENTER", "CENTRE", "DASH", "HIDDEN", "PHANTOM")):
        evidence.append(f"linetype:{linetype}")
    if _hidden_layer(entity, inspection):
        evidence.append(f"hidden_layer:{entity.layer}")
    if entity.handle in table_handles:
        evidence.append("table_or_grid_density")
    if _is_border(entity, drawing_bounds):
        evidence.append("border_extent")

    confidence = min(1.0, 0.45 + 0.15 * len(evidence)) if evidence else 0.0
    return ClassifiedEntityRecord(
        source=entity,
        classification="drawing_support" if evidence else "drawing_geometry",
        support_evidence=tuple(dict.fromkeys(evidence)),
        support_confidence=confidence,
    )


def _hidden_layer(entity: CadEntityRecord, inspection: DrawingInspection) -> bool:
    layer = inspection.layers.get(entity.layer)
    return bool(layer and layer.color < 0)


def _support_text(text: str) -> bool:
    upper = text.upper()
    return any(
        token in upper
        for token in ("NOTE", "DRAWING", "REV", "SCALE", "MATERIAL", "TITLE", "PART NO", "DATE", "SHEET")
    )


def _entity_text(entity: CadEntityRecord) -> str:
    if "text" in entity.attributes:
        return str(entity.attributes["text"])
    if entity.original_primitives and "text" in entity.original_primitive.attributes:
        return str(entity.original_primitive.attributes["text"])
    return ""


def _is_border(entity: CadEntityRecord, drawing_bounds: BBox | None) -> bool:
    if drawing_bounds is None or entity.bbox is None:
        return False
    if entity.entity_type not in {"LWPOLYLINE", "POLYLINE", "LINE"}:
        return False
    width = drawing_bounds.max_x - drawing_bounds.min_x
    height = drawing_bounds.max_y - drawing_bounds.min_y
    if width <= 0 or height <= 0:
        return False
    entity_width = entity.bbox.max_x - entity.bbox.min_x
    entity_height = entity.bbox.max_y - entity.bbox.min_y
    covers_width = entity_width >= width * 0.75
    covers_height = entity_height >= height * 0.75
    near_edge = entity.bbox.min_x <= drawing_bounds.min_x + width * 0.08 or entity.bbox.max_x >= drawing_bounds.max_x - width * 0.08
    return covers_width and covers_height and near_edge


def _table_handles(entities: tuple[CadEntityRecord, ...]) -> set[str]:
    tableish = [
        entity for entity in entities
        if _has_table_evidence(entity)
    ]
    if len(tableish) < 8:
        return set()
    bounds = _bounds(entity.bbox for entity in tableish)
    if bounds is None:
        return set()
    area = max((bounds.max_x - bounds.min_x) * (bounds.max_y - bounds.min_y), 1.0)
    return {entity.handle for entity in tableish} if len(tableish) / area > 0.01 else set()


def _has_table_evidence(entity: CadEntityRecord) -> bool:
    layer = entity.layer.upper()
    text = _entity_text(entity).upper()
    return (
        "TABLE" in layer
        or "GRID" in layer
        or "TITLE" in layer
        or any(token in text for token in ("REV", "DRAWING", "SHEET", "CELL", "TABLE"))
    )


def _bounds(boxes: Iterable[BBox | None]) -> BBox | None:
    present = tuple(box for box in boxes if box is not None)
    if not present:
        return None
    return BBox(
        min(box.min_x for box in present),
        min(box.min_y for box in present),
        max(box.max_x for box in present),
        max(box.max_y for box in present),
    )
