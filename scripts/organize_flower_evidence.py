#!/usr/bin/env python3
"""Create the private local four-folder flower evidence library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rollform_extractor.flower_evidence_organizer import build_flower_evidence_library


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = build_flower_evidence_library(args.manifest, args.output)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output.expanduser().resolve()),
        "verified_flower_count": len(result["verified_flowers"]),
        "review_required_source_count": len(result["review_required_sources"]),
        "station_count": sum(item["station_count"] for item in result["verified_flowers"]),
        "subsequence_count": sum(item["subsequence_count"] for item in result["verified_flowers"]),
        "roller_evidence_count": sum(item["roller_evidence_count"] for item in result["verified_flowers"]),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
