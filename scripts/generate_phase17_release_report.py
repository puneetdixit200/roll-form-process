#!/usr/bin/env python3
"""Validate evidence JSON and build a self-contained Phase 17 report."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import html
import json
from pathlib import Path
from typing import Any

REQUIRED = ("summary", "architecture", "algorithm", "synthetic_dataset", "evaluation", "tests", "determinism", "database", "api_frontend", "ci", "security", "risks", "decisions", "limitations")
CSS = """
:root{--ink:#172033;--muted:#5d687a;--line:#d8dfeb;--panel:#f5f7fb;--good:#106b43;--bad:#a52323;--warn:#8b5c00;--blue:#0759a5}*{box-sizing:border-box}body{margin:0;color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1280px;margin:auto;padding:28px 34px}h1{font-size:34px;margin:.1em 0}h2{border-bottom:2px solid var(--line);padding-bottom:7px;margin:2.3em 0 1em}h3{margin-top:1.4em}a{color:var(--blue)}.layout{display:grid;grid-template-columns:210px 1fr;gap:28px}.toc{position:sticky;top:12px;align-self:start;display:grid;gap:7px}.toc a{font-weight:650;text-decoration:none}.meta,.cards{display:grid;gap:12px}.meta{grid-template-columns:repeat(auto-fit,minmax(220px,1fr));background:var(--panel);padding:16px;border-radius:12px}.cards{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.card{border:1px solid var(--line);border-radius:10px;padding:13px;background:#fff}.metric{font-size:25px;font-weight:750}.label{font-size:12px;color:var(--muted)}.badge{display:inline-flex;gap:5px;align-items:center;border-radius:999px;padding:3px 10px;font-weight:750}.PASS{background:#ddf5e8;color:var(--good)}.FAIL{background:#ffe3e3;color:var(--bad)}.WARN,.BLOCKED{background:#fff0be;color:var(--warn)}.NA{background:#e9edf3;color:#4b5564}.decision{padding:18px;border:3px solid var(--bad);border-radius:13px;background:#fff5f5}.decision.safe{border-color:var(--good);background:#effff7}table{width:100%;border-collapse:collapse;margin:10px 0}th,td{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{background:var(--panel)}pre{white-space:pre-wrap;overflow:auto;max-height:320px;background:var(--panel);padding:11px;border-radius:8px}.callout{border-left:5px solid var(--warn);background:#fffaf0;padding:12px}.svgbox{border:1px solid var(--line);border-radius:10px;padding:8px;overflow:auto}.bar{height:18px;background:#dce7f4;border-radius:5px;overflow:hidden}.bar>i{display:block;height:100%;background:#2574b9}.back{float:right;font-size:12px}@media(max-width:800px){main{padding:18px}.layout{display:block}.toc{position:static;display:none}.layout:before{content:"Table of contents ▾";display:block;border:1px solid var(--line);padding:8px;margin-bottom:10px}}@media print{main{padding:0}.toc{display:none}.decision{break-inside:avoid}.back{display:none}}
"""

def esc(value: object) -> str:
    return html.escape(str(value))

def badge(value: object) -> str:
    status = str(value).upper()
    cls = status if status in {"PASS", "FAIL", "WARN", "BLOCKED", "NA"} else "NA"
    icon = {"PASS": "✓", "FAIL": "✕", "WARN": "!", "BLOCKED": "!", "NA": "•"}[cls]
    return f'<span class="badge {cls}" aria-label="{esc(status)}"><span aria-hidden="true">{icon}</span>{esc(status)}</span>'

def cards(values: dict[str, Any]) -> str:
    return '<div class="cards">' + ''.join(f'<div class="card"><div class="label">{esc(k)}</div><div class="metric">{esc(v)}</div></div>' for k,v in values.items()) + '</div>'

def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = ''.join(f'<th>{esc(x)}</th>' for x in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{x if isinstance(x,str) and x.startswith("<") else esc(x)}</td>' for x in row) + '</tr>' for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

def process_svg() -> str:
    labels = ["Historical drawing", "Occurrence input", "Eligible revisions", "Explainable ranking", "Abstain / review"]
    return '<svg viewBox="0 0 1100 150" role="img" aria-label="Recognition process">' + ''.join(f'<g transform="translate({25+i*215},45)"><rect width="180" height="58" rx="10" fill="#eaf2fb" stroke="#2574b9"/><text x="90" y="34" text-anchor="middle" font-size="14">{esc(label)}</text></g>' + (f'<path d="M {190+i*215} 74 H {235+i*215}" stroke="#2574b9" stroke-width="3" marker-end="url(#a)"/>' if i < 4 else '') for i,label in enumerate(labels)) + '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#2574b9"/></marker></defs></svg>'

def architecture_svg() -> str:
    boxes = [(30,30,"CAD / occurrence"),(250,30,"recognition.py"),(470,30,"SQLite runs"),(690,30,"FastAPI"),(880,30,"React review")]
    return '<svg viewBox="0 0 1120 120" role="img" aria-label="Phase 17 architecture">' + ''.join(f'<rect x="{x}" y="{y}" width="170" height="48" rx="9" fill="#f5f7fb" stroke="#64748b"/><text x="{x+85}" y="{y+29}" text-anchor="middle" font-size="13">{esc(label)}</text>' for x,y,label in boxes) + ''.join(f'<path d="M {x+170} 54 H {x+220}" stroke="#64748b" stroke-width="2" marker-end="url(#b)"/>' for x,y,label in boxes[:-1]) + '<defs><marker id="b" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#64748b"/></marker></defs></svg>'

def evaluation_chart(evaluation: dict[str, Any]) -> str:
    metrics = [("Top-1", evaluation.get("top_1_accuracy", 0)), ("Top-3", evaluation.get("top_3_recall", 0)), ("Coverage", evaluation.get("coverage", 0)), ("Non-abstained", evaluation.get("accuracy_non_abstained", 0))]
    return '<div class="cards">' + ''.join(f'<div class="card"><b>{esc(label)}</b><div class="bar" aria-label="{esc(label)} {float(value):.3f}"><i style="width:{max(0,min(100,float(value)*100)):.1f}%"></i></div><span>{float(value):.3f}</span></div>' for label,value in metrics) + '</div>'

def validate(evidence: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED if key not in evidence]
    if missing:
        raise ValueError("evidence missing required sections: " + ", ".join(missing))
    summary = evidence["summary"]
    for key in ("technical_result", "production_status", "branch", "feature_sha"):
        if not summary.get(key):
            raise ValueError(f"summary.{key} is required")
    if evidence["summary"].get("technical_result") not in {"PASS", "FAIL", "BLOCKED"}:
        raise ValueError("summary.technical_result must be PASS, FAIL, or BLOCKED")

def section(title: str, anchor: str, content: str) -> str:
    return f'<section id="{anchor}"><a class="back" href="#top">back to top</a><h2>{title}</h2>{content}</section>'

def build(evidence: dict[str, Any]) -> str:
    validate(evidence)
    summary, evaluation = evidence["summary"], evidence["evaluation"]
    technical_pass = summary["technical_result"] == "PASS"
    prod = summary.get("production_status", "NOT APPROVED")
    sections = []
    sections.append(section("1. Release summary", "summary", f'<div class="decision {"safe" if technical_pass else ""}"><h3>{"ENGINEERING IMPLEMENTATION: SAFE TO MERGE" if technical_pass else "ENGINEERING IMPLEMENTATION: DO NOT MERGE"}</h3><p>{badge(summary["technical_result"])}</p><p><strong>Production recognition: {esc(prod)}</strong></p></div><div class="meta">' + ''.join(f'<div><b>{esc(k)}</b><br>{esc(v)}</div>' for k,v in summary.items()) + '</div>'))
    sections.append(section("2. User problem and solution", "flow", '<p>Historical drawing geometry is converted into evidence, compared only with eligible inventory design revisions, scored component-by-component, and either presented for review or rejected/abstained.</p><div class="svgbox">' + process_svg() + '</div>'))
    sections.append(section("3. Phase boundary", "boundary", table(["Implemented in Phase 17","Explicitly not implemented"], [["Occurrence preparation; design candidate retrieval; deterministic scoring; hard filters; abstention; review; evaluation; provenance", "Physical asset assignment; tooling recommendation; reuse percentage; sequence generation; manufacturability prediction; external recognition service"]]) + '<div class="callout"><strong>Safety:</strong> candidate design recognition only. Physical asset identity is never automatically determined.</div>'))
    sections.append(section("4. Architecture", "architecture", '<div class="svgbox">' + architecture_svg() + '</div><pre>' + esc(json.dumps(evidence["architecture"], indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("5. Data lineage", "lineage", '<p>Source CAD handle → roller occurrence → recognition input hash → candidate geometry revision → component scores → candidate result → append-only engineer review → explicit evaluation label.</p><pre>' + esc(json.dumps(evidence.get("lineage", {}), indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("6. Recognition algorithm", "algorithm", '<p><code>overall = Σ(score × weight) / Σ(available weights)</code>. Missing evidence is excluded from the denominator and lowers coverage; it is not a contradiction.</p><pre>' + esc(json.dumps(evidence["algorithm"], indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("7. Feature coverage", "coverage", cards(evidence.get("feature_coverage", {}))))
    sections.append(section("8. Synthetic dataset", "dataset", '<div class="callout"><strong>Warning:</strong> synthetic performance is regression evidence, not factory accuracy.</div>' + cards(evidence["synthetic_dataset"])))
    sections.append(section("9. Evaluation dashboard", "evaluation", evaluation_chart(evaluation) + table(["Metric","Value"], [[key,value] for key,value in evaluation.items() if not isinstance(value, (dict,list))]) + '<pre>' + esc(json.dumps(evidence.get("evaluation_breakdowns", {}), indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("10. Threshold analysis", "thresholds", table(["Threshold","Coverage","Accuracy","False high confidence","Ambiguous"], [[row.get(k,"") for k in ("threshold","coverage","accuracy","false_high_confidence_count","ambiguous_count")] for row in evidence.get("threshold_analysis", [])])))
    sections.append(section("11. Candidate case studies", "cases", table(["Case","Expected","Status","Explanation"], [[row.get(k,"") for k in ("case","expected","status","explanation")] for row in evidence.get("case_studies", [])])))
    sections.append(section("12. Engineer-review workflow", "review", '<p>Original output remains immutable. Decisions append reviewer, timestamp, decision, reason, selected design/revision, notes, and supersession links.</p><pre>' + esc(json.dumps(evidence.get("review_workflow", {}), indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("13. Database integrity", "database", cards(evidence["database"])))
    sections.append(section("14. API and frontend", "api", table(["Endpoint/check","Result","Evidence"], [[row.get("endpoint",row.get("check","")), badge(row.get("result","NA")), row.get("evidence","")] for row in evidence["api_frontend"]])))
    sections.append(section("15. Test matrix", "tests", table(["Command","Result","Exit","Duration","Evidence"], [[row.get(k,"") if k != "result" else badge(row.get(k,"NA")) for k in ("command","result","exit_code","duration","excerpt")] for row in evidence["tests"]])))
    sections.append(section("16. Determinism", "determinism", cards(evidence["determinism"]) + '<pre>' + esc(json.dumps(evidence["determinism"], indent=2, sort_keys=True)) + '</pre>'))
    sections.append(section("17. Security and privacy", "security", table(["Check","Result","Evidence"], [[row.get("check",""), badge(row.get("result","NA")), row.get("evidence","")] for row in evidence["security"]])))
    sections.append(section("18. Risk register", "risks", table(["Risk","Likelihood","Impact","Mitigation","Residual","Owner","Blocker"], [[row.get(k,"") for k in ("risk","likelihood","impact","mitigation","residual_risk","owner","release_blocker")] for row in evidence["risks"]])))
    sections.append(section("19. Engineer decisions required", "decisions", '<ul>' + ''.join(f'<li>{esc(item)}</li>' for item in evidence["decisions"]) + '</ul>'))
    sections.append(section("20. Limitations", "limitations", ''.join(f'<h3>{esc(key)}</h3><ul>' + ''.join(f'<li>{esc(item)}</li>' for item in values) + '</ul>' for key,values in evidence["limitations"].items())))
    sections.append(section("21. Release decision", "decision", f'<div class="decision {"safe" if technical_pass else ""}"><h3>ENGINEERING IMPLEMENTATION: {"SAFE TO MERGE" if technical_pass else "DO NOT MERGE"}</h3><p>PRODUCTION USE: {esc(prod)}</p></div>'))
    sections.append(section("22. Post-merge release record", "release", '<pre>' + esc(json.dumps(evidence.get("release_record", {}), indent=2, sort_keys=True)) + '</pre>'))
    toc = ''.join(f'<a href="#{anchor}">{label}</a>' for anchor,label in [("summary","Summary"),("flow","Problem / solution"),("boundary","Boundary"),("architecture","Architecture"),("algorithm","Algorithm"),("coverage","Coverage"),("dataset","Dataset"),("evaluation","Evaluation"),("thresholds","Thresholds"),("cases","Cases"),("review","Review"),("database","Database"),("api","API / frontend"),("tests","Tests"),("determinism","Determinism"),("security","Security"),("risks","Risks"),("decisions","Engineer decisions"),("limitations","Limitations"),("decision","Decision")])
    generated = summary.get("report_generated_utc") or datetime.now(UTC).isoformat()
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phase 17 Release Readiness</title><style>' + CSS + '</style></head><body id="top"><main><h1>Phase 17: Explainable Roller Design Recognition</h1><p>Evidence-driven release report · generated ' + esc(generated) + '</p><div class="layout"><nav class="toc" aria-label="Table of contents">' + toc + '</nav><article>' + ''.join(sections) + '</article></div></main></body></html>'

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--html", type=Path, default=Path("docs/reports/phase-17-release-readiness.html"))
    parser.add_argument("--json", dest="json_path", type=Path, default=Path("docs/reports/phase-17-release-readiness.json"))
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    validate(evidence)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.html.write_text(build(evidence), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
