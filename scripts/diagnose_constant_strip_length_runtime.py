#!/usr/bin/env python3
"""Measure local CLRSG post-projection compatibility without exporting private geometry."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from statistics import mean

from rollform_extractor.clrsg_inference import infer_learned_candidates
from rollform_extractor.clrsg_model import load_clrsg_model
from rollform_extractor.strip_length_constraint import (
    STRIP_LENGTH_RELATIVE_TOLERANCE,
)
from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


def _profile_from_final_pass(flower: dict, index: int) -> dict:
    points = flower["passes"][-1]["points"]
    source_topology = str(flower.get("topology") or "OPEN_PATH")
    topology = (
        "CLOSED_CONTOUR"
        if source_topology in {"CLOSED_CONTOUR", "CLOSED_SINGLE_LOOP"}
        else "OPEN_PATH"
    )
    vertices = [
        {"vertex_id": f"p-{point_index:03d}", "x": point[0], "y": point[1]}
        for point_index, point in enumerate(points)
    ]
    pairs = list(zip(vertices, vertices[1:]))
    if topology == "CLOSED_CONTOUR":
        pairs.append((vertices[-1], vertices[0]))
    segments = [
        {
            "segment_id": f"s-{segment_index:03d}",
            "type": "LINE",
            "start_vertex_id": start["vertex_id"],
            "end_vertex_id": end["vertex_id"],
        }
        for segment_index, (start, end) in enumerate(pairs)
    ]
    return {
        "schema_version": 1,
        "profile_id": f"private-runtime-target-{index:03d}",
        "name": f"Private runtime target {index}",
        "topology": topology,
        "closed": topology == "CLOSED_CONTOUR",
        "computational_seam_vertex_id": vertices[0]["vertex_id"]
        if topology == "CLOSED_CONTOUR"
        else None,
        "vertices": vertices,
        "segments": segments,
        "metadata": {"source": "PRIVATE_LOCAL_RUNTIME", "visual_only": True},
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _visual_dataset(dataset: dict) -> dict:
    """Map extraction topology vocabulary into the visual-only contract in memory."""
    value = deepcopy(dataset)
    for flower in value.get("flowers", []):
        if flower.get("topology") == "CLOSED_SINGLE_LOOP":
            flower["topology"] = "CLOSED_CONTOUR"
        for item in flower.get("passes", []):
            if item.get("topology") == "CLOSED_SINGLE_LOOP":
                item["topology"] = "CLOSED_CONTOUR"
    return value


def diagnose(dataset: dict, model, station_counts: tuple[int, ...]) -> dict:
    visual_dataset = _visual_dataset(dataset)
    projection_rms: list[float] = []
    relative_errors: list[float] = []
    rows: list[dict] = []
    learned_count = fallback_count = final_exact_count = non_finite_count = topology_failure_count = 0
    run_count = 0

    for target_index, flower in enumerate(dataset.get("flowers", []), start=1):
        profile = validate_profile(_profile_from_final_pass(flower, target_index))
        canonical_target = canonicalize_profile(profile, samples=256)["points"]
        for station_count in station_counts:
            baseline = generate_visual_candidates(
                profile,
                visual_dataset.get("flowers", []),
                station_mode="EXACT",
                exact_station_count=station_count,
                candidate_limit=3,
                allow_mirror_matching=True,
                allow_rotation_alignment=True,
            )
            learned = infer_learned_candidates(profile, baseline, model)
            run_count += 1
            learned_candidates = learned.get("candidates", [])
            learned_count += len(learned_candidates)
            max_error = 0.0
            for candidate in learned_candidates:
                if candidate.get("status") == "LEARNED_SEQUENCE_FALLBACK":
                    fallback_count += 1
                if candidate.get("passes", [])[-1].get("profile", {}).get("points") == canonical_target:
                    final_exact_count += 1
                else:
                    topology_failure_count += 1
                for item in candidate.get("passes", []):
                    points = item.get("profile", {}).get("points", [])
                    if not all(math.isfinite(float(value)) for point in points for value in point):
                        non_finite_count += 1
                    evidence = item.get("generation", {}).get("strip_length_constraint", {})
                    projection_rms.append(float(evidence.get("projection_rms", 0.0)))
                    relative_error = float(evidence.get("relative_error", 1.0))
                    relative_errors.append(relative_error)
                    max_error = max(max_error, relative_error)
            rows.append(
                {
                    "target_index": target_index,
                    "station_count": station_count,
                    "learned_candidate_count": len(learned_candidates),
                    "maximum_relative_error": max_error,
                    "all_constraints_satisfied": bool(learned_candidates)
                    and max_error <= STRIP_LENGTH_RELATIVE_TOLERANCE,
                }
            )

    return {
        "schema_version": 1,
        "classification": "PRIVATE_LOCAL_ONLY",
        "geometry_exported": False,
        "sample_count": len(dataset.get("flowers", [])),
        "station_counts_tested": list(station_counts),
        "run_count": run_count,
        "learned_candidate_count": learned_count,
        "all_length_constraints_satisfied": bool(relative_errors)
        and max(relative_errors) <= STRIP_LENGTH_RELATIVE_TOLERANCE,
        "maximum_length_relative_error": max(relative_errors, default=0.0),
        "mean_projection_rms": mean(projection_rms) if projection_rms else 0.0,
        "p95_projection_rms": _percentile(projection_rms, 0.95),
        "maximum_projection_rms": max(projection_rms, default=0.0),
        "learned_candidate_availability_rate": learned_count / max(1, run_count * 4),
        "fallback_rate": fallback_count / max(1, learned_count),
        "final_target_exact_rate": final_exact_count / max(1, learned_count),
        "non_finite_count": non_finite_count,
        "topology_failure_count": topology_failure_count,
        "rows": rows,
        "note": "Projection RMS is visual geometry correction magnitude, not manufacturing error.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stations", default="8,16,28")
    args = parser.parse_args()
    station_counts = tuple(int(value) for value in args.stations.split(","))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    result = diagnose(dataset, load_clrsg_model(args.model), station_counts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, sort_keys=True))
    return 0 if result["all_length_constraints_satisfied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
