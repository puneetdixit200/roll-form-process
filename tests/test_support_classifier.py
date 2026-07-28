from __future__ import annotations

from dataclasses import replace

import ezdxf

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.support_classifier import classify_support


def test_paperspace_and_dimensions_are_marked_not_removed(tmp_path):
    dxf_path = tmp_path / "support.dxf"
    doc = ezdxf.new("R2013", setup=True)
    doc.layers.add("CENTER", linetype="CENTER")
    doc.layers.add("HIDDEN", linetype="HIDDEN")
    doc.layers.add("TITLE", color=2)
    doc.layers.add("BORDER", color=5)
    doc.layers.add("PART", color=3)
    doc.layers.get("HIDDEN").off()
    msp = doc.modelspace()
    profile = msp.add_line((0, 0), (20, 0), dxfattribs={"layer": "PART"})
    dim = msp.add_linear_dim(base=(0, 4), p1=(0, 0), p2=(20, 0), angle=0)
    dim.render()
    msp.add_text("NOTE: DEBURR").set_placement((0, 10))
    msp.add_line((0, 0), (20, 0), dxfattribs={"layer": "CENTER", "linetype": "CENTER"})
    msp.add_circle((8, 8), 2, dxfattribs={"layer": "HIDDEN"})
    msp.add_lwpolyline(
        [(-100, -50), (100, -50), (100, 50), (-100, 50)],
        close=True,
        dxfattribs={"layer": "BORDER"},
    )
    msp.add_lwpolyline(
        [(70, -40), (98, -40), (98, -10), (70, -10)],
        close=True,
        dxfattribs={"layer": "TITLE"},
    )
    msp.add_text("REV A").set_placement((72, -20))
    doc.layouts.new("SHEET1").add_text("paper").set_placement((0, 0))
    doc.saveas(dxf_path)

    parsed = parse_entities(doc, ExtractionConfig.load())
    inspection = inspect_drawing(dxf_path)

    result = classify_support(parsed.entities, inspection, ExtractionConfig.load())

    assert len(result.entities) == len(parsed.entities)
    by_handle = {entity.handle: entity for entity in result.entities}
    assert by_handle[profile.dxf.handle].classification == "drawing_geometry"
    support = [entity for entity in result.entities if entity.classification == "drawing_support"]
    assert support
    assert all(entity.support_evidence for entity in support)
    assert all(0.0 < entity.support_confidence <= 1.0 for entity in support)
    assert any("entity_type:DIMENSION" in entity.support_evidence for entity in support)
    assert any("paper_space" in entity.support_evidence for entity in support)
    assert any("linetype:CENTER" in entity.support_evidence for entity in support)
    assert any("hidden_layer:HIDDEN" in entity.support_evidence for entity in support)
    assert any("border_extent" in entity.support_evidence for entity in support)
    assert any("title_or_revision_text" in entity.support_evidence for entity in support)


def test_support_marks_table_density_without_dropping_geometry(tmp_path):
    dxf_path = tmp_path / "table.dxf"
    doc = ezdxf.new("R2013", setup=True)
    doc.layers.add("TABLE")
    msp = doc.modelspace()
    part = msp.add_circle((0, 0), 5)
    for x in range(6):
        msp.add_line((50 + x * 4, 50), (50 + x * 4, 70), dxfattribs={"layer": "TABLE"})
    for y in range(6):
        msp.add_line((50, 50 + y * 4), (70, 50 + y * 4), dxfattribs={"layer": "TABLE"})
    for i in range(4):
        msp.add_text(f"CELL {i}").set_placement((52, 52 + i * 4))
    doc.saveas(dxf_path)

    parsed = parse_entities(doc, ExtractionConfig.load())
    inspection = inspect_drawing(dxf_path)

    result = classify_support(parsed.entities, inspection, ExtractionConfig.load())

    assert len(result.entities) == len(parsed.entities)
    assert next(entity for entity in result.entities if entity.handle == part.dxf.handle).classification == "drawing_geometry"
    assert any(
        entity.classification == "drawing_support" and "table_or_grid_density" in entity.support_evidence
        for entity in result.entities
    )


def test_classification_is_reversible_entity_copy():
    doc = ezdxf.new("R2013", setup=True)
    dim = doc.modelspace().add_linear_dim(base=(0, 1), p1=(0, 0), p2=(4, 0), angle=0)
    dim.render()
    parsed = parse_entities(doc, ExtractionConfig.load())
    inspection = replace(
        inspect_drawing(_save_doc(doc)),
        path="memory",
    )

    result = classify_support(parsed.entities, inspection, ExtractionConfig.load())

    assert result.entities[0].handle == parsed.entities[0].handle
    assert result.entities[0].original_primitives == parsed.entities[0].original_primitives
    assert result.entities[0].attributes["support_classification"]["classification"] == "drawing_support"


def _save_doc(doc):
    from tempfile import NamedTemporaryFile

    handle = NamedTemporaryFile(suffix=".dxf", delete=False)
    handle.close()
    doc.saveas(handle.name)
    return handle.name
