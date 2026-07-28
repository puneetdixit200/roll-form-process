from __future__ import annotations

from dataclasses import replace
import json
import sqlite3

from rollform_extractor.batch import BatchRequest, aggregate_master, batch_extract
from rollform_extractor.cli import main
from tests.cad_factory import make_flower_dxf


def test_batch_resume_skips_unchanged_successful_project(tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    make_flower_dxf(source_root / "one.dxf", station_count=2, labels=True)
    make_flower_dxf(source_root / "two.dxf", station_count=3, labels=True, rollers=True)
    request = BatchRequest(source_root, tmp_path / "out")

    first = batch_extract(request)
    second = batch_extract(replace(request, resume=True, skip_unchanged=True))

    assert second.projects_skipped == first.total_files
    assert second.projects_reprocessed == 0
    assert second.station_count == first.station_count


def test_batch_reprocesses_changed_input_on_resume(tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    source = make_flower_dxf(source_root / "one.dxf", station_count=1, labels=True)
    request = BatchRequest(source_root, tmp_path / "out")
    batch_extract(request)
    make_flower_dxf(source, station_count=2, labels=True)

    second = batch_extract(replace(request, resume=True, skip_unchanged=True))

    assert second.projects_reprocessed == 1
    assert second.projects_skipped == 0


def test_batch_failure_isolated_per_file(tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    make_flower_dxf(source_root / "good.dxf", station_count=1, labels=True)
    (source_root / "bad.dxf").write_text("not a dxf", encoding="utf-8")

    summary = batch_extract(BatchRequest(source_root, tmp_path / "out"))
    ledger = json.loads(summary.ledger_path.read_text(encoding="utf-8"))

    assert summary.projects_succeeded == 1
    assert summary.projects_failed == 1
    assert {entry["status"] for entry in ledger["files"]} == {"success", "failed"}


def test_master_database_keeps_project_provenance_and_is_idempotent(tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    make_flower_dxf(source_root / "one.dxf", station_count=2, labels=True)
    make_flower_dxf(source_root / "two.dxf", station_count=1, labels=True, rollers=True)

    summary = batch_extract(BatchRequest(source_root, tmp_path / "out"))
    aggregate_master(tmp_path / "out")
    master = sqlite3.connect(summary.master_database)
    rows = master.execute("select source_database, source_project_id from projects").fetchall()
    project_count = master.execute("select count(*) from projects").fetchone()[0]
    station_count = master.execute("select count(*) from stations").fetchone()[0]

    assert len(rows) == 2
    assert project_count == 2
    assert station_count == 3
    assert all(source and project_id for source, project_id in rows)


def test_master_database_copies_catalog_fingerprints_templates_usage_and_transitions(tmp_path):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    make_flower_dxf(source_root / "one.dxf", station_count=2, labels=True, rollers=True)
    summary = batch_extract(BatchRequest(source_root, tmp_path / "out"))
    project_db = tmp_path / "out" / "one" / "project.sqlite"
    with sqlite3.connect(project_db) as db:
        db.execute(
            "insert into geometry_fingerprints (project_id, owner_table, owner_key, fingerprint_hash, fingerprint_json) "
            "values (1, 'profiles', 'P1', 'abc', '{}')"
        )
        db.execute(
            "insert into assembly_templates (template_id, signature_hash, template_json) values ('AT-1', 'sig', '{}')"
        )
        db.execute(
            "insert into roller_catalog (factory_id, bore, width, diameter, availability) values ('R-1', 1, 2, 3, 'available')"
        )
        db.execute(
            "insert into project_roll_usage (project_id, roller_catalog_id, assembly_id, occurrence_id) values (1, 1, null, 1)"
        )
        db.execute(
            "insert into station_transitions (project_id, from_station_id, to_station_id, measurements_json) values (1, 1, 2, '{}')"
        )

    aggregate_master(tmp_path / "out")
    master = sqlite3.connect(summary.master_database)

    assert master.execute("select count(*) from geometry_fingerprints").fetchone()[0] == 1
    assert master.execute("select count(*) from assembly_templates").fetchone()[0] == 1
    assert master.execute("select factory_id from roller_catalog").fetchone()[0] == "R-1"
    assert master.execute("select count(*) from project_roll_usage").fetchone()[0] == 1
    assert master.execute("select count(*) from station_transitions").fetchone()[0] == 1


def test_batch_cli_extract_validate_and_report(tmp_path, capsys):
    source_root = tmp_path / "inputs"
    source_root.mkdir()
    make_flower_dxf(source_root / "one.dxf", station_count=2, labels=True)
    out = tmp_path / "out"

    assert main(["batch-extract", str(source_root), str(out)]) == 0
    assert main(["batch-validate", str(out)]) == 0
    assert main(["batch-report", str(out)]) == 0

    output = capsys.readouterr().out
    assert "files=1" in output
    assert "valid" in output
    assert "extraction_dashboard.html" in output
