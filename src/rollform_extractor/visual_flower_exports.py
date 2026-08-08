"""Customer-safe visual candidate exports."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import ezdxf
from PIL import Image, ImageDraw


def export_visual_run(result: dict, output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    payload = json.dumps(result, indent=2, sort_keys=True)
    (output / "visual_run.json").write_text(payload, encoding="utf-8")
    files["visual_run.json"] = _hash(output / "visual_run.json")

    rows = []
    for candidate in result.get("candidates", []):
        candidate_constraint = candidate.get("geometry_constraints") or {}
        for item in candidate.get("passes", []):
            match = item.get("historical_match", {}).get("best_match") or {}
            confidence = item.get("visual_confidence", {})
            strip_constraint = (
                item.get("generation", {}).get("strip_length_constraint") or {}
            )
            rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "pass_id": item["pass_id"],
                    "order": item["order"],
                    "progress": item["progress"],
                    "visual_confidence": confidence.get("score"),
                    "confidence_band": confidence.get("band"),
                    "best_source_flower": match.get("source_flower_id"),
                    "best_source_pass": match.get("source_pass_id"),
                    "best_visual_similarity": match.get("overall_score"),
                    "evidence_coverage": match.get("evidence_coverage"),
                    "generation_class": item.get("generation", {})
                    .get("transformation", {})
                    .get("support"),
                    "target_strip_length": strip_constraint.get(
                        "target_length",
                        candidate_constraint.get("target_length"),
                    ),
                    "actual_strip_length": strip_constraint.get("actual_length"),
                    "strip_length_relative_error": strip_constraint.get(
                        "relative_error"
                    ),
                    "strip_length_satisfied": strip_constraint.get("satisfied"),
                    "strip_length_method": strip_constraint.get("method"),
                    "warnings": ";".join(item.get("warnings", [])),
                }
            )
    with (output / "passes.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]) if rows else ["candidate_id"],
        )
        writer.writeheader()
        writer.writerows(rows)
    files["passes.csv"] = _hash(output / "passes.csv")

    for candidate in result.get("candidates", []):
        directory = output / candidate["candidate_id"]
        directory.mkdir(exist_ok=True)
        dxf = directory / "combined.dxf"
        _write_dxf(candidate, dxf)
        files[str(dxf.relative_to(output))] = _hash(dxf)
        svg = directory / "combined.svg"
        svg.write_text(_svg(candidate), encoding="utf-8")
        files[str(svg.relative_to(output))] = _hash(svg)
        report = directory / "report.html"
        report.write_text(_html(candidate), encoding="utf-8")
        files[str(report.relative_to(output))] = _hash(report)
        png = directory / "contact-sheet.png"
        _write_contact_sheet(candidate, png)
        files[str(png.relative_to(output))] = _hash(png)
        for index, item in enumerate(candidate.get("passes", []), start=1):
            pass_dxf = directory / "passes" / f"pass-{index:03d}.dxf"
            pass_dxf.parent.mkdir(exist_ok=True)
            _write_pass_dxf(item, pass_dxf)
            files[str(pass_dxf.relative_to(output))] = _hash(pass_dxf)

    zip_path = output / "visual_flower_export.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in output.rglob("*"):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(output))
    files[zip_path.name] = _hash(zip_path)

    constraints = [
        candidate.get("geometry_constraints") or {}
        for candidate in result.get("candidates", [])
    ]
    constant_length_satisfied = bool(constraints) and all(
        item.get("enabled") and item.get("satisfied") for item in constraints
    )
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "files": files,
                "private_source_included": False,
                "constant_strip_length": {
                    "enabled": bool(constraints),
                    "all_candidates_satisfied": constant_length_satisfied,
                    "reference": "FINAL_TARGET_CENTERLINE",
                    "coordinate_space": "CANONICAL_VISUAL_UNITS",
                },
                "safety_boundary": (
                    "Visual prototype only; not manufacturing approval."
                ),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return files


def verify_visual_export(output: Path) -> dict[str, object]:
    """Verify customer-safe artifacts without reading any source CAD."""
    required = [
        "visual_run.json",
        "passes.csv",
        "manifest.json",
        "visual_flower_export.zip",
    ]
    files = {
        name: (output / name).is_file() and (output / name).stat().st_size > 0
        for name in required
    }
    candidate_dirs = (
        [path for path in output.iterdir() if path.is_dir()]
        if output.is_dir()
        else []
    )
    artifacts = [
        path
        for directory in candidate_dirs
        for path in directory.rglob("*")
        if path.is_file()
    ]
    checks: dict[str, bool] = {
        "required_files": all(files.values()),
        "nonzero_artifacts": all(path.stat().st_size > 0 for path in artifacts),
    }

    try:
        payload = json.loads(
            (output / "visual_run.json").read_text(encoding="utf-8")
        )
        checks["json_schema"] = isinstance(payload, dict) and "candidates" in payload
        checks["safety_boundary"] = (
            "manufacturing" in json.dumps(payload).lower()
            or payload.get("source_cad_included") is False
        )
        candidates = payload.get("candidates", [])
        checks["constant_strip_length"] = bool(candidates) and all(
            (candidate.get("geometry_constraints") or {}).get("satisfied") is True
            for candidate in candidates
        )
    except (OSError, json.JSONDecodeError):
        checks["json_schema"] = False
        checks["safety_boundary"] = False
        checks["constant_strip_length"] = False

    csv_path = output / "passes.csv"
    csv_header = (
        csv_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        if csv_path.is_file()
        else ""
    )
    checks["csv_headers"] = (
        "candidate_id" in csv_header
        and "strip_length_satisfied" in csv_header
        and "strip_length_relative_error" in csv_header
    )

    svg_paths = list(output.glob("*/combined.svg"))
    try:
        for path in svg_paths:
            ET.fromstring(path.read_text(encoding="utf-8"))
        checks["svg_parses"] = bool(svg_paths)
    except (OSError, ET.ParseError):
        checks["svg_parses"] = False

    png_paths = list(output.glob("*/contact-sheet.png"))
    checks["png_signature"] = bool(png_paths) and all(
        path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in png_paths
    )

    dxf_paths = list(output.glob("*/combined.dxf"))
    try:
        for path in dxf_paths:
            doc = ezdxf.readfile(path)
            layers = {entity.dxf.layer for entity in doc.modelspace()}
            checks["dxf_layers"] = (
                "GENERATED_PROFILE" in layers and "STATION_LABEL" in layers
            )
    except (OSError, ezdxf.DXFError):
        checks["dxf_layers"] = False
    if "dxf_layers" not in checks:
        checks["dxf_layers"] = False

    try:
        with ZipFile(output / "visual_flower_export.zip") as archive:
            names = archive.namelist()
            checks["zip_members"] = any(
                name.endswith("combined.dxf") for name in names
            ) and any(name.endswith("report.html") for name in names)
            checks["zip_private_safe"] = not any(
                "/home/" in name or name.lower().endswith(".dwg")
                for name in names
            )
    except (OSError, KeyError, BadZipFile):
        checks["zip_members"] = False
        checks["zip_private_safe"] = False

    text = "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in output.glob("*/report.html")
    )
    checks["html_safety_boundary"] = (
        "not manufacturing" in text.lower() and "physical roller" in text.lower()
    )
    checks["html_strip_length"] = "strip length" in text.lower()
    checks["no_private_paths"] = (
        "/home/pd/" not in text and "rollform-private" not in text
    )
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "files": files,
        "artifact_count": len(artifacts),
    }


def _write_dxf(candidate, path):
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    for index, item in enumerate(candidate.get("passes", []), start=1):
        points = [
            (float(point[0]) + index * 5, float(point[1]))
            for point in item["profile"]["points"]
        ]
        if points:
            modelspace.add_lwpolyline(
                points,
                close=item["profile"].get("topology") == "CLOSED_CONTOUR",
                dxfattribs={"layer": "GENERATED_PROFILE"},
            )
            modelspace.add_text(
                f"Station {index}",
                dxfattribs={"layer": "STATION_LABEL", "height": 1},
            ).set_placement((index * 5, 0))
    doc.saveas(path)


def _write_pass_dxf(item, path):
    doc = ezdxf.new("R2018")
    modelspace = doc.modelspace()
    points = [
        (float(point[0]), float(point[1]))
        for point in item.get("profile", {}).get("points", [])
    ]
    if points:
        modelspace.add_lwpolyline(
            points,
            close=item.get("profile", {}).get("topology") == "CLOSED_CONTOUR",
            dxfattribs={"layer": "GENERATED_PROFILE"},
        )
    doc.saveas(path)


def _write_contact_sheet(candidate, path: Path) -> None:
    width, height = 960, 640
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    passes = candidate.get("passes", [])
    cols = 4
    rows = max(1, (len(passes) + cols - 1) // cols)
    cell_w, cell_h = width // cols, height // rows
    for index, item in enumerate(passes):
        points = [
            (float(point[0]), float(point[1]))
            for point in item.get("profile", {}).get("points", [])
        ]
        if points:
            min_x, max_x = min(point[0] for point in points), max(
                point[0] for point in points
            )
            min_y, max_y = min(point[1] for point in points), max(
                point[1] for point in points
            )
            sx = (cell_w - 24) / max(max_x - min_x, 1e-9)
            sy = (cell_h - 40) / max(max_y - min_y, 1e-9)
            scale = min(sx, sy)
            origin_x = (index % cols) * cell_w + 12
            origin_y = (index // cols) * cell_h + 24
            projected = [
                (
                    origin_x + (x - min_x) * scale,
                    origin_y + cell_h - 28 - (y - min_y) * scale,
                )
                for x, y in points
            ]
            if len(projected) > 1:
                draw.line(projected, fill="#155783", width=2)
        strip_constraint = (
            item.get("generation", {}).get("strip_length_constraint") or {}
        )
        length_text = (
            f"L={float(strip_constraint.get('actual_length')):.3f}"
            if strip_constraint.get("actual_length") is not None
            else "L=n/a"
        )
        draw.text(
            (
                (index % cols) * cell_w + 8,
                (index // cols) * cell_h + 6,
            ),
            (
                f"Pass {item.get('order')}  "
                f"{float(item.get('visual_confidence', {}).get('score', 0)):.1f}  "
                f"{length_text}"
            ),
            fill="#17202a",
        )
    image.save(path, format="PNG")


def _svg(candidate):
    paths = []
    for index, item in enumerate(candidate.get("passes", []), start=1):
        points = " ".join(
            f"{float(point[0]) + index * 5:.5f},{-float(point[1]):.5f}"
            for point in item["profile"]["points"]
        )
        paths.append(
            f"<polyline points='{points}' fill='none' "
            "stroke='#155783' stroke-width='.02'/>"
        )
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='-3 -3 160 12'>"
        "<title>Visual prototype candidate with constant centerline strip length</title>"
        + "".join(paths)
        + "</svg>"
    )


def _html(candidate):
    constraint = candidate.get("geometry_constraints") or {}
    rows = "".join(
        (
            "<tr>"
            f"<td>{item['order']}</td>"
            f"<td>{item['visual_confidence']['score']:.2f}</td>"
            f"<td>{html.escape(str((item.get('historical_match', {}).get('best_match') or {}).get('source_pass_id', 'none')))}</td>"
            f"<td>{html.escape(str((item.get('generation', {}).get('strip_length_constraint') or {}).get('actual_length', 'n/a')))}</td>"
            f"<td>{html.escape(str((item.get('generation', {}).get('strip_length_constraint') or {}).get('relative_error', 'n/a')))}</td>"
            "</tr>"
        )
        for item in candidate.get("passes", [])
    )
    return (
        "<!doctype html><meta charset='utf-8'><title>Visual flower candidate</title>"
        "<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:.4rem}"
        ".notice{background:#fff3cd;padding:1rem}</style>"
        "<h1>Visual Flower Generator</h1>"
        "<p class='notice'><strong>Visual prototype only.</strong> Similarity and confidence "
        "refer to geometry appearance, not manufacturing feasibility or physical roller availability.</p>"
        f"<h2>{html.escape(candidate['candidate_id'])}</h2>"
        f"<p>Visual confidence: {candidate['visual_confidence']['score']:.2f} "
        f"({html.escape(candidate['visual_confidence']['band'])})</p>"
        "<p><strong>Strip length constraint:</strong> final-target centerline in canonical visual units; "
        f"satisfied={html.escape(str(constraint.get('satisfied', False)))}; "
        f"target={html.escape(str(constraint.get('target_length', 'n/a')))}; "
        f"max relative error={html.escape(str(constraint.get('maximum_relative_error', 'n/a')))}.</p>"
        "<p>This centerline constraint does not model neutral-axis shift, thinning, springback, "
        "material strain, tooling contact, or manufacturing feasibility.</p>"
        "<table><tr><th>Station</th><th>Visual confidence</th><th>Historical match</th>"
        f"<th>Strip length</th><th>Relative error</th></tr>{rows}</table>"
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
