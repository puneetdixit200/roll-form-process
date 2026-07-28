from __future__ import annotations

import ezdxf
import pytest

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.station_detector import detect_stations


@pytest.mark.parametrize("count", [8, 12, 15, 16, 18, 20])
def test_station_count_is_derived_from_labels_and_geometry(tmp_path, count):
    doc = make_flower_dxf(station_count=count, labels=True)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == count
    assert [station.sequence_index for station in result.stations] == list(range(1, count + 1))
    assert result.manual_review_required is False


def test_repeated_insert_blocks_define_unlabelled_stations(tmp_path):
    doc = make_flower_dxf(station_count=10, labels=False, blocks=True)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 10
    assert all(station.evidence["candidate_method"] == "block_repetition" for station in result.stations)
    assert all(station.manual_review_required for station in result.stations)


def test_labelled_repeated_station_blocks_keep_unique_insert_handles(tmp_path):
    doc = make_flower_dxf(station_count=5, labels=True, blocks=True)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 5
    assert all(station.evidence["candidate_method"] == "block_repetition" for station in result.stations)
    assert len({station.source_handles[0] for station in result.stations}) == 5


def test_partial_labels_on_repeated_station_blocks_keep_all_inserts_for_review(tmp_path):
    doc = make_flower_dxf(station_count=5, labels=False, blocks=True)
    for index, number in enumerate((1, 2, 4, 5)):
        doc.modelspace().add_text(f"ST{number:02d}", dxfattribs={"layer": "PROFILE", "height": 2}).set_placement((index * 40, 14))
    parsed = parse_entities(doc, ExtractionConfig.load())

    result = _detect_parsed(tmp_path, doc, parsed)

    expanded_handles = {entity.handle for entity in parsed.expanded_entities}
    assert len(result.stations) == 5
    assert all(station.evidence["candidate_method"] == "block_repetition" for station in result.stations)
    assert all(not expanded_handles.intersection(station.source_handles) for station in result.stations)
    assert any(station.drawing_label.startswith("Station_Unknown_") for station in result.stations)
    assert result.manual_review_required is True


def test_labelled_geometry_wins_over_repeated_nonstation_blocks(tmp_path):
    doc = make_flower_dxf(station_count=6, labels=True)
    fastener = doc.blocks.new("FASTENER")
    fastener.add_circle((0, 0), radius=1, dxfattribs={"layer": "PROFILE"})
    for index in range(3):
        doc.modelspace().add_blockref("FASTENER", (500 + index * 8, 80), dxfattribs={"layer": "PROFILE"})

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 6
    assert all(station.evidence["candidate_method"] == "geometry_cluster" for station in result.stations)


def test_unlabelled_multirow_layout_uses_unknown_labels_and_review(tmp_path):
    doc = make_flower_dxf(station_count=12, labels=False, rows=3)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 12
    assert all(station.drawing_label.startswith("Station_Unknown_") for station in result.stations)
    assert all(station.manual_review_required for station in result.stations)


def test_reversed_numeric_labels_drive_sequence_order(tmp_path):
    doc = make_flower_dxf(station_count=6, labels=True, reversed_labels=True)

    result = _detect(tmp_path, doc)

    assert [station.drawing_label for station in result.stations] == [f"ST{i:02d}" for i in range(1, 7)]
    assert [station.sequence_index for station in result.stations] == list(range(1, 7))


def test_partial_numeric_labels_preserve_known_sequence_and_request_review(tmp_path):
    doc = make_flower_dxf(station_count=4, labels=False)
    for index, number in enumerate((2, 3, 4), start=1):
        doc.modelspace().add_text(f"ST{number:02d}", dxfattribs={"layer": "PROFILE", "height": 2}).set_placement((index * 40, 14))

    result = _detect(tmp_path, doc)

    by_label = {station.drawing_label: station.sequence_index for station in result.stations}
    assert by_label["ST02"] == 2
    assert by_label["ST03"] == 3
    assert by_label["ST04"] == 4
    assert result.manual_review_required is True


def test_vertical_unlabelled_layout_orders_top_to_bottom(tmp_path):
    doc = make_flower_dxf(station_count=5, labels=False, vertical=True)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 5
    assert [station.sequence_index for station in result.stations] == [1, 2, 3, 4, 5]
    assert [round(station.bbox.max_y, 1) for station in result.stations] == sorted(
        [round(station.bbox.max_y, 1) for station in result.stations],
        reverse=True,
    )


def test_duplicate_labels_mark_conflict_for_review(tmp_path):
    doc = make_flower_dxf(station_count=4, labels=True, duplicate_label=True)

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 4
    assert result.manual_review_required is True
    assert any("conflicting_station_labels" in warning.code for warning in result.warnings)
    assert any(station.manual_review_required for station in result.stations)


def test_configured_cluster_gap_can_join_non_overlapping_station_geometry(tmp_path):
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("PROFILE", color=3)
    msp = doc.modelspace()
    for index in range(3):
        x = index * 80
        msp.add_lwpolyline([(x, 0), (x + 10, 0), (x + 10, 10), (x, 10)], close=True, dxfattribs={"layer": "PROFILE"})
        msp.add_lwpolyline([(x + 22, 0), (x + 32, 0), (x + 32, 10), (x + 22, 10)], close=True, dxfattribs={"layer": "PROFILE"})
        msp.add_text(f"ST{index + 1:02d}", dxfattribs={"layer": "PROFILE", "height": 2}).set_placement((x, 14))

    result = _detect(tmp_path, doc)

    assert len(result.stations) == 3
    assert all(len(station.source_handles) == 2 for station in result.stations)


def _detect(tmp_path, doc):
    return _detect_parsed(tmp_path, doc, parse_entities(doc, ExtractionConfig.load()))


def _detect_parsed(tmp_path, doc, parsed):
    dxf_path = tmp_path / "flower.dxf"
    doc.saveas(dxf_path)
    return detect_stations(parsed.entities + parsed.expanded_entities, inspect_drawing(dxf_path), ExtractionConfig.load())


def make_flower_dxf(
    *,
    station_count: int,
    labels: bool,
    rows: int = 1,
    blocks: bool = False,
    reversed_labels: bool = False,
    vertical: bool = False,
    duplicate_label: bool = False,
):
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("PROFILE", color=3)
    block = doc.blocks.new("FLOWER")
    block.add_lwpolyline([(0, 0), (16, 0), (16, 10), (0, 10)], close=True, dxfattribs={"layer": "PROFILE"})
    block.add_circle((8, 5), radius=3, dxfattribs={"layer": "PROFILE"})
    msp = doc.modelspace()
    columns = max(1, (station_count + rows - 1) // rows)
    for index in range(station_count):
        row = index // columns
        col = index % columns
        x = 0 if vertical else col * 40
        y = -index * 30 if vertical else -row * 30
        if blocks:
            msp.add_blockref("FLOWER", (x, y), dxfattribs={"layer": "PROFILE"})
        else:
            msp.add_lwpolyline([(x, y), (x + 16, y), (x + 16, y + 10), (x, y + 10)], close=True, dxfattribs={"layer": "PROFILE"})
            msp.add_circle((x + 8, y + 5), radius=3, dxfattribs={"layer": "PROFILE"})
        if labels:
            label_number = station_count - index if reversed_labels else index + 1
            if duplicate_label and index == station_count - 1:
                label_number = 1
            msp.add_text(f"ST{label_number:02d}", dxfattribs={"layer": "PROFILE", "height": 2}).set_placement((x, y + 14))
    return doc
