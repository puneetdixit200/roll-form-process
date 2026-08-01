#!/usr/bin/env python3
"""Generate a self-contained Phase 16 inventory release report from evidence JSON."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import html
import json
from pathlib import Path

CSS = """
:root{--ink:#182235;--muted:#5d687b;--line:#d7deea;--panel:#f5f7fb;--good:#126b43;--bad:#a82424;--warn:#8a5b00}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:28px}h1{font-size:32px}h2{margin-top:2em;border-bottom:2px solid var(--line);padding-bottom:6px}.toc{display:flex;flex-wrap:wrap;gap:10px}.toc a{color:#0759a5;font-weight:600}.meta,.cards{display:grid;gap:12px}.meta{grid-template-columns:repeat(auto-fit,minmax(220px,1fr));background:var(--panel);padding:16px;border-radius:10px}.cards{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.card{border:1px solid var(--line);border-radius:10px;padding:12px}.metric{font-size:24px;font-weight:700}.label{color:var(--muted);font-size:12px}.badge{display:inline-block;border-radius:999px;padding:3px 10px;font-weight:700}.PASS{background:#dff5e9;color:var(--good)}.FAIL{background:#ffe4e4;color:var(--bad)}.WARN,.BLOCKED{background:#fff0bd;color:var(--warn)}.NA{background:#e8ecf2;color:#4b5565}table{width:100%;border-collapse:collapse;margin:10px 0}th,td{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}th{background:var(--panel)}pre{white-space:pre-wrap;max-height:300px;overflow:auto;background:var(--panel);padding:10px}.decision{padding:18px;border:3px solid var(--bad);background:#fff5f5;border-radius:12px}.decision.safe{border-color:var(--good);background:#f0fff7}@media print{.toc{display:none}}
"""

def esc(value: object) -> str:
    return html.escape(str(value))

def badge(value: object) -> str:
    status = str(value).upper()
    cls = status if status in {"PASS", "FAIL", "WARN", "BLOCKED", "NA"} else "NA"
    return f'<span class="badge {cls}">{esc(status)}</span>'

def cards(values: dict[str, object]) -> str:
    return '<div class="cards">' + ''.join(f'<div class="card"><div class="label">{esc(k)}</div><div class="metric">{esc(v)}</div></div>' for k,v in values.items()) + '</div>'

def table(headers: list[str], rows: list[list[object]]) -> str:
    head = ''.join(f'<th>{esc(x)}</th>' for x in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{x if isinstance(x,str) and x.startswith("<") else esc(x)}</td>' for x in row) + '</tr>' for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

def build(evidence: dict[str, object]) -> str:
    summary = evidence.get('summary', {})
    result = str(summary.get('overall_result', 'BLOCKED')).upper()
    safe = result == 'PASS'
    sections: list[str] = []
    sections.append(f'<section id="summary"><h2>1. Executive Summary</h2><div class="decision {"safe" if safe else ""}"><h3>{"SAFE TO MERGE" if safe else "DO NOT MERGE"}</h3><p>Overall result: {badge(result)}</p><p>{esc(summary.get("merge_recommendation", ""))}</p></div><div class="meta">' + ''.join(f'<div><b>{esc(k)}</b><br>{esc(v)}</div>' for k,v in summary.items() if k != 'overall_result') + '</div></section>')
    sections.append('<section id="scope"><h2>2. Scope Completed</h2><p>Versioned physical roller inventory with staged, unit-safe, provenance-preserving imports. Phase 17 recognition and recommendations are disabled.</p></section>')
    sections.append('<section id="schema"><h2>3. Schema and Import Workflow</h2><p>' + esc(evidence.get('schema_summary','')) + '</p><pre>' + esc(json.dumps(evidence.get('import_workflow',{}), indent=2, sort_keys=True)) + '</pre></section>')
    sections.append('<section id="pilot"><h2>4. Pilot Results</h2>' + cards(evidence.get('pilot',{})) + '</section>')
    sections.append('<section id="tests"><h2>5. Test Matrix</h2>' + table(['Command','Result','Evidence'], [[esc(x.get('command','')),badge(x.get('result','NA')),esc(x.get('excerpt',''))] for x in evidence.get('tests',[])]) + '</section>')
    sections.append('<section id="database"><h2>6. Database and Migration</h2>' + cards(evidence.get('database',{})) + '</section>')
    sections.append('<section id="api"><h2>7. API and Frontend</h2>' + table(['Check','Result','Evidence'], [[esc(x.get('check','')),badge(x.get('result','NA')),esc(x.get('evidence',''))] for x in evidence.get('api_frontend',[])]) + '</section>')
    sections.append('<section id="docker"><h2>8. Docker and CI</h2>' + cards(evidence.get('ci',{})) + '<pre>' + esc(json.dumps(evidence.get('docker',{}), indent=2, sort_keys=True)) + '</pre></section>')
    sections.append('<section id="limits"><h2>9. Remaining Limitations</h2>' + ''.join(f'<h3>{esc(k)}</h3><ul>' + ''.join(f'<li>{esc(v)}</li>' for v in vals) + '</ul>' for k,vals in evidence.get('limitations',{}).items()) + '</section>')
    sections.append(f'<section id="decision"><h2>10. Release Decision</h2><div class="decision {"safe" if safe else ""}"><h3>{"SAFE TO MERGE" if safe else "DO NOT MERGE"}</h3><p>{esc(summary.get("merge_recommendation", ""))}</p></div></section>')
    toc = '<nav class="toc" aria-label="Table of contents">' + ' '.join(f'<a href="#{a}">{b}</a>' for a,b in [('summary','Summary'),('scope','Scope'),('schema','Schema'),('pilot','Pilot'),('tests','Tests'),('database','Database'),('api','API / Frontend'),('docker','Docker / CI'),('limits','Limitations'),('decision','Decision')]) + '</nav>'
    generated = summary.get('report_generated_utc') or datetime.now(UTC).isoformat()
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phase 16 Release Readiness</title><style>' + CSS + '</style></head><body><main><h1>Phase 16 Roller Inventory Release Readiness</h1><p>Self-contained evidence report · generated ' + esc(generated) + '</p>' + toc + ''.join(sections) + '</main></body></html>'

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--html', type=Path, default=Path('docs/reports/phase-16-release-readiness.html'))
    parser.add_argument('--json', dest='json_path', type=Path, default=Path('docs/reports/phase-16-release-readiness.json'))
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding='utf-8'))
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    args.html.write_text(build(evidence), encoding='utf-8')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
