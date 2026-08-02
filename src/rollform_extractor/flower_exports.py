"""Redacted, offline exports for the history-constrained prototype."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

import ezdxf
import matplotlib.pyplot as plt

from rollform_extractor.flower_generation import GeneratedCandidate
from rollform_extractor.flower_prototype_dataset import FlowerPrototypeDataset
from rollform_extractor.flower_reconstruction_benchmark import benchmark_dataset


def export_prototype_dataset(dataset: FlowerPrototypeDataset, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    (output / "dataset.json").write_text(json.dumps(dataset.to_dict(include_geometry=True), indent=2, sort_keys=True), encoding="utf-8")
    summary = {
        "schema_version": dataset.to_dict()["schema_version"],
        "dataset_id": dataset.dataset_id,
        "dataset_hash": dataset.dataset_hash,
        "source_classification": dataset.source_classification,
        "flowers": [{"flower_id": f.flower_id, "station_count": len(f.passes), "topology": f.topology, "quality_flags": list(f.quality_flags)} for f in dataset.flowers],
        "roller_evidence_count": len(dataset.roller_evidence),
        "private_source_paths_redacted": True,
    }
    (output / "run_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return output


def export_generation(candidates: tuple[GeneratedCandidate, ...], output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    (output / "retrieval_results.json").write_text(json.dumps([c.retrieval.to_dict() for c in candidates], indent=2, sort_keys=True), encoding="utf-8")
    (output / "validation_summary.json").write_text(json.dumps([c.validation for c in candidates], indent=2, sort_keys=True), encoding="utf-8")
    (output / "candidates.json").write_text(json.dumps([c.to_dict() for c in candidates], indent=2, sort_keys=True), encoding="utf-8")
    with (output / "candidate_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["candidate_id", "candidate_type", "source_flower_id", "station_count", "status", "confidence", "shape_rms", "developed_length_relative_error"])
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({"candidate_id": candidate.candidate_id, "candidate_type": candidate.candidate_type, "source_flower_id": candidate.source_flower_id, "station_count": candidate.station_count, "status": candidate.status, "confidence": candidate.confidence, "shape_rms": candidate.validation.get("shape_rms"), "developed_length_relative_error": candidate.validation.get("developed_length_relative_error")})
    for candidate in candidates:
        candidate_dir = output / "candidates" / candidate.candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "candidate.json").write_text(json.dumps(candidate.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        _write_candidate_dxf(candidate, candidate_dir / "combined_flower.dxf")
        _write_candidate_png(candidate, candidate_dir / "combined_flower.png")
    (output / "report.html").write_text(_generation_html(candidates), encoding="utf-8")
    return output


def _write_candidate_dxf(candidate: GeneratedCandidate, path: Path) -> None:
    document = ezdxf.new("R2018")
    modelspace = document.modelspace()
    for index, item in enumerate(candidate.passes):
        points = [(item.shape_vector[offset] + index * 4.0, item.shape_vector[offset + 1]) for offset in range(0, len(item.shape_vector), 2)]
        if points:
            modelspace.add_lwpolyline(points, close=True, dxfattribs={"layer": "GENERATED_CANDIDATE"})
    document.saveas(path)


def _write_candidate_png(candidate: GeneratedCandidate, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(12, 5))
    for index, item in enumerate(candidate.passes):
        points = [(item.shape_vector[offset] + index * 4.0, item.shape_vector[offset + 1]) for offset in range(0, len(item.shape_vector), 2)]
        if points:
            x, y = zip(*(points + [points[0]]))
            axis.plot(x, y, linewidth=0.7)
    axis.set_title("Historically grounded candidate - engineer review only")
    axis.set_aspect("equal", adjustable="datalim")
    axis.axis("off")
    figure.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(figure)


def export_benchmark(flowers, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    evidence = benchmark_dataset(tuple(flowers))
    (output / "benchmark.json").write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return output


def _generation_html(candidates: tuple[GeneratedCandidate, ...]) -> str:
    rows = "".join(f"<tr><td>{html.escape(c.candidate_id)}</td><td>{html.escape(c.candidate_type)}</td><td>{c.station_count}</td><td>{html.escape(c.status)}</td><td>{c.confidence:.3f}</td><td>{c.validation.get('shape_rms', 0):.5f}</td></tr>" for c in candidates)
    return f"""<!doctype html><html lang='en'><meta charset='utf-8'><title>Flower prototype evidence</title><style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:.5rem;text-align:left}}.notice{{padding:1rem;background:#fff3cd;border-left:4px solid #b58105}}</style><h1>History-constrained flower prototype</h1><p class='notice'><strong>Historically grounded flower-sequence candidate for engineer review.</strong> This is not production approval, a tooling recommendation, or physical roller availability.</p><h2>Generated candidates</h2><table><thead><tr><th>ID</th><th>Type</th><th>Stations</th><th>Status</th><th>Confidence</th><th>Shape RMS</th></tr></thead><tbody>{rows}</tbody></table></html>"""
