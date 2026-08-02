#!/usr/bin/env python3
"""Compare two extraction projects using canonical semantic snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rollform_extractor.determinism import compare_project_snapshots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record", type=Path, help="record the passing comparison in this project and refresh its manifest")
    args = parser.parse_args()
    result = compare_project_snapshots(args.left, args.right)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.record:
        if not result["equal"]:
            raise SystemExit("refusing to record a failed determinism comparison")
        summary_path = args.record / "determinism_summary.json"
        summary_path.write_text(encoded + "\n", encoding="utf-8")
        manifest_path = args.record / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("files", {})["determinism_summary.json"] = {
            "sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
            "bytes": summary_path.stat().st_size,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(encoded)
    return 0 if result["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
