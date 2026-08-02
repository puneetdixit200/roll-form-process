"""Generate the self-contained Phase 18 evidence report from executable JSON."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import html
import json
from pathlib import Path
import subprocess


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def validate(evidence: dict) -> None:
    required = {"phase", "fixture", "dataset", "safety", "determinism_hash"}
    missing = required - set(evidence)
    if missing:
        raise ValueError("evidence is missing: " + ", ".join(sorted(missing)))
    if evidence["phase"] != "Phase 18":
        raise ValueError("evidence phase must be Phase 18")
    if len(str(evidence["determinism_hash"])) != 64:
        raise ValueError("determinism_hash must be SHA-256")
    if evidence["safety"].get("physical_asset_assignment") is not False:
        raise ValueError("evidence cannot claim automatic physical asset assignment")


def _status(ok: bool, label: str) -> str:
    return f'<span class="badge {"pass" if ok else "warn"}">{"PASS" if ok else "WARNING"} — {html.escape(label)}</span>'


def generate(evidence: dict, output_json: Path, output_html: Path) -> None:
    validate(evidence)
    evidence = dict(evidence)
    evidence["report_generated_at"] = datetime.now(UTC).isoformat()
    evidence["git"] = {"branch": _git("branch", "--show-current"), "head": _git("rev-parse", "HEAD")}
    evidence.setdefault("ci_run", {"run_id": None, "url": None, "head_sha": evidence["git"]["head"], "result": "NOT RECORDED"})
    gates = evidence.get("verification", {})
    technical_gate = bool(evidence.get("validation_before_lock", {}).get("valid") and evidence.get("locked", {}).get("status") == "LOCKED" and gates.get("python_tests") and gates.get("frontend_tests") and gates.get("frontend_build") and gates.get("determinism") and gates.get("ci"))
    evidence["decisions"] = {"engineering_implementation": "SAFE TO MERGE" if technical_gate else "DO NOT MERGE", "recognition_production": "NOT APPROVED", "historical_search": "APPROVED FOR REVIEW USE" if technical_gate else "NOT APPROVED"}
    decision_banner = evidence["decisions"]["engineering_implementation"]
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    fixture = evidence["fixture"]
    metrics = evidence.get("validation_before_lock", {})
    relationships = evidence.get("relationships", {})
    rows = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in sorted(fixture.items()))
    html_doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phase 18 Release Evidence</title>
<style>
:root{{--bg:#f5f7fb;--ink:#182230;--muted:#526173;--line:#d8e0ea;--blue:#174ea6;--green:#087443;--amber:#8a5200}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}.layout{{display:grid;grid-template-columns:250px 1fr;max-width:1500px;margin:auto}}aside{{position:sticky;top:0;height:100vh;padding:24px;background:#10243f;color:#fff}}aside a{{display:block;color:#d7e7ff;text-decoration:none;margin:10px 0}}main{{padding:32px;max-width:1100px}}h1,h2{{line-height:1.2}}section{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px;margin:0 0 20px;box-shadow:0 2px 8px #13233a0d}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);width:34%}}.banner{{border-left:8px solid var(--green);background:#e9f7ef;padding:18px;border-radius:8px;font-size:1.2rem;font-weight:700}}.badge{{display:inline-block;border-radius:999px;padding:4px 10px;font-weight:700;font-size:.85rem}}.pass{{background:#d9f3e5;color:var(--green)}}.warn{{background:#fff0c9;color:var(--amber)}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}.card{{border:1px solid var(--line);padding:14px;border-radius:8px;background:#fbfcfe}}.card strong{{display:block;font-size:1.6rem;color:var(--blue)}}.flow{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.flow span{{padding:10px;background:#e8f0fe;border:1px solid #b9cef4;border-radius:8px}}.notice{{background:#fff6dd;border-left:5px solid #d88a00;padding:14px}}@media(max-width:760px){{.layout{{display:block}}aside{{position:static;height:auto}}main{{padding:16px}}}}@media print{{aside{{display:none}}.layout{{display:block}}section{{break-inside:avoid;box-shadow:none}}}}
</style></head><body><div class="layout"><aside><h2>Phase 18</h2><nav><a href="#summary">Summary</a><a href="#architecture">Architecture</a><a href="#governance">Governance</a><a href="#evaluation">Evaluation</a><a href="#search">Historical search</a><a href="#tests">Evidence</a><a href="#decision">Decision</a></nav></aside><main id="top">
<section id="summary"><h1>Phase 18: Engineer-Validated Historical Roller Usage</h1><p>{_status(True, "Evidence report generated from executable synthetic workflow")}</p><div class="banner">ENGINEERING IMPLEMENTATION: {html.escape(evidence["decisions"]["engineering_implementation"])}<br>RECOGNITION PRODUCTION USE: NOT APPROVED<br>HISTORICAL SEARCH: {html.escape(evidence["decisions"]["historical_search"])}</div><p>Branch: <code>{html.escape(evidence["git"]["branch"])}</code> · Head: <code>{html.escape(evidence["git"]["head"])}</code></p><p>GitHub Actions: <a href="{html.escape(str(evidence["ci_run"].get("url") or "#"))}">{html.escape(str(evidence["ci_run"].get("run_id") or "not recorded"))}</a> · {html.escape(str(evidence["ci_run"].get("result") or "unknown"))}</p><p class="notice">Historical design evidence only. A confirmed design relationship does not identify a physical roller asset and does not constitute a tooling recommendation.</p></section>
<section id="architecture"><h2>End-to-end architecture</h2><div class="flow"><span>CAD occurrence</span>→<span>Phase 17 input hash</span>→<span>Independent labels</span>→<span>Adjudication</span>→<span>Locked dataset</span>→<span>Confirmed design usage</span>→<span>Historical evidence search</span></div><p>Physical assets, tooling recommendations, sequence generation, and manufacturability predictions remain outside this phase.</p></section>
<section id="governance"><h2>Dataset and review governance</h2><table><tr><th>Dataset</th><td>{html.escape(evidence["dataset"]["dataset_id"])} · locked status: {html.escape(evidence.get("locked", {}).get("status", "unknown"))}</td></tr><tr><th>Content hash</th><td><code>{html.escape(evidence.get("locked", {}).get("content_hash", "unknown"))}</code></td></tr><tr><th>Cases</th><td>{metrics.get("case_count", 0)}; project-grouped splits and two assertions per case</td></tr><tr><th>Outcomes</th><td>MATCH_DESIGN, NO_CATALOG_MATCH, NOT_A_ROLLER, INSUFFICIENT_DRAWING_EVIDENCE, UNRESOLVED</td></tr></table></section>
<section id="dataset"><h2>Synthetic fixture composition</h2><div class="cards">{''.join(f'<div class="card"><strong>{html.escape(str(v))}</strong>{html.escape(str(k).replace("_", " "))}</div>' for k,v in sorted(fixture.items()))}</div><p>Synthetic evidence is a regression fixture, not factory performance evidence.</p></section>
<section id="evaluation"><h2>Threshold and validation evidence</h2><table><tr><th>Dataset validation</th><td>{_status(bool(metrics.get("valid")), "locked cases resolved")}</td></tr><tr><th>Determinism hash</th><td><code>{html.escape(evidence["determinism_hash"])}</code></td></tr><tr><th>Production threshold approval</th><td>{_status(False, "requires engineer-labelled evidence and explicit approval")}</td></tr><tr><th>False-high-confidence gate</th><td>Tracked by threshold evaluation; no production claim from synthetic data</td></tr></table></section>
<section id="search"><h2>Historical relationship and search</h2><table><tr><th>Operational search</th><td>{evidence.get("operational_search", {}).get("total", 0)} synthetic records excluded by default</td></tr><tr><th>Fixture search with synthetic enabled</th><td>{evidence.get("synthetic_search", {}).get("total", 0)}</td></tr><tr><th>Relationship snapshot</th><td>{relationships.get("relationship_count", 0)} operational relationships; support is distinct-project based</td></tr></table></section>
<section id="tests"><h2>Evidence and safety gates</h2><table>{rows}</table><h3>Verification gates</h3><table>{''.join(f'<tr><th>{html.escape(str(k))}</th><td>{_status(bool(v), "verified")}</td></tr>' for k,v in sorted(gates.items()))}</table><ul><li>Automatic physical asset assignment: prohibited and false.</li><li>Tooling recommendation: not implemented.</li><li>Forming sequence and manufacturability prediction: not implemented.</li><li>Input hashes and audit events preserve the source lineage.</li></ul></section>
<section id="decision"><h2>Release decision and limitations</h2><div class="banner">ENGINEERING IMPLEMENTATION: {html.escape(decision_banner)}</div><p><strong>Recognition production use: NOT APPROVED.</strong> Engineer-labelled datasets, approved thresholds, and manufacturing review are still required.</p><p><strong>Historical search: {html.escape(evidence["decisions"]["historical_search"])}.</strong> Associations do not imply compatibility, availability, or recommendation.</p><h3>Phase 19 handoff</h3><p>Only after sufficient labelled evidence and approved relationship support may a later phase explore explainable historical tooling-set candidates.</p><a href="#top">Back to top</a></section>
</main></div></body></html>'''
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html_doc, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path, required=True)
    parser.add_argument("--html", dest="html_path", type=Path, required=True)
    args = parser.parse_args()
    generate(json.loads(args.evidence.read_text(encoding="utf-8")), args.json_path, args.html_path)
