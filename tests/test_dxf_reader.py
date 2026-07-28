from __future__ import annotations

import json

import ezdxf
import pytest

from rollform_extractor.dxf_reader import inspect_drawing
from tests.cad_factory import write_sample_dxf


@pytest.fixture
def sample_dxf(tmp_path):
    return write_sample_dxf(tmp_path / "part.dxf")


def test_inspect_drawing_reports_layers_blocks_layouts_units_and_extents(sample_dxf):
    inspection = inspect_drawing(sample_dxf)

    assert inspection.units == "Millimeters"
    assert "PROFILE" in inspection.layers
    assert inspection.layers["EMPTY"].entity_count == 0
    assert "ROLLER" in inspection.blocks
    assert inspection.blocks["ROLLER"].entity_count == 1
    assert inspection.layouts["Model"].entity_count == 3
    assert inspection.layouts["CHECKS"].entity_count == 1
    assert inspection.modelspace_entity_count == 3
    assert inspection.paperspace_entity_count == 1
    assert inspection.extents.min_x == 1
    assert inspection.extents.min_y == 2
    assert inspection.extents.max_x == 12
    assert inspection.extents.max_y == 22
    assert inspection.text_count == 2
    assert inspection.insert_count == 1


def test_inspection_is_json_safe(sample_dxf):
    inspection = inspect_drawing(sample_dxf)

    json.dumps(inspection.to_dict())


def test_extents_use_ezdxf_bbox_for_non_line_entities(tmp_path):
    dxf_path = tmp_path / "arc.dxf"
    write_sample_dxf(dxf_path)
    doc = ezdxf.readfile(dxf_path)
    doc.modelspace().add_arc(center=(-5, -6), radius=2, start_angle=0, end_angle=90)
    doc.saveas(dxf_path)

    inspection = inspect_drawing(dxf_path)

    assert inspection.extents.min_x == -5
    assert inspection.extents.min_y == -6
