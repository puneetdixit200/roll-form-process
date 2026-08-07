#!/usr/bin/env python3
"""Benchmark public procedural visual generation without private model data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from rollform_extractor.visual_flower_engine import generate_visual_candidates
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "visual_flower_golden"
    timings = []
    for station_count, fixture_name in ((8, "OPEN_U_CHANNEL_SMALL.json"), (16, "OPEN_U_CHANNEL_MEDIUM.json"), (28, "OPEN_U_CHANNEL_LARGE.json")):
        profile = validate_profile(json.loads((root / fixture_name).read_text(encoding="utf-8")))
        canonical = canonicalize_profile(profile, samples=256)["points"]
        history = [{"flower_id": "PUBLIC-GOLDEN-HISTORY", "topology": profile.topology, "passes": [{"pass_id": f"PUBLIC-PASS-{index:03d}", "topology": profile.topology, "shape_vector": [value for point in canonical for value in point], "width": 1.0, "height": 1.0} for index in range(station_count)]}]
        samples = []
        # One representative run per count keeps the release check bounded;
        # the geometry matcher is deterministic and can be profiled deeper
        # outside CI when needed.
        for _ in range(1):
            started = perf_counter(); result = generate_visual_candidates(profile, history, station_mode="EXACT", exact_station_count=station_count, candidate_limit=1); elapsed = perf_counter() - started
            assert result["candidates"] and len(result["candidates"][0]["passes"]) == station_count
            samples.append(elapsed)
        timings.append({"station_count": station_count, "mean_seconds": mean(samples), "median_seconds": median(samples), "p95_seconds": sorted(samples)[-1], "maximum_seconds": max(samples), "preferred_threshold_seconds": 2.0 if station_count == 16 else 4.0})
    values = [item["p95_seconds"] for item in timings]
    result = {"schema_version": 1, "classification": "PUBLIC_SYNTHETIC_TEST", "timings": timings, "status": "PASS" if timings[1]["p95_seconds"] < 2.0 and timings[2]["p95_seconds"] < 4.0 else "WARN", "total_mean_seconds": mean(values)}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
