#!/usr/bin/env python3
"""Generate the canonical extraction reliability evidence report.

The report is deliberately generated from the project validator and readiness
command, not from hand-edited status text.
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--baseline", type=Path, default=Path("docs/reports/canonical-reliability-baseline.json"))
    parser.add_argument("--output-json", type=Path, default=Path("docs/reports/canonical-reliability-remediation.json"))
    parser.add_argument("--output-html", type=Path, default=Path("docs/reports/canonical-reliability-remediation.html"))
    parser.add_argument("--determinism", type=Path)
    args = parser.parse_args()
    evidence = collect(args.project, args.baseline, args.determinism)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    args.output_html.write_text(render(evidence), encoding="utf-8")
    print(args.output_html)
    return 0


def collect(project: Path, baseline_path: Path, determinism_path: Path | None = None) -> dict[str, Any]:
    validation = _run_json(["python", "-m", "rollform_extractor.cli", "validate", str(project), "--json"])
    readiness = _run_json(["python", "-m", "rollform_extractor.cli", "dataset-readiness", str(project), "--json"])
    baseline = _load(baseline_path)
    git_sha = _git_sha()
    counts = validation.get("counts", {})
    baseline_counts = baseline.get("baseline_counts", baseline.get("counts", {}))
    blockers = readiness.get("blockers", [])
    determinism = _load(determinism_path) if determinism_path else {}
    report_data = _load(project / "report_data.json")
    length_examples = [
        {
            "pass_id": item.get("pass_id"),
            "outline_perimeter": item.get("outline_perimeter_drawing_units"),
            "generated_neutral_length": item.get("generated_neutral_developed_length_drawing_units"),
            "expected_neutral_length": item.get("expected_neutral_developed_length_drawing_units"),
            "neutral_length_error": item.get("neutral_length_error_drawing_units"),
        }
        for flower in report_data.get("composite_flowers", [])
        for item in flower.get("passes", [])
        if item.get("pass_id") in {"pass_00_flat", "pass_01", "pass_02"}
    ]
    software_pass = bool(validation.get("valid"))
    pilot_valid = software_pass and not validation.get("issues")
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "repository": "puneetdixit200/roll-form-process",
        "branch": _git_branch(),
        "starting_sha": git_sha,
        "project_path": str(project),
        "baseline": baseline,
        "current_validation": validation,
        "current_readiness": readiness,
        "determinism_evidence": determinism,
        "length_examples": length_examples,
        "before_after": {
            "hash_mismatches": {"baseline": len(baseline.get("manifest_hash_details", {}).get("mismatches", [])), "corrected": sum(issue.get("code") == "hash_mismatch" for issue in validation.get("issues", []))},
            "accepted_composite_flowers": {"baseline": baseline_counts.get("composite_flowers_reported"), "corrected": counts.get("composite_flowers")},
            "accepted_composite_passes": {"baseline": baseline_counts.get("composite_passes_reported"), "corrected": counts.get("composite_passes")},
            "feature_sets": {"baseline": baseline_counts.get("feature_sets_reported"), "corrected": counts.get("feature_sets")},
        },
        "decisions": {
            "software_remediation": "PASS" if software_pass else "FAIL",
            "pilot_structural_validity": "PASS" if pilot_valid else "FAIL",
            "pilot_engineering_confirmation": "CONFIRMED" if readiness.get("status") == "READY" else "NOT CONFIRMED",
            "pilot_dataset_readiness": readiness.get("status", "BLOCKED"),
            "remaining_drawings": "KEEP QUARANTINED",
        },
        "limitations": [
            "Drawing units are not engineer-confirmed in the current pilot.",
            "Pass order and station alignment require engineer confirmation.",
            "Normalized descriptors are engineering features, not trusted retrieval data.",
            "The remaining drawing corpus remains quarantined.",
            "No production approval is implied.",
        ],
        "blockers": blockers,
    }


def _run_json(command: list[str]) -> dict[str, Any]:
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError:
        value = {"command": command, "exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr}
    if isinstance(value, dict):
        value.setdefault("exit_code", process.returncode)
        return value
    return {"exit_code": process.returncode, "value": value}


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()


def _git_branch() -> str:
    return subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=False).stdout.strip()


def render(evidence: dict[str, Any]) -> str:
    decisions = evidence["decisions"]
    readiness = evidence["current_readiness"]
    validation = evidence["current_validation"]
    status_class = "pass" if decisions["pilot_structural_validity"] == "PASS" else "fail"
    blocker_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in evidence.get("blockers", [])) or "<li>None</li>"
    rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value.get('baseline')))}</td><td>{html.escape(str(value.get('corrected')))}</td></tr>"
        for key, value in evidence["before_after"].items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canonical extraction reliability remediation</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1180px;margin:0 auto;padding:24px;background:#f4f6f8;color:#17202a;line-height:1.45}}
header,section,aside{{background:#fff;border:1px solid #d8dee4;border-radius:10px;padding:20px;margin:16px 0}}
h1,h2{{line-height:1.2}} table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d8dee4;padding:8px;text-align:left}}
.badge{{display:inline-block;padding:5px 10px;border-radius:999px;font-weight:700}}.pass{{background:#d9f7e6;color:#075b32}}.fail{{background:#ffe0e0;color:#8a1010}}.warn{{background:#fff1c2;color:#6b4d00}}
code,pre{{background:#f1f3f5;border-radius:5px;padding:2px 4px}}pre{{padding:12px;overflow:auto}}@media print{{body{{background:#fff}}header,section,aside{{break-inside:avoid}}}}
</style></head><body>
<header><h1>Canonical Extraction Reliability Remediation</h1>
<p><strong>Software remediation:</strong> <span class="badge {status_class}">{html.escape(decisions['software_remediation'])}</span>
<strong>Pilot structural validity:</strong> <span class="badge {status_class}">{html.escape(decisions['pilot_structural_validity'])}</span></p>
<p><strong>Pilot engineering confirmation:</strong> {html.escape(decisions['pilot_engineering_confirmation'])}<br>
<strong>Pilot dataset readiness:</strong> <span class="badge warn">{html.escape(str(decisions['pilot_dataset_readiness']))}</span><br>
<strong>Remaining drawings:</strong> {html.escape(decisions['remaining_drawings'])}</p>
<p>Generated {html.escape(evidence['generated_at'])} from Git SHA <code>{html.escape(evidence['starting_sha'])}</code>.</p></header>
<section><h2>Baseline and corrected evidence</h2><table><thead><tr><th>Metric</th><th>Baseline</th><th>Corrected</th></tr></thead><tbody>{rows}</tbody></table>
<p>The baseline is preserved as a reproduction record; corrected artifacts were regenerated from source geometry and configuration.</p></section>
<section><h2>Validation</h2><p>Validator: <span class="badge {status_class}">{'PASS' if validation.get('valid') else 'FAIL'}</span></p>
<pre>{html.escape(json.dumps(validation, indent=2, sort_keys=True))}</pre></section>
<section><h2>Dataset-readiness gate</h2><p>Status: <span class="badge warn">{html.escape(str(readiness.get('status')))}</span></p>
<ul>{blocker_html}</ul><pre>{html.escape(json.dumps(readiness, indent=2, sort_keys=True))}</pre></section>
<section><h2>Two-run determinism</h2><pre>{html.escape(json.dumps(evidence.get('determinism_evidence', {}), indent=2, sort_keys=True))}</pre></section>
<section><h2>Qualified length examples</h2><table><thead><tr><th>Pass</th><th>Outline perimeter</th><th>Generated neutral</th><th>Expected neutral</th><th>Error</th></tr></thead><tbody>{''.join(f"<tr><td>{html.escape(str(row.get('pass_id')))}</td><td>{html.escape(str(row.get('outline_perimeter')))}</td><td>{html.escape(str(row.get('generated_neutral_length')))}</td><td>{html.escape(str(row.get('expected_neutral_length')))}</td><td>{html.escape(str(row.get('neutral_length_error')))}</td></tr>" for row in evidence.get('length_examples', []))}</tbody></table></section>
<section><h2>Root-cause corrections</h2><ul>
<li>Manifest diagnostics now include expected and actual SHA-256 values.</li>
<li>Incomplete composite regions are auditable and excluded from accepted flowers.</li>
<li>Pass features are checked one-for-one against accepted canonical passes.</li>
<li>Alignment is a domain-level monotonic optimization, not report first-match selection.</li>
<li>Outline perimeter and generated neutral developed length are separate fields.</li>
<li>Neutral-length error is calculated from independently retained values.</li>
<li>Comparison vectors reject absolute CAD placement fields.</li>
<li>Review application regenerates SQLite and dependent artifacts through an atomic path.</li>
</ul></section>
<section><h2>Safety boundary</h2><p>These artifacts are candidate engineering extraction only. Unconfirmed units/order block trusted corpus import. No retrieval, automatic roller assignment, tooling recommendation, forming-sequence generation, or production approval is implemented.</p></section>
<section><h2>Known limitations and required decisions</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in evidence['limitations'])}</ul></section>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
