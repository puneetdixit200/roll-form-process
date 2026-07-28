from __future__ import annotations

import math

import ezdxf
import numpy as np
import pytest

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.entity_parser import parse_entities


@pytest.fixture
def drawing_with_entity():
    def build(entity_type: str):
        doc = ezdxf.new("R2013", setup=True)
        doc.header["$INSUNITS"] = 4
        doc.layers.add("PROFILE", color=3)
        msp = doc.modelspace()
        _add_entity(msp, entity_type)
        return doc

    return build


@pytest.mark.parametrize(
    "entity_type",
    [
        "LINE",
        "LWPOLYLINE",
        "POLYLINE",
        "ARC",
        "CIRCLE",
        "ELLIPSE",
        "SPLINE",
        "INSERT",
        "TEXT",
        "MTEXT",
        "DIMENSION",
        "HATCH",
        "POINT",
    ],
)
def test_supported_entity_retains_authoritative_primitive(entity_type, drawing_with_entity):
    parsed = parse_entities(drawing_with_entity(entity_type), ExtractionConfig.load())

    assert parsed.entities[0].original_primitive.kind == entity_type
    assert parsed.entities[0].original_dxf_attributes
    assert parsed.entities[0].original_primitives[0].attributes
    assert parsed.entities[0].normalized_primitives[0].kind == entity_type


def test_nested_insert_records_composed_mirror_rotation_and_scale():
    doc = ezdxf.new("R2013", setup=True)
    inner = doc.blocks.new("INNER")
    inner.add_line((0, 0), (2, 0))
    outer = doc.blocks.new("OUTER")
    outer.add_blockref(
        "INNER",
        (5, 0),
        dxfattribs={"rotation": 90, "xscale": -2, "yscale": 3},
    )
    doc.modelspace().add_blockref("OUTER", (10, 20), dxfattribs={"rotation": 30})

    entity = parse_entities(doc, ExtractionConfig.load()).expanded_entities[0]

    assert entity.transform.parent_block == "OUTER"
    assert entity.transform.block_path == ("OUTER", "INNER")
    assert np.asarray(entity.transform.matrix_4x4).shape == (4, 4)
    assert entity.transform.mirrored is True
    assert entity.original_primitive.kind == "LINE"
    assert entity.original_primitives[0].attributes["start"] == (0.0, 0.0, 0.0)


def test_unsupported_entity_keeps_ledger_and_warning():
    doc = ezdxf.new("R2013", setup=True)
    mesh = doc.modelspace().add_mesh()

    parsed = parse_entities(doc, ExtractionConfig.load())

    assert parsed.entities[0].handle == mesh.dxf.handle
    assert parsed.entities[0].entity_type == "MESH"
    assert parsed.entities[0].original_primitives == ()
    assert parsed.warnings[0].source_handles == (mesh.dxf.handle,)


def _add_entity(layout, entity_type: str) -> None:
    if entity_type == "LINE":
        layout.add_line((0, 0), (4, 0), dxfattribs={"layer": "PROFILE"})
    elif entity_type == "LWPOLYLINE":
        layout.add_lwpolyline([(0, 0), (2, 0), (2, 1)], dxfattribs={"layer": "PROFILE"})
    elif entity_type == "POLYLINE":
        layout.add_polyline3d([(0, 0, 0), (1, 1, 0)], dxfattribs={"layer": "PROFILE"})
    elif entity_type == "ARC":
        layout.add_arc((0, 0), 2, 0, 90, dxfattribs={"layer": "PROFILE"})
    elif entity_type == "CIRCLE":
        layout.add_circle((0, 0), 2, dxfattribs={"layer": "PROFILE"})
    elif entity_type == "ELLIPSE":
        layout.add_ellipse((0, 0), (3, 0), ratio=0.5, dxfattribs={"layer": "PROFILE"})
    elif entity_type == "SPLINE":
        layout.add_spline([(0, 0), (1, 2), (3, 0)], dxfattribs={"layer": "PROFILE"})
    elif entity_type == "INSERT":
        block = layout.doc.blocks.new("PART")
        block.add_line((0, 0), (1, 0))
        layout.add_blockref("PART", (0, 0), dxfattribs={"layer": "PROFILE"})
    elif entity_type == "TEXT":
        layout.add_text("ST01", dxfattribs={"layer": "PROFILE"}).set_placement((0, 0))
    elif entity_type == "MTEXT":
        layout.add_mtext("station", dxfattribs={"layer": "PROFILE"}).set_location((0, 0))
    elif entity_type == "DIMENSION":
        layout.add_linear_dim(base=(0, 1), p1=(0, 0), p2=(4, 0), angle=0).render()
    elif entity_type == "HATCH":
        hatch = layout.add_hatch(dxfattribs={"layer": "PROFILE"})
        hatch.paths.add_polyline_path([(0, 0), (1, 0), (1, 1)], is_closed=True)
    elif entity_type == "POINT":
        layout.add_point((1, 2), dxfattribs={"layer": "PROFILE"})
    else:
        raise AssertionError(entity_type)
