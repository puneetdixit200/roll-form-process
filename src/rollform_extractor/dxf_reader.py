from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import bbox
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
    xref_path: str | None = None


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
    xrefs: tuple[dict[str, str], ...]
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
            getattr(block.block_record.dxf, "xref_path", None),
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
        xrefs=tuple(
            {"name": block.name, "path": block.xref_path or ""}
            for block in blocks.values()
            if block.is_xref
        ),
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
    box = bbox.extents(doc.modelspace())
    if box.has_data:
        return BBox(box.extmin[0], box.extmin[1], box.extmax[0], box.extmax[1])
    extmin = doc.header.get("$EXTMIN")
    extmax = doc.header.get("$EXTMAX")
    if extmin is not None and extmax is not None:
        return BBox(float(extmin[0]), float(extmin[1]), float(extmax[0]), float(extmax[1]))
    return None


def _timestamp(doc: ezdxf.EzDxf, key: str) -> str | None:
    value = doc.header.get(key)
    return str(value) if value is not None else None


def _json_safe(value: Any) -> Any:
    if hasattr(value, "xyz"):
        return tuple(value.xyz)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
