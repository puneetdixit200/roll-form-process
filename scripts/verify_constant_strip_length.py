#!/usr/bin/env python3
"""Verify constant centerline strip length in a visual flower JSON export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rollform_extractor.strip_length_constraint import (
    STRIP_LENGTH_RELATIVE_TOLERANCE,
    centerline_length,
)


def verify(payload: dict, tolerance: float) -> dict:
    rows = []
    passed = True
    for candidate in payload.get("candidates", []):
        passes = candidate.get("passes", [])
        if not passes:
            rows.append({"candidate_id": candidate.get("candidate_id"), "status": "NO_PASSES"})
            passed = False
            continue
        topology = passes[-1].get("profile", {}).get("topology", "OPEN_PATH")
        target_points = passes[-1].get("profile", {}).get("points", [])
        target_length = centerline_length(target_points, topology)
        maximum_relative_error = 0.0
        pass_rows = []
        for item in passes:
            points = item.get("profile", {}).get("points", [])
            actual_length = centerline_length(points, topology)
            relative_error = abs(actual_length - target_length) / max(target_length, 1e-12)
            maximum_relative_error = max(maximum_relative_error, relative_error)
            metadata = item.get("generation", {}).get("strip_length_constraint") or {}
            pass_rows.append(
                {
                    "order": item.get("order"),
                    "actual_length": actual_length,
                    "relative_error": relative_error,
                    "metadata_satisfied": metadata.get("satisfied"),
                }
            )
        candidate_passed = maximum_relative_error <= tolerance
        passed = passed and candidate_passed
        rows.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "candidate_style": candidate.get("candidate_style"),
                "topology": topology,
                "station_count": len(passes),
                "target_length": target_length,
                "maximum_relative_error": maximum_relative_error,
                "tolerance": tolerance,
                "status": "PASS" if candidate_passed else "FAIL",
                "passes": pass_rows,
            }
        )
    return {
        "status": "PASS" if passed and rows else "FAIL",
        "constraint": "FINAL_TARGET_CENTERLINE_LENGTH",
        "coordinate_space": "CANONICAL_VISUAL_UNITS",
        "relative_tolerance": tolerance,
        "candidates": rows,
        "manufacturing_approval": "NOT_APPROVED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", type=Path, help="visual_run.json or generation response JSON")
    parser.add_argument("--tolerance", type=float, default=STRIP_LENGTH_RELATIVE_TOLERANCE)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
        result = verify(payload, args.tolerance)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
