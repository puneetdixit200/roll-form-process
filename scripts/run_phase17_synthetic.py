#!/usr/bin/env python3
"""Run the sanitized Phase 17 deterministic regression dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.roller_recognition import InventoryRevisionCandidate, evaluate_recognition, prepare_recognition_input, recognize_occurrence


def candidate(design_id: str, revision_id: str, shape: tuple[float, ...], *, diameter: float = 100.0, bore: float = 40.0, role: str = "upper_upper", fingerprint: str | None = None) -> InventoryRevisionCandidate:
    return InventoryRevisionCandidate(design_id, design_id, "WORKING", revision_id, {"outer_diameter_mm": diameter, "bore_diameter_mm": bore, "face_width_mm": 60.0}, {"role": role}, shape, fingerprint, None, "CONFIRMED", "VERIFIED", "VERIFIED_ELIGIBLE", .98, (design_id.lower(),), role=role)


def make_occurrence(identifier: str, *, shape=(0.0, 1.0, 0.0, 1.0), diameter=100.0, bore=40.0, units="CONFIRMED", role="upper_upper", design_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(occurrence_id=identifier, station_id="SYN-STATION", role=role, source_handles=(f"SYN-{identifier}",), confidence=.98, evidence={"outer_diameter_mm": diameter, "bore_diameter_mm": bore, "width_mm": 60.0, "units_status": units, "shape_vector": list(shape), "physical_fingerprint": "fp-001" if design_id == "RDES-001" else None, "geometry_descriptor": {"design_id": design_id}})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = ExtractionConfig.load().roller_recognition
    revisions = [candidate("RDES-001", "RREV-001", (0, 1, 0, 1), fingerprint="fp-001"), candidate("RDES-002", "RREV-002", (0, .8, .2, 1), diameter=110), candidate("RDES-003", "RREV-003", (.1, .9, .1, .9), diameter=120), candidate("RDES-004", "RREV-004", (.2, .7, .3, .8), diameter=90), candidate("RDES-005", "RREV-005", (.3, .6, .4, .7), diameter=130, bore=50), candidate("RDES-006", "RREV-006", (.4, .5, .5, .6), diameter=80, bore=30), candidate("RDES-007", "RREV-007", (.5, .4, .6, .5), diameter=140, bore=55), candidate("RDES-008", "RREV-008", (.6, .3, .7, .4), diameter=150, bore=60)]
    cases = [
        (make_occurrence("CASE-EXACT-ID", design_id="RDES-001"), "RDES-001"),
        (make_occurrence("CASE-EXACT-FP"), "RDES-001"),
        (make_occurrence("CASE-NEAR", shape=(.11, .89, .11, .89), diameter=120), "RDES-003"),
        (make_occurrence("CASE-WRONG-BORE", diameter=130, bore=22, shape=(.3, .6, .4, .7)), None),
        (make_occurrence("CASE-UNKNOWN-UNITS", units="UNKNOWN", shape=(.5, .4, .6, .5), diameter=140, bore=55), "RDES-007"),
        (make_occurrence("CASE-NO-MATCH", diameter=999), None),
        (make_occurrence("CASE-AMBIGUOUS", shape=(0, 1, 0, 1)), None),
        (make_occurrence("CASE-INVALID"), None),
    ]
    results = []
    labels = {}
    for occurrence, expected in cases:
        prepared = prepare_recognition_input("SYNTHETIC-PROJECT", occurrence, units_status=occurrence.evidence["units_status"], configuration_hash="synthetic-config")
        if occurrence.occurrence_id == "CASE-INVALID":
            prepared = prepared.__class__(**{name: getattr(prepared, name) for name in prepared.__dataclass_fields__ if name != "quality_flags" and name != "input_hash"}, quality_flags=("INVALID_GEOMETRY",), input_hash="")
        available_revisions = revisions + ([candidate("RDES-009", "RREV-009", (0, 1, 0, 1))] if occurrence.occurrence_id == "CASE-AMBIGUOUS" else [])
        result = recognize_occurrence(prepared, available_revisions, config)
        results.append(result)
        if expected:
            labels[occurrence.occurrence_id] = expected
    data = {"dataset_kind": "SYNTHETIC", "case_count": len(cases), "results": [result.to_dict() for result in results], "metrics": evaluate_recognition(results, labels, dataset_kind="SYNTHETIC"), "acceptance": {"true_no_match_abstained": results[5].abstained, "ambiguous_case_abstained": results[6].status == "AMBIGUOUS", "wrong_bore_abstained": results[3].abstained, "invalid_abstained": results[7].status == "INVALID_INPUT", "unknown_units_has_no_dimensional_claim": results[4].input.quality == "UNKNOWN_UNITS"}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"dataset_kind": "SYNTHETIC", "case_count": len(cases), "metrics": data["metrics"], "acceptance": data["acceptance"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
