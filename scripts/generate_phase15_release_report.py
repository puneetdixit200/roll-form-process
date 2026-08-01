#!/usr/bin/env python3
"""Build the self-contained Phase 15 release-readiness evidence report."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import html
import json
from pathlib import Path


CSS = """
:root{color-scheme:light;--ink:#172033;--muted:#5c6678;--line:#d9deea;--good:#147a4b;--bad:#a52323;--warn:#9a6500;--panel:#f7f9fc}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);background:#fff}main{max-width:1180px;margin:auto;padding:28px}h1{font-size:32px;margin:.2em 0}h2{margin-top:2.2em;border-bottom:2px solid var(--line);padding-bottom:6px}h3{margin-top:1.4em}a{color:#0759a5}.meta,.grid{display:grid;gap:12px}.meta{grid-template-columns:repeat(auto-fit,minmax(220px,1fr));background:var(--panel);padding:16px;border-radius:10px}.grid{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.card{border:1px solid var(--line);border-radius:10px;padding:13px;background:#fff}.metric{font-size:25px;font-weight:700}.label{color:var(--muted);font-size:12px}.badge{display:inline-block;border-radius:999px;padding:3px 10px;font-weight:700;letter-spacing:.03em}.PASS{color:#fff;background:var(--good)}.FAIL{color:#fff;background:var(--bad)}.BLOCKED,.WARN{color:#241700;background:#f3c44f}.NA{color:#fff;background:#667085}table{width:100%;border-collapse:collapse;margin:10px 0}th,td{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{background:var(--panel)}code{background:#eef1f6;padding:1px 4px;border-radius:4px}details{margin:8px 0;background:var(--panel);padding:8px;border-radius:6px}pre{white-space:pre-wrap;max-height:260px;overflow:auto}.decision{padding:20px;border:3px solid var(--bad);border-radius:12px;background:#fff5f5}.decision.safe{border-color:var(--good);background:#f0fff7}.toc{display:flex;flex-wrap:wrap;gap:10px;padding:10px 0}.toc a{font-weight:600}@media print{main{padding:0}.toc{display:none}.decision{break-inside:avoid}}
"""


def esc(value: object) -> str:
    return html.escape(str(value))


def badge(status: str) -> str:
    normalized = str(status).upper()
    cls = normalized if normalized in {"PASS", "FAIL", "BLOCKED", "WARN", "NA"} else "NA"
    return f'<span class="badge {cls}">{esc(normalized)}</span>'


def table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{esc(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{item if isinstance(item, str) and item.startswith('<') else esc(item)}</td>" for item in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def metrics(values: dict[str, object]) -> str:
    return '<div class="grid">' + "".join(f'<div class="card"><div class="label">{esc(key)}</div><div class="metric">{esc(value)}</div></div>' for key, value in values.items()) + "</div>"


def command_table(commands: list[dict[str, object]]) -> str:
    rows = []
    for item in commands:
        excerpt = f"<details><summary>output</summary><pre>{esc(item.get('excerpt',''))}</pre></details>"
        rows.append([esc(item.get("command", "")), esc(item.get("cwd", "")), esc(item.get("exit_code", "")), esc(item.get("duration", "")), badge(str(item.get("result", "NA"))), excerpt])
    return table(["Command", "Working directory", "Exit", "Duration", "Result", "Evidence"], rows)


def build(evidence: dict[str, object]) -> str:
    summary = evidence.get("summary", {})
    result = str(summary.get("overall_result", "BLOCKED")).upper()
    safe = result == "PASS"
    sections = []
    sections.append(f"<section id='summary'><h2>1. Executive Summary</h2><div class='decision {'safe' if safe else ''}'><h3>{'SAFE TO MERGE' if safe else 'DO NOT MERGE'}</h3><p>Overall result: {badge(result)}</p><p>{esc(summary.get('merge_recommendation',''))}</p></div><div class='meta'>" + "".join(f"<div><b>{esc(k)}</b><br>{esc(v)}</div>" for k,v in summary.items() if k != 'overall_result') + "</div></section>")
    sections.append("<section id='scope'><h2>2. Scope Completed</h2><p>" + esc(summary.get("scope", "Phase 15 versioned automatic pass feature extraction and its offline delivery path.")) + "</p></section>")
    defects = evidence.get("defects", [])
    sections.append("<section id='defects'><h2>3. Defects Corrected</h2>" + table(["Defect","Previous risk","Fix","Verification","Status"], [[esc(x.get(k,'')) for k in ("defect","risk","fix","verification")] + [badge(x.get("status","NA"))] for x in defects]) + "</section>")
    sections.append("<section id='tests'><h2>4. Test Matrix</h2>" + command_table(evidence.get("commands", [])) + "</section>")
    pilot = evidence.get("pilot", {})
    sections.append("<section id='pilot'><h2>5. Pilot Results</h2>" + metrics({k:v for k,v in pilot.items() if k not in {"determinism"}}) + "</section>")
    det = evidence.get("determinism", {})
    sections.append("<section id='determinism'><h2>6. Determinism</h2>" + badge("PASS" if det.get("equal") else "FAIL") + "<pre>" + esc(json.dumps(det, indent=2, sort_keys=True)) + "</pre></section>")
    db = evidence.get("database", {})
    sections.append("<section id='database'><h2>7. Database Integrity</h2>" + metrics(db) + "</section>")
    api = evidence.get("api_frontend", {})
    sections.append("<section id='api'><h2>8. API and Frontend</h2>" + table(["Check","Result","Evidence"], [[esc(x.get("check","")), badge(x.get("result","NA")), esc(x.get("evidence",""))] for x in api.get("checks", [])]) + "</section>")
    docker = evidence.get("docker", {})
    sections.append("<section id='docker'><h2>9. Docker and Offline Deployment</h2><p>" + badge(docker.get("result","NA")) + " " + esc(docker.get("diagnosis","")) + "</p><pre>" + esc(docker.get("excerpt","")) + "</pre></section>")
    ci = evidence.get("ci", {})
    sections.append("<section id='ci'><h2>10. CI Status</h2>" + table(["Item","Value"], [[esc(k), esc(v)] for k,v in ci.items()]) + "</section>")
    hygiene = evidence.get("hygiene", {})
    sections.append("<section id='hygiene'><h2>11. Repository Hygiene</h2>" + metrics(hygiene) + "</section>")
    limitations = evidence.get("limitations", {})
    sections.append("<section id='limits'><h2>12. Remaining Limitations</h2>" + "".join(f"<h3>{esc(k)}</h3><ul>" + "".join(f"<li>{esc(v)}</li>" for v in vals) + "</ul>" for k,vals in limitations.items()) + "</section>")
    sections.append("<section id='decision'><h2>13. Release Decision</h2><div class='decision " + ("safe" if safe else "") + "'><h3>" + ("SAFE TO MERGE" if safe else "DO NOT MERGE") + "</h3><p>" + esc(summary.get("merge_recommendation", "")) + "</p></div></section>")
    toc = "<nav class='toc' aria-label='Table of contents'>" + " ".join(f"<a href='#{anchor}'>{label}</a>" for anchor,label in [("summary","Summary"),("scope","Scope"),("defects","Defects"),("tests","Tests"),("pilot","Pilot"),("determinism","Determinism"),("database","Database"),("api","API / Frontend"),("docker","Docker"),("ci","CI"),("hygiene","Hygiene"),("limits","Limitations"),("decision","Decision")]) + "</nav>"
    generated = summary.get("report_generated_utc") or datetime.now(UTC).isoformat()
    return "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Phase 15 Release Readiness</title><style>" + CSS + "</style></head><body><main><h1>Phase 15 Release Readiness</h1><p>Auditable offline completion report · generated " + esc(generated) + "</p>" + toc + "".join(sections) + "</main></body></html>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--html", type=Path, default=Path("docs/reports/phase-15-release-readiness.html"))
    parser.add_argument("--json", dest="json_path", type=Path, default=Path("docs/reports/phase-15-release-readiness.json"))
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.html.write_text(build(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
