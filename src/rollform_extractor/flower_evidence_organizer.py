"""Build a deterministic, private-local flower/station/subsequence/roller library."""

from __future__ import annotations

from hashlib import sha256
import html
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4


LIBRARY_SCHEMA_VERSION = 1
SUBSEQUENCE_LENGTH = 3


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_name(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in value.strip())
    safe = "-".join(part for part in safe.split("-") if part)
    if not safe:
        raise ValueError("label must contain at least one safe character")
    return safe


def _svg(points: list[list[float]], label: str) -> str:
    if not points:
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 240'><text x='20' y='40'>No geometry</text></svg>\n"
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    width, height = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    margin = max(width, height) * 0.1
    path = " ".join(f"{'M' if index == 0 else 'L'} {point[0]} {-point[1]}" for index, point in enumerate(points))
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' role='img' "
        f"aria-label='{html.escape(label)}' viewBox='{min_x-margin} {-max_y-margin} {width+2*margin} {height+2*margin}'>"
        f"<title>{html.escape(label)}</title><rect x='{min_x-margin}' y='{-max_y-margin}' width='{width+2*margin}' height='{height+2*margin}' fill='white'/>"
        f"<path d='{path}' fill='none' stroke='#155783' stroke-width='{max(width, height)*0.012}'/></svg>\n"
    )


def _copy_labelled(source: Path, destination: Path, label: str) -> dict[str, Any]:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"configured source is unavailable: {label}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "label": label,
        "filename": destination.name,
        "sha256": _digest_file(source),
        "size_bytes": source.stat().st_size,
    }


def _dataset_flowers(dataset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(item["flower_id"]): item for item in dataset.get("flowers", [])}


def _station_metadata(flower_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "station_label": f"STATION-{int(item.get('inferred_order', 0)) + 1:03d}",
        "pass_id": item.get("pass_id"),
        "sequence_order": int(item.get("inferred_order", 0)) + 1,
        "source_handle": item.get("source_handle"),
        "width": item.get("width"),
        "height": item.get("height"),
        "developed_length": item.get("developed_length"),
        "topology": item.get("topology"),
        "quality_flags": item.get("quality_flags", []),
        "roller_association_status": "UNRESOLVED_UNLESS_STATION_EVIDENCE_EXISTS",
        "manufacturing_approval": "NOT_APPROVED",
        "physical_asset_assignment": False,
    }


def _build_verified_flower(
    root: Path,
    entry: Mapping[str, Any],
    flower: Mapping[str, Any],
) -> dict[str, Any]:
    flower_id = _safe_name(str(entry["flower_id"]))
    passes = sorted(
        flower.get("passes", []),
        key=lambda item: (int(item.get("inferred_order", 0)), str(item.get("pass_id", ""))),
    )
    sequence_dir = root / "01_FLOWER_SEQUENCES" / flower_id
    source = Path(str(entry["source_path"]))
    source_record = _copy_labelled(source, sequence_dir / f"{flower_id}-SOURCE{source.suffix.lower()}", "verified flower sequence source")
    _write_json(sequence_dir / "FLOWER.json", {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "display_label": entry.get("display_label", flower_id),
        "evidence_status": "VERIFIED_DATASET_SEQUENCE",
        "station_count": len(passes),
        "source": source_record,
        "dataset_source_sha256": flower.get("source_sha256"),
        "quality_flags": flower.get("quality_flags", []),
    })

    station_links: list[str] = []
    for item in passes:
        order = int(item.get("inferred_order", 0)) + 1
        station_label = f"STATION-{order:03d}"
        station_dir = root / "02_STATIONS" / flower_id / station_label
        station_dir.mkdir(parents=True, exist_ok=True)
        _write_json(station_dir / "STATION.json", _station_metadata(flower_id, item))
        points = item.get("points") or item.get("normalized_points") or []
        (station_dir / "PROFILE.svg").write_text(_svg(points, f"{flower_id} {station_label}"), encoding="utf-8")
        station_links.append(f"02_STATIONS/{flower_id}/{station_label}/STATION.json")

    subsequence_links: list[str] = []
    for start in range(max(0, len(passes) - SUBSEQUENCE_LENGTH + 1)):
        window = passes[start : start + SUBSEQUENCE_LENGTH]
        start_order, end_order = start + 1, start + len(window)
        label = f"SUBSEQUENCE-{start_order:03d}-TO-{end_order:03d}"
        subsequence_dir = root / "03_SUBSEQUENCES" / flower_id / label
        subsequence_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "flower_id": flower_id,
            "subsequence_label": label,
            "start_station": f"STATION-{start_order:03d}",
            "end_station": f"STATION-{end_order:03d}",
            "pass_ids": [item.get("pass_id") for item in window],
            "source_handles": [item.get("source_handle") for item in window],
            "station_links": [f"../../../02_STATIONS/{flower_id}/STATION-{order:03d}/STATION.json" for order in range(start_order, end_order + 1)],
        }
        _write_json(subsequence_dir / "SUBSEQUENCE.json", record)
        subsequence_links.append(f"03_SUBSEQUENCES/{flower_id}/{label}/SUBSEQUENCE.json")

    roller_dir = root / "04_ROLLERS" / flower_id
    roller_dir.mkdir(parents=True, exist_ok=True)
    roller_records = []
    for roller in entry.get("roller_sources", []):
        evidence_id = _safe_name(str(roller["evidence_id"]))
        roller_source = Path(str(roller["path"]))
        copied = _copy_labelled(roller_source, roller_dir / f"{evidence_id}-SOURCE{roller_source.suffix.lower()}", "partial roller sequence evidence")
        copied.update({
            "evidence_id": evidence_id,
            "association_status": roller.get("association_status", "UNRESOLVED_STATION_ASSOCIATION"),
            "physical_asset_assignment": False,
            "manufacturing_approval": "NOT_APPROVED",
        })
        roller_records.append(copied)
    _write_json(roller_dir / "ROLLER_EVIDENCE.json", {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "records": roller_records,
        "notice": "Roller geometry is supporting evidence only. No station or physical asset is automatically assigned.",
    })
    return {
        "flower_id": flower_id,
        "status": "VERIFIED_DATASET_SEQUENCE",
        "station_count": len(passes),
        "subsequence_count": len(subsequence_links),
        "roller_evidence_count": len(roller_records),
        "sequence_link": f"01_FLOWER_SEQUENCES/{flower_id}/FLOWER.json",
        "station_links": station_links,
        "subsequence_links": subsequence_links,
        "roller_link": f"04_ROLLERS/{flower_id}/ROLLER_EVIDENCE.json",
    }


def _build_unindexed_source(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    source_id = _safe_name(str(entry["source_id"]))
    source = Path(str(entry["source_path"]))
    target = root / "01_FLOWER_SEQUENCES" / "REVIEW_REQUIRED" / source_id
    source_record = _copy_labelled(source, target / f"{source_id}-SOURCE{source.suffix.lower()}", "unindexed flower source drawing")
    _write_json(target / "SOURCE_STATUS.json", {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "source_id": source_id,
        "display_label": entry.get("display_label", source_id),
        "evidence_status": "REVIEW_REQUIRED_NOT_A_VERIFIED_FLOWER_SEQUENCE",
        "source": source_record,
        "stations_extracted": False,
        "roller_association_status": "UNRESOLVED",
    })
    return {
        "source_id": source_id,
        "status": "REVIEW_REQUIRED_NOT_A_VERIFIED_FLOWER_SEQUENCE",
        "source_link": f"01_FLOWER_SEQUENCES/REVIEW_REQUIRED/{source_id}/SOURCE_STATUS.json",
    }


def _index_html(index: Mapping[str, Any]) -> str:
    verified = "".join(
        f"<tr><td>{html.escape(item['flower_id'])}</td><td>{item['station_count']}</td><td>{item['subsequence_count']}</td><td>{item['roller_evidence_count']}</td><td><a href='{html.escape(item['sequence_link'])}'>flower</a> · <a href='{html.escape(item['roller_link'])}'>rollers</a></td></tr>"
        for item in index["verified_flowers"]
    )
    review = "".join(
        f"<li><a href='{html.escape(item['source_link'])}'>{html.escape(item['source_id'])}</a> — review required</li>"
        for item in index["review_required_sources"]
    )
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Flower Evidence Library</title><style>body{{font:16px system-ui;max-width:1100px;margin:auto;padding:1rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:.5rem;text-align:left}}.notice{{border-left:5px solid #b56d00;padding:.8rem;background:#fff5dd}}code{{background:#eee;padding:.1rem .3rem}}</style></head><body><h1>Flower Evidence Library</h1><p class='notice'><strong>Engineering evidence index.</strong> Roller evidence does not identify a physical asset and does not approve manufacturing.</p><p>Four folders: <code>01_FLOWER_SEQUENCES</code>, <code>02_STATIONS</code>, <code>03_SUBSEQUENCES</code>, <code>04_ROLLERS</code>.</p><h2>Verified flowers</h2><table><thead><tr><th>Flower</th><th>Stations</th><th>3-pass subsequences</th><th>Roller files</th><th>Open</th></tr></thead><tbody>{verified}</tbody></table><h2>Source drawings requiring extraction/review</h2><ul>{review}</ul></body></html>"""


def build_flower_evidence_library(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_path = Path(str(manifest["dataset_path"])).expanduser().resolve()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    flowers = _dataset_flowers(dataset)
    output_root = output_root.expanduser().resolve()
    staging = output_root.parent / f".{output_root.name}.tmp-{uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        for folder in ("01_FLOWER_SEQUENCES", "02_STATIONS", "03_SUBSEQUENCES", "04_ROLLERS"):
            (staging / folder).mkdir()
        verified = []
        for entry in sorted(manifest.get("flowers", []), key=lambda item: str(item["flower_id"])):
            flower_id = str(entry["flower_id"])
            if flower_id not in flowers:
                raise ValueError(f"dataset flower is unavailable: {flower_id}")
            verified.append(_build_verified_flower(staging, entry, flowers[flower_id]))
        review_required = [
            _build_unindexed_source(staging, entry)
            for entry in sorted(manifest.get("unindexed_sources", []), key=lambda item: str(item["source_id"]))
        ]
        index = {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "library_status": "READY_FOR_ENGINEERING_EVIDENCE_REVIEW",
            "dataset_id": dataset.get("dataset_id"),
            "dataset_hash": dataset.get("dataset_hash"),
            "verified_flowers": verified,
            "review_required_sources": review_required,
            "folder_contract": ["01_FLOWER_SEQUENCES", "02_STATIONS", "03_SUBSEQUENCES", "04_ROLLERS"],
            "manufacturing_approval": "NOT_APPROVED",
            "physical_asset_assignment": False,
        }
        _write_json(staging / "INDEX.json", index)
        (staging / "INDEX.html").write_text(_index_html(index), encoding="utf-8")
        if output_root.exists():
            backup = output_root.parent / f".{output_root.name}.backup-{uuid4().hex}"
            os.replace(output_root, backup)
            try:
                os.replace(staging, output_root)
            except Exception:
                os.replace(backup, output_root)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(staging, output_root)
        return index
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
