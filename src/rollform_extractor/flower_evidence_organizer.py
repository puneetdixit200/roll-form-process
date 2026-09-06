"""Build a deterministic, private-local flower/station/subsequence/roller library."""

from __future__ import annotations

from hashlib import sha256
import csv
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping
from uuid import uuid4

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


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


def _save_dxf_deterministically(document: Any, path: Path) -> None:
    document.saveas(path)
    text = path.read_text(encoding="utf-8")
    # ezdxf writes the current Julian timestamp into these header variables.
    # They do not describe source geometry and would otherwise make identical
    # evidence exports differ byte-for-byte between runs.
    text = re.sub(
        r"(\$TD(?:U)?(?:CREATE|UPDATE)\r?\n\s*40\r?\n)[^\r\n]+",
        r"\g<1>2451544.5",
        text,
    )
    text = re.sub(
        r"(\d+\.\d+\.\d+ @ )\d{4}-\d{2}-\d{2}T[^\r\n]+",
        r"\g<1>2000-01-01T00:00:00+00:00",
        text,
    )
    path.write_text(text, encoding="utf-8", newline="")


def _write_extracted_sequence_dxf(path: Path, flower_id: str, passes: list[Mapping[str, Any]]) -> None:
    """Write only the selected flower passes into a deterministic derived DXF."""
    document = ezdxf.new("R12")
    document.layers.add("EXTRACTED_SEQUENCE", color=5)
    document.layers.add("STATION_LABELS", color=7)
    modelspace = document.modelspace()
    widths = []
    for item in passes:
        points = item.get("points") or item.get("normalized_points") or []
        xs = [float(point[0]) for point in points]
        widths.append(max(xs) - min(xs) if xs else 1.0)
    spacing = max(max(widths, default=1.0) * 1.25, 10.0)
    for index, item in enumerate(passes):
        raw_points = item.get("points") or item.get("normalized_points") or []
        points = [(float(point[0]), float(point[1])) for point in raw_points]
        if not points:
            continue
        min_x = min(point[0] for point in points)
        min_y = min(point[1] for point in points)
        positioned = [(x - min_x + index * spacing, y - min_y) for x, y in points]
        closed = len(positioned) > 2 and math.dist(positioned[0], positioned[-1]) <= 1e-9
        if closed:
            positioned = positioned[:-1]
        modelspace.add_polyline2d(positioned, close=closed, dxfattribs={"layer": "EXTRACTED_SEQUENCE"})
        label = modelspace.add_text(
            f"{flower_id} STATION-{index + 1:03d}",
            height=max(spacing * 0.025, 1.0),
            dxfattribs={"layer": "STATION_LABELS"},
        )
        label.set_placement((index * spacing, -max(spacing * 0.08, 3.0)))
    _save_dxf_deterministically(document, path)


def _positioned_passes(passes: list[Mapping[str, Any]]) -> tuple[list[list[tuple[float, float]]], float]:
    raw = []
    widths = []
    for item in passes:
        source_points = item.get("points") or item.get("normalized_points") or []
        points = [(float(point[0]), float(point[1])) for point in source_points]
        raw.append(points)
        widths.append(max((point[0] for point in points), default=1.0) - min((point[0] for point in points), default=0.0))
    spacing = max(max(widths, default=1.0) * 1.25, 10.0)
    positioned = []
    for index, points in enumerate(raw):
        min_x = min((point[0] for point in points), default=0.0)
        min_y = min((point[1] for point in points), default=0.0)
        positioned.append([(x - min_x + index * spacing, y - min_y) for x, y in points])
    return positioned, spacing


def _write_sequence_png(path: Path, flower_id: str, passes: list[Mapping[str, Any]], title: str) -> None:
    positioned, _spacing = _positioned_passes(passes)
    figure, axis = plt.subplots(figsize=(max(7.0, len(passes) * 1.2), 4.5))
    for index, points in enumerate(positioned):
        if not points:
            continue
        x, y = zip(*points)
        axis.plot(x, y, linewidth=1.4, label=f"Station {index + 1:03d}")
        axis.text(sum(x) / len(x), min(y), str(index + 1), fontsize=7, ha="center", va="top")
    axis.set_title(f"{flower_id} — {title}")
    axis.set_aspect("equal", adjustable="datalim")
    axis.axis("off")
    figure.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _write_profile_png(path: Path, flower_id: str, station_label: str, item: Mapping[str, Any]) -> None:
    points = item.get("points") or item.get("normalized_points") or []
    figure, axis = plt.subplots(figsize=(5.0, 3.5))
    if points:
        x = [float(point[0]) for point in points]
        y = [float(point[1]) for point in points]
        axis.plot(x, y, color="#155783", linewidth=2.0)
    axis.set_title(f"{flower_id} — {station_label}")
    axis.set_aspect("equal", adjustable="datalim")
    axis.axis("off")
    figure.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _entity_points(entity: Any, sample_count: int = 96) -> list[tuple[float, float]]:
    if entity.dxftype() == "POLYLINE":
        points = [(float(vertex.dxf.location.x), float(vertex.dxf.location.y)) for vertex in entity.vertices]
        if entity.is_closed and points and points[0] != points[-1]:
            points.append(points[0])
        return points
    if entity.dxftype() == "ARC":
        center = entity.dxf.center
        start = math.radians(float(entity.dxf.start_angle))
        sweep = math.radians((float(entity.dxf.end_angle) - float(entity.dxf.start_angle)) % 360.0)
        return [
            (
                float(center.x) + float(entity.dxf.radius) * math.cos(start + sweep * index / sample_count),
                float(center.y) + float(entity.dxf.radius) * math.sin(start + sweep * index / sample_count),
            )
            for index in range(sample_count + 1)
        ]
    return []


def _write_roller_artifacts(
    roller_dir: Path,
    flower_id: str,
    station_label: str,
    roller: Mapping[str, Any],
    source_entities: Mapping[str, Any],
) -> dict[str, Any]:
    occurrence_id = _safe_name(str(roller["occurrence_id"]))
    target = roller_dir / station_label / occurrence_id
    target.mkdir(parents=True, exist_ok=True)
    handles = [str(value) for value in roller.get("source_handles", [])]
    entities = [source_entities[handle] for handle in handles if handle in source_entities]
    if not entities:
        raise ValueError(f"roller source geometry unavailable: {occurrence_id}")
    document = ezdxf.new("R12")
    document.layers.add("ROLLER_EVIDENCE", color=3)
    modelspace = document.modelspace()
    for entity in entities:
        copied = entity.copy()
        copied.dxf.layer = "ROLLER_EVIDENCE"
        modelspace.add_entity(copied)
    dxf_name = "ROLLER.dxf"
    _save_dxf_deterministically(document, target / dxf_name)

    figure, axis = plt.subplots(figsize=(4.5, 4.0))
    partial = False
    for entity in entities:
        points = _entity_points(entity)
        if points:
            x, y = zip(*points)
            axis.plot(x, y, color="#7a3e00", linewidth=2.0)
        partial = partial or entity.dxftype() == "ARC" or (entity.dxftype() == "POLYLINE" and not entity.is_closed)
    evidence = dict(roller.get("evidence") or {})
    role = str(roller.get("role") or evidence.get("candidate_role") or "UNCLASSIFIED").upper()
    axis.set_title(f"{flower_id} {station_label}\n{occurrence_id} — {role}")
    axis.set_aspect("equal", adjustable="datalim")
    axis.axis("off")
    png_name = "ROLLER.png"
    figure.savefig(target / png_name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    record = {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "station_label": station_label,
        "source_station_id": roller.get("station_id"),
        "occurrence_id": occurrence_id,
        "candidate_role": role,
        "source_handles": handles,
        "confidence": roller.get("confidence"),
        "role_status": "CANDIDATE_NOT_ENGINEER_CONFIRMED",
        "geometry_completeness": "PARTIAL_GEOMETRY" if partial else "COMPLETE_OUTLINE",
        "dxf": dxf_name,
        "png": png_name,
        "evidence": evidence,
        "physical_asset_assignment": False,
        "manufacturing_approval": "NOT_APPROVED",
    }
    _write_json(target / "ROLLER.json", record)
    return record


def _station_roller_evidence(
    root: Path,
    entry: Mapping[str, Any],
    flower_id: str,
    passes: list[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any] | None]:
    configured = entry.get("extraction_project_path")
    if not configured:
        return {}, None
    project_root = Path(str(configured)).expanduser().resolve()
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    report_path = project_root / "report_data.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    source_files = sorted((project_root / "source").glob("*.dxf"))
    if len(source_files) != 1:
        raise ValueError(f"expected one extracted source DXF for {flower_id}")
    source_document = ezdxf.readfile(source_files[0])
    source_entities = {
        str(entity.dxf.handle): entity
        for entity in source_document.modelspace()
        if getattr(entity.dxf, "handle", None)
    }
    profiles = list(project.get("profiles", []))
    profiles_by_id = {str(profile.get("profile_id")): profile for profile in profiles}
    station_region = {
        str(station.get("station_id")): str((station.get("evidence") or {}).get("region_type") or "")
        for station in project.get("stations", [])
    }
    composite_by_handle = {}
    for composite in report.get("composite_flowers", []):
        for item in composite.get("passes", []):
            for handle in item.get("source_handles", []):
                composite_by_handle[str(handle)] = item
    rollers_by_station: dict[str, list[Mapping[str, Any]]] = {}
    for roller in project.get("rollers", []):
        rollers_by_station.setdefault(str(roller.get("station_id")), []).append(roller)

    station_records: dict[str, list[dict[str, Any]]] = {}
    mappings = []
    roller_dir = root / "04_ROLLERS" / flower_id
    for index, item in enumerate(passes):
        station_label = f"STATION-{index + 1:03d}"
        source_handle = str(item.get("source_handle", ""))
        direct = [
            profile
            for profile in profiles
            if source_handle in {str(value) for value in profile.get("source_handles", [])}
            and station_region.get(str(profile.get("station_id"))) != "COMPOSITE_FLOWER"
        ]
        linkage_method = "SOURCE_HANDLE"
        linkage_score = 1.0
        selected_profile = direct[0] if len(direct) == 1 else None
        if selected_profile is None and source_handle in composite_by_handle:
            matches = composite_by_handle[source_handle].get("individual_profile_matches", [])
            ranked = sorted(matches, key=lambda value: (-float(value.get("similarity_score", 0.0)), str(value.get("individual_profile_id", ""))))
            selected_profile = profiles_by_id.get(str(ranked[0].get("individual_profile_id"))) if ranked else None
            linkage_method = "EXACT_GEOMETRY_MATCH" if ranked and ranked[0].get("exact_match") else "GEOMETRY_MATCH_REVIEW_REQUIRED"
            linkage_score = float(ranked[0].get("similarity_score", 0.0)) if ranked else 0.0
        source_station_id = str(selected_profile.get("station_id")) if selected_profile else None
        records = []
        for roller in sorted(rollers_by_station.get(source_station_id or "", []), key=lambda value: str(value.get("occurrence_id", ""))):
            records.append(_write_roller_artifacts(roller_dir, flower_id, station_label, roller, source_entities))
        station_records[station_label] = records
        mappings.append({
            "station_label": station_label,
            "pass_id": item.get("pass_id"),
            "source_station_id": source_station_id,
            "linkage_method": linkage_method if selected_profile else "NO_STATION_MATCH",
            "linkage_score": linkage_score,
            "roller_occurrence_count": len(records),
            "confirmation_status": "CANDIDATE_NOT_ENGINEER_CONFIRMED",
        })
        station_manifest_dir = roller_dir / station_label
        station_manifest_dir.mkdir(parents=True, exist_ok=True)
        _write_json(station_manifest_dir / "STATION_ROLLERS.json", {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "flower_id": flower_id,
            "station_label": station_label,
            "source_station_id": source_station_id,
            "linkage_method": linkage_method if selected_profile else "NO_STATION_MATCH",
            "linkage_score": linkage_score,
            "confirmation_status": "CANDIDATE_NOT_ENGINEER_CONFIRMED",
            "roller_occurrence_count": len(records),
            "roller_occurrences": [
                {
                    "occurrence_id": record["occurrence_id"],
                    "candidate_role": record["candidate_role"],
                    "geometry_completeness": record["geometry_completeness"],
                    "record": f"{record['occurrence_id']}/ROLLER.json",
                    "dxf": f"{record['occurrence_id']}/ROLLER.dxf",
                    "png": f"{record['occurrence_id']}/ROLLER.png",
                }
                for record in records
            ],
            "notice": "Historical roller occurrence evidence only. No physical asset is identified or approved.",
        })
    return station_records, {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "source_project_sha256": _digest_file(project_root / "project.json"),
        "station_mappings": mappings,
        "notice": "Detected roller geometry is historical evidence only. Partial geometry is retained. No physical asset is assigned.",
    }


def _dataset_flowers(dataset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(item["flower_id"]): item for item in dataset.get("flowers", [])}


def _station_metadata(
    flower_id: str,
    item: Mapping[str, Any],
    roller_records: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    roller_records = roller_records or []
    station_label = f"STATION-{int(item.get('inferred_order', 0)) + 1:03d}"
    return {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "station_label": station_label,
        "pass_id": item.get("pass_id"),
        "sequence_order": int(item.get("inferred_order", 0)) + 1,
        "source_handle": item.get("source_handle"),
        "width": item.get("width"),
        "height": item.get("height"),
        "developed_length": item.get("developed_length"),
        "topology": item.get("topology"),
        "quality_flags": item.get("quality_flags", []),
        "roller_association_status": "UNRESOLVED_UNLESS_STATION_EVIDENCE_EXISTS",
        "roller_evidence_link": f"../../../04_ROLLERS/{flower_id}/ROLLER_EVIDENCE.json",
        "roller_station_manifest_link": f"../../../04_ROLLERS/{flower_id}/{station_label}/STATION_ROLLERS.json",
        "roller_occurrence_count": len(roller_records),
        "roller_occurrence_links": [
            f"../../../04_ROLLERS/{flower_id}/{station_label}/{record['occurrence_id']}/ROLLER.json"
            for record in roller_records
        ],
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
    source_record = _copy_labelled(source, sequence_dir / f"{flower_id}-SOURCE{source.suffix.lower()}", "extracted flower sequence source")
    quality_flags = list(flower.get("quality_flags", []))
    order_review_required = any("ORDER_INFERRED_REVIEW_REQUIRED" in str(flag) for flag in quality_flags)
    evidence_status = "EXTRACTED_DATASET_SEQUENCE_REVIEW_REQUIRED" if order_review_required else "VERIFIED_DATASET_SEQUENCE"
    extracted_sequence_name = f"{flower_id}-EXTRACTED-SEQUENCE.dxf"
    _write_extracted_sequence_dxf(sequence_dir / extracted_sequence_name, flower_id, passes)
    sequence_png_name = f"{flower_id}-FULL-SEQUENCE.png"
    _write_sequence_png(sequence_dir / sequence_png_name, flower_id, passes, "Full flower sequence")
    _write_json(sequence_dir / "FLOWER.json", {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "flower_id": flower_id,
        "display_label": entry.get("display_label", flower_id),
        "evidence_status": evidence_status,
        "pass_order_status": "ENGINEER_REVIEW_REQUIRED" if order_review_required else "DATASET_VERIFIED",
        "station_count": len(passes),
        "source": source_record,
        "extracted_sequence_dxf": extracted_sequence_name,
        "extracted_sequence_sha256": _digest_file(sequence_dir / extracted_sequence_name),
        "extracted_sequence_contains_source_cad": False,
        "full_sequence_png": sequence_png_name,
        "dataset_source_sha256": flower.get("source_sha256"),
        "source_region_id": flower.get("source_region_id"),
        "extractor_mode_requested": flower.get("extractor_mode_requested"),
        "extractor_mode_used": flower.get("extractor_mode_used"),
        "quality_flags": quality_flags,
    })

    station_rollers, station_mapping = _station_roller_evidence(root, entry, flower_id, passes)

    station_links: list[str] = []
    for item in passes:
        order = int(item.get("inferred_order", 0)) + 1
        station_label = f"STATION-{order:03d}"
        station_dir = root / "02_STATIONS" / flower_id / station_label
        station_dir.mkdir(parents=True, exist_ok=True)
        _write_json(station_dir / "STATION.json", _station_metadata(flower_id, item, station_rollers.get(station_label)))
        points = item.get("points") or item.get("normalized_points") or []
        (station_dir / "PROFILE.svg").write_text(_svg(points, f"{flower_id} {station_label}"), encoding="utf-8")
        _write_profile_png(station_dir / "PROFILE.png", flower_id, station_label, item)
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
            "roller_evidence_link": f"../../../04_ROLLERS/{flower_id}/ROLLER_EVIDENCE.json",
            "roller_station_links": [
                f"../../../04_ROLLERS/{flower_id}/STATION-{order:03d}/STATION_ROLLERS.json"
                for order in range(start_order, end_order + 1)
            ],
            "roller_occurrence_count": sum(
                len(station_rollers.get(f"STATION-{order:03d}", []))
                for order in range(start_order, end_order + 1)
            ),
            "roller_station_association_status": "UNRESOLVED_UNLESS_STATION_EVIDENCE_EXISTS",
        }
        _write_json(subsequence_dir / "SUBSEQUENCE.json", record)
        _write_extracted_sequence_dxf(subsequence_dir / "ROLL-FORM-SUBSEQUENCE.dxf", f"{flower_id} {label}", window)
        _write_sequence_png(subsequence_dir / "ROLL-FORM-SUBSEQUENCE.png", flower_id, window, label)
        subsequence_links.append(f"03_SUBSEQUENCES/{flower_id}/{label}/SUBSEQUENCE.json")

    roller_dir = root / "04_ROLLERS" / flower_id
    roller_dir.mkdir(parents=True, exist_ok=True)
    roller_records = [record for station_records in station_rollers.values() for record in station_records]
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
        "station_mapping": station_mapping,
        "notice": "Roller geometry is supporting evidence only. No station or physical asset is automatically assigned.",
    })
    return {
        "flower_id": flower_id,
        "status": evidence_status,
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
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Flower Evidence Library</title><style>body{{font:16px system-ui;max-width:1100px;margin:auto;padding:1rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:.5rem;text-align:left}}.notice{{border-left:5px solid #b56d00;padding:.8rem;background:#fff5dd}}code{{background:#eee;padding:.1rem .3rem}}</style></head><body><h1>Flower Evidence Library</h1><p class='notice'><strong>Engineering evidence index.</strong> Roller evidence does not identify a physical asset and does not approve manufacturing. Sequence order remains review-required where stated in each FLOWER.json.</p><p>Four folders: <code>01_FLOWER_SEQUENCES</code>, <code>02_STATIONS</code>, <code>03_SUBSEQUENCES</code>, <code>04_ROLLERS</code>.</p><p><a href='FILE_LOCATIONS.json'>Exact file locations (JSON)</a> · <a href='FILE_LOCATIONS.csv'>Exact file locations (CSV)</a></p><h2>Extracted flower sequences</h2><table><thead><tr><th>Flower</th><th>Stations</th><th>3-pass subsequences</th><th>Roller files</th><th>Open</th></tr></thead><tbody>{verified}</tbody></table><h2>Source drawings requiring extraction/review</h2><ul>{review}</ul></body></html>"""


def _location_metadata(output_root: Path, staging: Path) -> list[dict[str, Any]]:
    category_names = {
        "01_FLOWER_SEQUENCES": "FLOWER_SEQUENCE",
        "02_STATIONS": "STATION",
        "03_SUBSEQUENCES": "SUBSEQUENCE",
        "04_ROLLERS": "ROLLER_EVIDENCE",
    }
    locations = []
    for path in sorted(item for item in staging.rglob("*") if item.is_file()):
        relative = path.relative_to(staging)
        if relative.name in {"INDEX.json", "INDEX.html", "FILE_LOCATIONS.json", "FILE_LOCATIONS.csv"}:
            continue
        parts = relative.parts
        flower_id = parts[1] if len(parts) > 1 and parts[1] != "REVIEW_REQUIRED" else None
        source_id = parts[2] if len(parts) > 2 and parts[1] == "REVIEW_REQUIRED" else None
        station_label = next((part for part in parts if part.startswith("STATION-")), None)
        subsequence_label = next((part for part in parts if part.startswith("SUBSEQUENCE-")), None)
        locations.append({
            "category": category_names.get(parts[0], "OTHER"),
            "flower_id": flower_id,
            "source_id": source_id,
            "station_label": station_label,
            "subsequence_label": subsequence_label,
            "filename": path.name,
            "relative_path": relative.as_posix(),
            "absolute_path": str(output_root / relative),
            "sha256": _digest_file(path),
            "size_bytes": path.stat().st_size,
            "visibility": "PRIVATE_LOCAL_ONLY",
        })
    return locations


def _write_location_indexes(staging: Path, locations: list[dict[str, Any]]) -> None:
    _write_json(staging / "FILE_LOCATIONS.json", {
        "schema_version": LIBRARY_SCHEMA_VERSION,
        "visibility": "PRIVATE_LOCAL_ONLY",
        "file_count": len(locations),
        "files": locations,
    })
    fields = ["category", "flower_id", "source_id", "station_label", "subsequence_label", "filename", "relative_path", "absolute_path", "sha256", "size_bytes", "visibility"]
    with (staging / "FILE_LOCATIONS.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(locations)


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
            "exact_file_locations_json": str(output_root / "FILE_LOCATIONS.json"),
            "exact_file_locations_csv": str(output_root / "FILE_LOCATIONS.csv"),
        }
        locations = _location_metadata(output_root, staging)
        _write_location_indexes(staging, locations)
        index["indexed_file_count"] = len(locations)
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
