"""Customer-safe visual candidate exports."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import ezdxf


def export_visual_run(result: dict, output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    payload = json.dumps(result, indent=2, sort_keys=True)
    (output / "visual_run.json").write_text(payload, encoding="utf-8"); files["visual_run.json"] = _hash(output / "visual_run.json")
    rows = []
    for candidate in result.get("candidates", []):
        for item in candidate.get("passes", []):
            match = item.get("historical_match", {}).get("best_match") or {}
            confidence = item.get("visual_confidence", {})
            rows.append({"candidate_id": candidate["candidate_id"], "pass_id": item["pass_id"], "order": item["order"], "progress": item["progress"], "visual_confidence": confidence.get("score"), "confidence_band": confidence.get("band"), "best_source_flower": match.get("source_flower_id"), "best_source_pass": match.get("source_pass_id"), "best_visual_similarity": match.get("overall_score"), "evidence_coverage": match.get("evidence_coverage"), "generation_class": item.get("generation", {}).get("transformation", {}).get("support"), "warnings": ";".join(item.get("warnings", []))})
    with (output / "passes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["candidate_id"]); writer.writeheader(); writer.writerows(rows)
    files["passes.csv"] = _hash(output / "passes.csv")
    for candidate in result.get("candidates", []):
        directory = output / candidate["candidate_id"]; directory.mkdir(exist_ok=True)
        dxf = directory / "combined.dxf"; _write_dxf(candidate, dxf); files[str(dxf.relative_to(output))] = _hash(dxf)
        svg = directory / "combined.svg"; svg.write_text(_svg(candidate), encoding="utf-8"); files[str(svg.relative_to(output))] = _hash(svg)
        report = directory / "report.html"; report.write_text(_html(candidate), encoding="utf-8"); files[str(report.relative_to(output))] = _hash(report)
    zip_path = output / "visual_flower_export.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in output.rglob("*"):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(output))
    files[zip_path.name] = _hash(zip_path)
    (output / "manifest.json").write_text(json.dumps({"files": files, "private_source_included": False, "safety_boundary": "Visual prototype only; not manufacturing approval."}, indent=2, sort_keys=True), encoding="utf-8")
    return files


def _write_dxf(candidate, path):
    doc = ezdxf.new("R2018"); modelspace = doc.modelspace()
    for index, item in enumerate(candidate.get("passes", []), start=1):
        points = [(float(point[0]) + index * 5, float(point[1])) for point in item["profile"]["points"]]
        if points:
            modelspace.add_lwpolyline(points, close=item["profile"].get("topology") == "CLOSED_CONTOUR", dxfattribs={"layer": "GENERATED_PROFILE"})
            modelspace.add_text(f"Station {index}", dxfattribs={"layer": "STATION_LABEL", "height": 1}).set_placement((index * 5, 0))
    doc.saveas(path)


def _svg(candidate):
    paths = []
    for index, item in enumerate(candidate.get("passes", []), start=1):
        points = " ".join(f"{float(p[0]) + index * 5:.5f},{-float(p[1]):.5f}" for p in item["profile"]["points"])
        paths.append(f"<polyline points='{points}' fill='none' stroke='#155783' stroke-width='.02'/>")
    return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='-3 -3 160 12'><title>Visual prototype candidate</title>" + "".join(paths) + "</svg>"


def _html(candidate):
    rows = "".join(f"<tr><td>{item['order']}</td><td>{item['visual_confidence']['score']:.2f}</td><td>{html.escape(str((item.get('historical_match',{}).get('best_match') or {}).get('source_pass_id','none')))}</td></tr>" for item in candidate.get("passes", []))
    return f"<!doctype html><meta charset='utf-8'><title>Visual flower candidate</title><style>body{{font:16px system-ui;max-width:1000px;margin:2rem auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:.4rem}}.notice{{background:#fff3cd;padding:1rem}}</style><h1>Visual Flower Generator</h1><p class='notice'><strong>Visual prototype only.</strong> Similarity and confidence refer to geometry appearance, not manufacturing feasibility or physical roller availability.</p><h2>{html.escape(candidate['candidate_id'])}</h2><p>Visual confidence: {candidate['visual_confidence']['score']:.2f} ({html.escape(candidate['visual_confidence']['band'])})</p><table><tr><th>Station</th><th>Visual confidence</th><th>Historical match</th></tr>{rows}</table>"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
