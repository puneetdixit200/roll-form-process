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


def test_top_level_insert_record_has_its_own_transform():
    doc = ezdxf.new("R2013", setup=True)
    doc.blocks.new("PART").add_line((0, 0), (1, 0))
    doc.modelspace().add_blockref(
        "PART",
        (10, 20),
        dxfattribs={"rotation": 90, "xscale": 2, "yscale": 3},
    )

    insert = parse_entities(doc, ExtractionConfig.load()).entities[0]

    assert np.round(np.asarray(insert.transform.matrix_4x4), 6).tolist() == [
        [0.0, -3.0, 0.0, 10.0],
        [2.0, 0.0, 0.0, 20.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_expanded_entities_only_contains_insert_expansion():
    doc = ezdxf.new("R2013", setup=True)
    block = doc.blocks.new("PART")
    block.add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_line((5, 5), (6, 5))
    msp.add_blockref("PART", (0, 0))

    parsed = parse_entities(doc, ExtractionConfig.load())

    assert [entity.entity_type for entity in parsed.entities] == ["LINE", "INSERT"]
    assert [entity.entity_type for entity in parsed.expanded_entities] == ["LINE"]


def test_repeated_insert_expansion_gives_each_occurrence_a_unique_ledger_handle():
    doc = ezdxf.new("R2013", setup=True)
    block_line = doc.blocks.new("PART").add_line((0, 0), (1, 0))
    msp = doc.modelspace()
    msp.add_blockref("PART", (0, 0))
    msp.add_blockref("PART", (10, 0))

    expanded = parse_entities(doc, ExtractionConfig.load()).expanded_entities

    assert len({entity.handle for entity in expanded}) == 2
    assert {entity.source_handles for entity in expanded} == {(block_line.dxf.handle,)}
    assert {entity.original_primitives[0].source_handle for entity in expanded} == {block_line.dxf.handle}


def test_polyline_spline_hatch_text_and_dimension_keep_geometry_fields():
    doc = ezdxf.new("R2013", setup=True)
    msp = doc.modelspace()
    lw = msp.add_lwpolyline(
        [(0, 0, 0.5, 0.1, 0.2), (2, 0, 0.0, 0.3, 0.4)],
        format="xybse",
    )
    lw.closed = True
    poly = msp.add_polyline2d([(0, 0), (1, 0)])
    poly.close(True)
    spline = msp.add_rational_spline(
        [(0, 0), (1, 2), (3, 0)],
        weights=[1, 0.5, 1],
        degree=2,
        knots=[0, 0, 0, 1, 1, 1],
    )
    hatch = msp.add_hatch()
    path = hatch.paths.add_edge_path()
    path.add_line((0, 0), (1, 0))
    path.add_arc((1, 1), 1, 0, 90)
    text = msp.add_text("ST01", dxfattribs={"height": 2, "rotation": 15})
    text.set_placement((4, 5))
    mtext = msp.add_mtext("note", dxfattribs={"char_height": 3, "rotation": 25})
    mtext.set_location((6, 7))
    msp.add_linear_dim(base=(0, 1), p1=(0, 0), p2=(4, 0), angle=0).render()

    by_handle = {
        entity.handle: entity.original_primitive.attributes
        for entity in parse_entities(doc, ExtractionConfig.load()).entities
    }

    assert by_handle[lw.dxf.handle]["vertices"] == (
        {"point": (0.0, 0.0, 0.0), "bulge": 0.5, "start_width": 0.1, "end_width": 0.2},
        {"point": (2.0, 0.0, 0.0), "bulge": 0.0, "start_width": 0.3, "end_width": 0.4},
    )
    assert by_handle[lw.dxf.handle]["closed"] is True
    assert by_handle[poly.dxf.handle]["closed"] is True
    assert by_handle[spline.dxf.handle]["knots"] == (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    assert by_handle[spline.dxf.handle]["weights"] == (1.0, 0.5, 1.0)
    assert by_handle[hatch.dxf.handle]["paths"][0]["edges"][1]["kind"] == "ARC"
    assert by_handle[text.dxf.handle]["height"] == 2.0
    assert by_handle[mtext.dxf.handle]["rotation"] == 25.0
    dim_attrs = next(attrs for attrs in by_handle.values() if attrs.get("measurement") == 4.0)
    assert dim_attrs["defpoint2"] == (0.0, 0.0, 0.0)
    assert dim_attrs["defpoint3"] == (4.0, 0.0, 0.0)


def test_per_handle_bbox_and_normalization_failures_become_warnings(monkeypatch):
    doc = ezdxf.new("R2013", setup=True)
    line = doc.modelspace().add_line((0, 0), (1, 0))

    def fail_bbox(_entity):
        raise RuntimeError("bbox broke")

    def fail_normalize(*_args, **_kwargs):
        raise RuntimeError("normalize broke")

    monkeypatch.setattr("rollform_extractor.entity_parser._bbox_from_entity", fail_bbox)
    monkeypatch.setattr("rollform_extractor.entity_parser.normalize_primitives", fail_normalize)

    parsed = parse_entities(doc, ExtractionConfig.load())

    assert parsed.entities[0].handle == line.dxf.handle
    assert parsed.entities[0].bbox is None
    assert parsed.entities[0].normalized_primitives == ()
    assert {warning.code for warning in parsed.warnings} == {"bbox_failed", "normalization_failed"}
    assert all(warning.source_handles == (line.dxf.handle,) for warning in parsed.warnings)


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
