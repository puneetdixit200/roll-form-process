#!/usr/bin/env python3
"""Generate the Phase 21 redacted readiness evidence report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import subprocess


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def validate(evidence: dict) -> None:
    required = ("phase", "git", "statuses", "golden", "safety", "tests")
    missing = [key for key in required if key not in evidence]
    if missing or str(evidence.get("phase")) != "21":
        raise ValueError(f"invalid Phase 21 evidence: missing={missing}")
    for key in ("manufacturing_approval", "physical_roller_availability"):
        if key not in evidence["safety"]:
            raise ValueError(f"missing safety field: {key}")


def render(evidence: dict) -> str:
    statuses = evidence["statuses"]
    status_rows = "".join(f"<tr><th>{html.escape(str(key))}</th><td><span class='badge {str(value).lower().replace(' ', '-')}'>{html.escape(str(value))}</span></td></tr>" for key, value in statuses.items())
    cards = "".join(f"<div class='card'><small>{html.escape(str(key))}</small><strong>{html.escape(str(value))}</strong></div>" for key, value in {"Supported golden": evidence["golden"].get("supported"), "OOD golden": evidence["golden"].get("ood"), "Python": evidence["tests"].get("python"), "Frontend": evidence["tests"].get("frontend")}.items())
    body = html.escape(json.dumps(evidence, indent=2, sort_keys=True))
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Phase 21 Demo Readiness</title><style>body{{margin:0;background:#f3f6f8;color:#17212b;font:16px system-ui,sans-serif}}main{{max-width:1120px;margin:auto;padding:24px}}header,section{{background:#fff;border:1px solid #d5dde5;border-radius:12px;padding:22px;margin:14px 0}}h1{{margin-top:0}}.notice{{padding:14px;border-left:5px solid #c78600;background:#fff3c4}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}.card{{background:#edf4f8;border-radius:8px;padding:12px}}.card strong{{display:block;font-size:1.4rem;margin-top:5px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:9px;border-bottom:1px solid #dce3e8;text-align:left}}.badge{{display:inline-block;border-radius:999px;padding:4px 9px;font-weight:700;background:#dbe5eb}}.pass,.ready{{background:#d8f3dc;color:#14532d}}.warn,.not-ready{{background:#fff0bd;color:#704e00}}.fail{{background:#ffd9de;color:#841c2c}}pre{{background:#101820;color:#dce9f1;padding:14px;border-radius:8px;overflow:auto;white-space:pre-wrap}}@media print{{header,section{{break-inside:avoid}}}}</style></head><body><main><header><h1>Phase 21 Prototype Validation Demo Release</h1><p><strong>Visual geometry prototype only.</strong> Not manufacturing approval, tooling approval, physical roller selection, or production release.</p><div class='notice'><strong>Manufacturing approval: NOT APPROVED.</strong> Physical roller availability: NOT DETERMINED.</div><div class='cards'>{cards}</div></header><section><h2>Release statuses</h2><table>{status_rows}</table></section><section><h2>Evidence</h2><p>Branch: <code>{html.escape(str(evidence['git'].get('branch')))}</code><br>Head: <code>{html.escape(str(evidence['git'].get('head')))}</code><br>Generated: {html.escape(str(evidence.get('generated_at')))}</p><pre>{body}</pre></section><section><h2>Evidence boundary</h2><ul><li>Private CLRSG evidence remains local and is not embedded here.</li><li>Golden fixtures are public procedural profiles.</li><li>Visual confidence is not manufacturing confidence.</li><li>Engineer feedback does not retrain or change model approval.</li></ul></section></main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=Path("docs/reports/phase21-demo-readiness.json"))
    parser.add_argument("--output-html", type=Path, default=Path("docs/reports/phase21-demo-readiness.html"))
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    evidence["generated_at"] = datetime.now(timezone.utc).isoformat()
    evidence.setdefault("git", {})["branch"] = git_value("branch", "--show-current")
    evidence["git"]["head"] = git_value("rev-parse", "HEAD")
    validate(evidence)
    args.output_json.parent.mkdir(parents=True, exist_ok=True); args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_html.write_text(render(evidence), encoding="utf-8")
    print(json.dumps({"status": "PASS", "json": str(args.output_json), "html": str(args.output_html)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
