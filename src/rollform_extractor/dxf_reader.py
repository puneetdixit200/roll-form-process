from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import units

from rollform_extractor.models import BBox


@dataclass(frozen=True)
class LayerInspection:
    name: str
    color: int
    linetype: str
    entity_count: int


@dataclass(frozen=True)
class BlockInspection:
    name: str
    entity_count: int
    is_xref: bool


@dataclass(frozen=True)
class LayoutInspection:
    name: str
    entity_count: int
    is_modelspace: bool


@dataclass(frozen=True)
class DrawingInspection:
    path: str
    header: dict[str, Any]
    units: str | None
    layers: dict[str, LayerInspection]
    linetypes: tuple[str, ...]
    blocks: dict[str, BlockInspection]
    layouts: dict[str, LayoutInspection]
    xrefs: tuple[str, ...]
    extents: BBox | None
    created: str | None
    updated: str | None
    modelspace_entity_count: int
    paperspace_entity_count: int
    insert_count: int
    text_count: int
    dimension_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_drawing(dxf_path: Path) -> DrawingInspection:
    doc = ezdxf.readfile(dxf_path)
    layouts = {
        layout.name: LayoutInspection(
            layout.name,
            sum(1 for _ in layout),
            layout.name.lower() == "model",
        )
        for layout in doc.layouts
    }
    layer_counts = _layer_counts(doc)
    blocks = {
        block.name: BlockInspection(
            block.name,
            len(block),
            bool(getattr(block.block_record.dxf, "xref_path", "")),
        )
        for block in doc.blocks
        if not block.name.startswith("*")
    }
    entity_types = [entity.dxftype() for layout in doc.layouts for entity in layout]
    return DrawingInspection(
        path=str(dxf_path),
        header=_header(doc),
        units=units.unit_name(doc.header.get("$INSUNITS", 0)),
        layers={
            layer.dxf.name: LayerInspection(
                layer.dxf.name,
                layer.dxf.color,
                layer.dxf.linetype,
                layer_counts.get(layer.dxf.name, 0),
            )
            for layer in doc.layers
        },
        linetypes=tuple(linetype.dxf.name for linetype in doc.linetypes),
        blocks=blocks,
        layouts=layouts,
        xrefs=tuple(block.name for block in blocks.values() if block.is_xref),
        extents=_extents(doc),
        created=_timestamp(doc, "$TDCREATE"),
        updated=_timestamp(doc, "$TDUPDATE"),
        modelspace_entity_count=layouts.get("Model", LayoutInspection("Model", 0, True)).entity_count,
        paperspace_entity_count=sum(
            layout.entity_count for layout in layouts.values() if not layout.is_modelspace
        ),
        insert_count=entity_types.count("INSERT"),
        text_count=entity_types.count("TEXT") + entity_types.count("MTEXT"),
        dimension_count=entity_types.count("DIMENSION"),
    )


def _header(doc: ezdxf.EzDxf) -> dict[str, Any]:
    keys = ("$ACADVER", "$INSUNITS", "$EXTMIN", "$EXTMAX", "$LIMMIN", "$LIMMAX")
    return {key: _json_safe(doc.header.get(key)) for key in keys if key in doc.header}


def _layer_counts(doc: ezdxf.EzDxf) -> dict[str, int]:
    counts: dict[str, int] = {}
    for layout in doc.layouts:
        for entity in layout:
            layer = entity.dxf.layer
            counts[layer] = counts.get(layer, 0) + 1
    return counts


def _extents(doc: ezdxf.EzDxf) -> BBox | None:
    points: list[tuple[float, float]] = []
    for entity in doc.modelspace():
        points.extend(_entity_points(entity))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def _entity_points(entity: Any) -> list[tuple[float, float]]:
    dxftype = entity.dxftype()
    if dxftype == "LINE":
        return [_xy(entity.dxf.start), _xy(entity.dxf.end)]
    if dxftype == "INSERT":
        return [_xy(entity.dxf.insert)]
    if dxftype == "CIRCLE":
        center = _xy(entity.dxf.center)
        radius = float(entity.dxf.radius)
        return [
            (center[0] - radius, center[1] - radius),
            (center[0] + radius, center[1] + radius),
        ]
    if dxftype in {"TEXT", "MTEXT"}:
        return [_xy(entity.dxf.insert)]
    return []


def _xy(value: Any) -> tuple[float, float]:
    return (float(value[0]), float(value[1]))


def _timestamp(doc: ezdxf.EzDxf, key: str) -> str | None:
    value = doc.header.get(key)
    return str(value) if value is not None else None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "xyz"):
        return tuple(value.xyz)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
