from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rollform_extractor.models import BBox, CadEntityRecord, WarningRecord
from rollform_extractor.review import (
    OverrideValidationError,
    apply_station_overrides,
    load_overrides,
    write_review_queue,
)


BOX_A = BBox(0.0, 0.0, 10.0, 10.0)
BOX_B = BBox(20.0, 0.0, 30.0, 10.0)
BOX_C = BBox(40.0, 0.0, 50.0, 10.0)


@pytest.fixture
def parsed_flower():
    entities = (
        _entity("A1", BOX_A),
        _entity("B1", BOX_B),
        _entity("C1", BOX_C),
    )
    return type("ParsedFlower", (), {"entities": entities, "handles": {e.handle for e in entities}})()


def test_manual_station_boxes_define_variable_station_count(parsed_flower, tmp_path):
    overrides = write_overrides(tmp_path, station_boxes=[BOX_A, BOX_B, BOX_C])

    stations = apply_station_overrides(
        parsed_flower.entities,
        load_overrides(overrides, parsed_flower.handles),
    )

    assert [station.sequence_index for station in stations] == [1, 2, 3]
    assert [station.station_id for station in stations] == ["S1", "S2", "S3"]
    assert [station.bbox for station in stations] == [BOX_A, BOX_B, BOX_C]
    assert all(station.method == "manual_override" for station in stations)


def test_unknown_profile_handle_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(tmp_path, profile_handles={"1": ["DOES_NOT_EXIST"]})

    with pytest.raises(OverrideValidationError, match="DOES_NOT_EXIST"):
        load_overrides(path, parsed_flower.handles)


def test_unknown_station_source_handle_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        raw_station_boxes=[
            {
                "sequence_index": 1,
                "bbox": _box_json(BOX_A),
                "source_handles": ["DOES_NOT_EXIST"],
            }
        ],
    )

    with pytest.raises(OverrideValidationError, match="DOES_NOT_EXIST"):
        load_overrides(path, parsed_flower.handles)


def test_duplicate_station_order_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        raw_station_boxes=[
            {"sequence_index": 1, "bbox": _box_json(BOX_A)},
            {"sequence_index": 1, "bbox": _box_json(BOX_B)},
        ],
    )

    with pytest.raises(OverrideValidationError, match="duplicate station sequence"):
        load_overrides(path, parsed_flower.handles)


@pytest.mark.parametrize("sequence_index", [1.9, "1"])
def test_non_integer_station_sequence_is_rejected(parsed_flower, tmp_path, sequence_index):
    path = write_overrides(
        tmp_path,
        raw_station_boxes=[{"sequence_index": sequence_index, "bbox": _box_json(BOX_A)}],
    )

    with pytest.raises(OverrideValidationError, match="sequence_index"):
        load_overrides(path, parsed_flower.handles)


def test_invalid_station_box_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        raw_station_boxes=[{"sequence_index": 1, "bbox": _box_json(BBox(0, 0, 0, 1))}],
    )

    with pytest.raises(OverrideValidationError, match="positive area"):
        load_overrides(path, parsed_flower.handles)


def test_conflicting_handle_ownership_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        station_boxes=[BOX_A, BOX_B],
        profile_handles={"1": ["A1"]},
        roller_handles={"2": {"upper": ["A1"]}},
    )

    with pytest.raises(OverrideValidationError, match="assigned to multiple stations"):
        load_overrides(path, parsed_flower.handles)


def test_same_station_profile_and_roller_handle_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        profile_handles={"1": ["A1"]},
        roller_handles={"1": {"upper": ["A1"]}},
    )

    with pytest.raises(OverrideValidationError, match="assigned more than once"):
        load_overrides(path, parsed_flower.handles)


def test_overlapping_station_boxes_reject_shared_entity_ownership(parsed_flower, tmp_path):
    path = write_overrides(
        tmp_path,
        raw_station_boxes=[
            {"sequence_index": 1, "bbox": _box_json(BBox(0, 0, 7, 10))},
            {"sequence_index": 2, "bbox": _box_json(BBox(5, 0, 12, 10))},
        ],
    )

    overrides = load_overrides(path, parsed_flower.handles)
    with pytest.raises(OverrideValidationError, match="assigned to multiple stations"):
        apply_station_overrides(parsed_flower.entities, overrides)


def test_unknown_station_reference_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(tmp_path, station_boxes=[BOX_A], profile_handles={"2": ["A1"]})

    with pytest.raises(OverrideValidationError, match="unknown station"):
        load_overrides(path, parsed_flower.handles)


def test_invalid_units_and_roller_roles_are_rejected(parsed_flower, tmp_path):
    bad_units = write_overrides(tmp_path, units="cubits")
    with pytest.raises(OverrideValidationError, match="units"):
        load_overrides(bad_units, parsed_flower.handles)

    bad_role = write_overrides(tmp_path, roller_handles={"1": {"maybe": ["A1"]}})
    with pytest.raises(OverrideValidationError, match="roller role"):
        load_overrides(bad_role, parsed_flower.handles)


def test_schema_version_is_required(parsed_flower, tmp_path):
    path = tmp_path / "manual_overrides.json"
    path.write_text(json.dumps({"stations": []}), encoding="utf-8")

    with pytest.raises(OverrideValidationError, match="schema_version"):
        load_overrides(path, parsed_flower.handles)


def test_configuration_snapshot_must_be_a_mapping(parsed_flower, tmp_path):
    path = write_overrides(tmp_path, configuration_snapshot=["not", "a", "mapping"])

    with pytest.raises(OverrideValidationError, match="configuration_snapshot"):
        load_overrides(path, parsed_flower.handles)


def test_review_queue_writes_json_and_csv_without_overwriting_engineer_decisions(tmp_path):
    warnings = (
        _warning("uncertain_boundary", ("A1",)),
        _warning("missing_label", ()),
        _warning("profile_ambiguity", ("B1",)),
        _warning("roller_ambiguity", ("C1",)),
        _warning("broken_contour", ("A1", "B1")),
        _warning("low_confidence", ("C1",)),
        _warning("duplicate_id", ("A1",)),
        _warning("shared_station_geometry", ("A1",)),
        _warning("unit_uncertainty", ()),
    )
    template = {
        "schema_version": 1,
        "units": "mm",
        "stations": [{"sequence_index": 1, "bbox": _box_json(BOX_A)}],
    }
    json_path, csv_path = write_review_queue(tmp_path, warnings, template)
    manual_path = tmp_path / "manual_overrides.json"
    manual_path.write_text(json.dumps({"engineer_decision": "keep"}), encoding="utf-8")

    second_json_path, second_csv_path = write_review_queue(tmp_path, warnings, template)

    assert (json_path, csv_path) == (second_json_path, second_csv_path)
    assert json.loads(manual_path.read_text(encoding="utf-8")) == {"engineer_decision": "keep"}
    queue = json.loads(json_path.read_text(encoding="utf-8"))
    assert [item["category"] for item in queue["items"]] == [
        "uncertain_boundary",
        "missing_label",
        "profile_ambiguity",
        "roller_ambiguity",
        "broken_contour",
        "low_confidence",
        "duplicate_id",
        "shared_station_geometry",
        "unit_uncertainty",
    ]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["category"] == "uncertain_boundary"
    assert rows[-1]["category"] == "unit_uncertainty"


def test_review_queue_preserves_completed_json_and_csv_decisions(tmp_path):
    json_path = tmp_path / "review_queue.json"
    csv_path = tmp_path / "review_queue.csv"
    resolved_item = {
        "category": "missing_label",
        "message": "engineer resolved",
        "source_handles": ["A1"],
        "method": "manual",
        "configuration_hash": "old-hash",
        "confidence": 1.0,
        "status": "resolved",
        "engineer_decision": "S1",
    }
    json_path.write_text(
        json.dumps({"schema_version": 1, "items": [resolved_item]}),
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "category",
                "message",
                "source_handles",
                "method",
                "configuration_hash",
                "confidence",
                "status",
                "engineer_decision",
            ],
        )
        writer.writeheader()
        writer.writerow({**resolved_item, "source_handles": "A1"})

    write_review_queue(tmp_path, (_warning("low_confidence", ("B1",)),), {"schema_version": 1})

    queue = json.loads(json_path.read_text(encoding="utf-8"))
    assert resolved_item in queue["items"]
    assert any(item["category"] == "low_confidence" for item in queue["items"])
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert any(row["engineer_decision"] == "S1" for row in rows)
    assert any(row["category"] == "low_confidence" for row in rows)


def write_overrides(
    tmp_path: Path,
    *,
    units: str = "mm",
    station_boxes: list[BBox] | None = None,
    raw_station_boxes: list[dict] | None = None,
    profile_handles: dict[str, list[str]] | None = None,
    roller_handles: dict[str, dict[str, list[str]]] | None = None,
    configuration_snapshot: object = None,
) -> Path:
    stations = raw_station_boxes
    if stations is None:
        stations = [
            {"sequence_index": index, "bbox": _box_json(box)}
            for index, box in enumerate(station_boxes or [BOX_A], start=1)
        ]
    path = tmp_path / "manual_overrides.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "units": units,
                "configuration_snapshot": (
                    {"source": "test"} if configuration_snapshot is None else configuration_snapshot
                ),
                "stations": stations,
                "profile_handles": profile_handles or {},
                "roller_handles": roller_handles or {},
            }
        ),
        encoding="utf-8",
    )
    return path


def _box_json(box: BBox) -> dict[str, float]:
    return {
        "min_x": box.min_x,
        "min_y": box.min_y,
        "max_x": box.max_x,
        "max_y": box.max_y,
    }


def _entity(handle: str, box: BBox) -> CadEntityRecord:
    return CadEntityRecord(
        handle=handle,
        entity_type="LINE",
        layer="PROFILE",
        color=7,
        line_type=None,
        layout="Model",
        bbox=box,
        source_handles=(handle,),
        configuration_hash="entity-hash",
    )


def _warning(code: str, handles: tuple[str, ...]) -> WarningRecord:
    return WarningRecord(
        code=code,
        message=f"{code} needs review",
        source_handles=handles,
        method="test",
        configuration_hash="warning-hash",
        confidence=0.4,
    )
