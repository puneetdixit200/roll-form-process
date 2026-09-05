"""Portable SQLite evidence indexed by dataset, flower and historical pass."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def build_roller_library(library: Path, output: Path) -> dict[str, Any]:
    """Build a separate derived database; publish only after integrity checks."""
    library = library.resolve()
    index = json.loads((library / "INDEX.json").read_text())
    stages, rollers = [], []
    for evidence_path in sorted(library.glob("04_ROLLERS/*/ROLLER_EVIDENCE.json")):
        evidence = json.loads(evidence_path.read_text())
        flower = evidence["flower_id"]
        for stage in (evidence.get("station_mapping") or {}).get("station_mappings", []):
            stage_key = sha256(f"{flower}|{stage['pass_id']}".encode()).hexdigest()
            stages.append((stage_key, flower, stage["pass_id"], json.dumps(stage, sort_keys=True)))
            folder = evidence_path.parent / stage["station_label"]
            for record_path in sorted(folder.glob("*/ROLLER.json")):
                record = json.loads(record_path.read_text())
                roller_key = sha256(f"{stage_key}|{record['occurrence_id']}".encode()).hexdigest()
                png = (record_path.parent / "ROLLER.png").read_bytes()
                dxf = (record_path.parent / "ROLLER.dxf").read_bytes()
                # Public contracts use an explicit allowlist, never source paths.
                metadata = {key: record.get(key) for key in (
                    "occurrence_id", "source_station_id", "source_handles", "candidate_role",
                    "geometry_completeness", "confidence", "role_status",
                )}
                rollers.append((roller_key, stage_key, json.dumps(metadata, sort_keys=True), png, dxf))
    semantic = [index["dataset_hash"], stages, [list(row[:3]) + [sha256(row[3]).hexdigest(), sha256(row[4]).hexdigest()] for row in rollers]]
    content_hash = sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".roller-library-", dir=output.parent)
    os.close(fd)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE stages (id TEXT PRIMARY KEY, flower_id TEXT NOT NULL,
                        pass_id TEXT NOT NULL, metadata TEXT NOT NULL, UNIQUE(flower_id, pass_id));
                    CREATE TABLE rollers (id TEXT PRIMARY KEY, stage_id TEXT NOT NULL REFERENCES stages(id),
                        metadata TEXT NOT NULL, png BLOB NOT NULL, dxf BLOB NOT NULL);
                    CREATE INDEX rollers_stage ON rollers(stage_id);
                    PRAGMA user_version=1;
                """)
                db.executemany("INSERT INTO metadata VALUES (?,?)", [("dataset_hash", index["dataset_hash"]), ("content_hash", content_hash)])
                db.executemany("INSERT INTO stages VALUES (?,?,?,?)", stages)
                db.executemany("INSERT INTO rollers VALUES (?,?,?,?,?)", rollers)
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("roller library integrity failed")
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"stage_count": len(stages), "roller_count": len(rollers), "content_hash": content_hash}


def configured_library() -> Path | None:
    configured = os.environ.get("ROLLFORM_HISTORICAL_ROLLER_SQLITE")
    dataset = os.environ.get("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
    path = Path(configured) if configured else Path(dataset).with_name("rollers.sqlite") if dataset else None
    return path if path and path.is_file() else None


def library_hash(path: Path | None, dataset_hash: str) -> str:
    if path is None:
        return "UNCONFIGURED"
    with closing(_connect(path)) as db:
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
    return metadata["content_hash"] if metadata["dataset_hash"] == dataset_hash else "STALE_DATASET"


def attach_subsequence_rollers(candidates: list[dict], path: Path | None, dataset_hash: str) -> None:
    status = library_hash(path, dataset_hash)
    for candidate in candidates:
        candidate["historical_roller_library_hash"] = status
        lookups = [
            (match["source_flower_id"], mapping)
            for match in candidate.get("top_historical_subsequences", [])
            for mapping in match.get("mapping", [])
        ]
        # Individual pass matches have their own source identities. Never borrow
        # rollers from the best interval, another match rank, or an adjacent pass.
        for generated_pass in candidate.get("passes", []):
            history = generated_pass.get("historical_match") or {}
            matches = list(history.get("top_matches") or [])[:3]
            if history.get("best_match"):
                matches.append(history["best_match"])
            lookups.extend((match["source_flower_id"], match) for match in matches)
        for flower_id, mapping in lookups:
            mapping["roller_occurrences"] = []
            mapping["roller_link_status"] = status if status in {"UNCONFIGURED", "STALE_DATASET"} else "NO_SOURCE_STAGE"
            if path is None or status in {"UNCONFIGURED", "STALE_DATASET"}:
                continue
            with closing(_connect(path)) as db:
                stage = db.execute("SELECT id,metadata FROM stages WHERE flower_id=? AND pass_id=?", (flower_id, mapping["source_pass_id"])).fetchone()
                if stage is None:
                    continue
                mapping["roller_source_link"] = json.loads(stage["metadata"])
                rows = db.execute("SELECT id,metadata FROM rollers WHERE stage_id=? ORDER BY id", (stage["id"],)).fetchall()
                mapping["roller_link_status"] = "HISTORICAL_OCCURRENCE_EVIDENCE" if rows else "NO_ROLLER_DETECTED"
                mapping["roller_occurrences"] = [json.loads(row["metadata"]) | {
                    "roller_id": row["id"], "manufacturing_approval": "NOT_APPROVED", "physical_asset_assignment": False,
                } for row in rows]
        if candidate.get("top_historical_subsequences"):
            candidate["best_historical_subsequence"] = candidate["top_historical_subsequences"][0]


def roller_asset(path: Path | None, dataset_hash: str, roller_id: str, kind: str) -> bytes | None:
    if kind not in {"png", "dxf"} or path is None or library_hash(path, dataset_hash) in {"UNCONFIGURED", "STALE_DATASET"}:
        return None
    with closing(_connect(path)) as db:
        row = db.execute(f"SELECT {kind} FROM rollers WHERE id=?", (roller_id,)).fetchone()
        return bytes(row[0]) if row else None
