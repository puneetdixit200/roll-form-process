#!/usr/bin/env python3
"""Generate public procedural golden profiles; never reads private data."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "visual_flower_golden"


def profile(fixture_id: str, family: str, scale: float, closed: bool, negative: bool, stations: int) -> dict:
    if closed:
        base = [(-2, -1), (0, -1), (2, -1), (2, 1), (0, 1), (-2, 1), (-2, -1)]
    elif family == "OPEN_Z_PROFILE":
        base = [(-3, 1), (-1, 1), (1, -1), (3, -1)]
    elif family == "OPEN_CURVED_WAVE":
        base = [(-3, 0), (-2, 1), (-1, 0), (0, -1), (1, 0), (2, 1), (3, 0)]
    elif family == "OPEN_STEP_PROFILE":
        base = [(-3, 0), (-2, 0), (-2, 1), (-1, 1), (-1, 0), (0, 0), (0, 1), (1, 1), (1, 0), (3, 0)]
    elif family == "OPEN_ASYMMETRIC_CHANNEL":
        base = [(-3, 0), (-2, 1), (-1, 1), (0, 0), (1, -1), (3, -1)]
    elif family == "OPEN_MIXED_LINE_ARC":
        base = [(-3, 0), (-2, 1), (-1, 1), (0, 0), (1, -1), (3, -1)]
    else:
        base = [(-3, 0), (-2, 1), (0, 1), (1, 0), (2, -1), (3, -1)]
    if negative:
        base = [(x, y + (0.35 if index % 2 else -0.35)) for index, (x, y) in enumerate(base)]
    vertices = [{"vertex_id": f"{fixture_id}-v{index}", "x": round(x * scale, 5), "y": round(y * scale, 5)} for index, (x, y) in enumerate(base)]
    segments = [{"segment_id": f"{fixture_id}-s{index}", "type": "LINE", "start_vertex_id": vertices[index]["vertex_id"], "end_vertex_id": vertices[index + 1]["vertex_id"]} for index in range(len(vertices) - 1)]
    return {"schema_version": 1, "profile_id": fixture_id, "name": f"Public golden {family} {scale:g}", "topology": "CLOSED_CONTOUR" if closed else "OPEN_PATH", "closed": closed, "computational_seam_vertex_id": vertices[0]["vertex_id"] if closed else None, "vertices": vertices, "segments": segments, "metadata": {"source": "PUBLIC_SYNTHETIC_TEST", "visual_only": True, "family": family, "requested_station_count": stations, "expected_engine": "DETERMINISTIC_FALLBACK_OR_LEARNED", "expected_ood_class": "OUT_OF_DISTRIBUTION" if negative else "IN_DISTRIBUTION", "negative_probe": negative}}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    families = ["OPEN_U_CHANNEL", "OPEN_C_CHANNEL", "OPEN_Z_PROFILE", "OPEN_HAT_PROFILE", "OPEN_STEP_PROFILE", "OPEN_ASYMMETRIC_CHANNEL", "OPEN_CURVED_WAVE", "OPEN_MIXED_LINE_ARC", "CLOSED_ROUNDED_RECTANGLE", "CLOSED_ASYMMETRIC_LOOP"]
    entries = []
    for family_index, family in enumerate(families):
        closed = family.startswith("CLOSED_")
        for variant, scale in zip(("SMALL", "MEDIUM", "LARGE"), (0.7, 1.0, 1.35)):
            fixture_id = f"{family}_{variant}"
            stations = (8, 16, 28)[(family_index + int(scale * 10)) % 3]
            payload = profile(fixture_id, family, scale, closed, False, stations)
            (OUT / f"{fixture_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            entries.append({"fixture_id": fixture_id, "path": f"{fixture_id}.json", "family": family, "variant": variant, "requested_station_count": stations, "expected_topology": payload["topology"], "expected_engine": "DETERMINISTIC_FALLBACK_OR_LEARNED", "expected_ood_class": "IN_DISTRIBUTION"})
    for index in range(10):
        fixture_id = f"OOD_HIGH_FREQUENCY_{index + 1:02d}"
        payload = profile(fixture_id, "OPEN_CURVED_WAVE", 0.8 + index * 0.04, False, True, 16)
        (OUT / f"{fixture_id}.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entries.append({"fixture_id": fixture_id, "path": f"{fixture_id}.json", "family": "OOD_HIGH_FREQUENCY", "variant": str(index + 1), "requested_station_count": 16, "expected_topology": "OPEN_PATH", "expected_engine": "DETERMINISTIC_FALLBACK", "expected_ood_class": "OUT_OF_DISTRIBUTION"})
    (OUT / "manifest.json").write_text(json.dumps({"schema_version": 1, "classification": "PUBLIC_SYNTHETIC_TEST", "fixture_count": len(entries), "supported_count": 30, "negative_count": 10, "fixtures": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
