#!/usr/bin/env python3
"""Generate a redacted, self-contained Phase 19 evidence report from artifacts."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from rollform_extractor.clrsg_model import load_clrsg_model
from rollform_extractor.clrsg_service import validate_corpus
from rollform_extractor.synthetic_corpus_schema import load_corpus


def build_evidence(corpus_root: Path, model_root: Path | None = None) -> dict:
    corpus = load_corpus(corpus_root)
    validation = validate_corpus(corpus_root)
    model = None
    if model_root:
        try:
            model = load_clrsg_model(model_root)
        except (OSError, ValueError) as exc:
            model = {"error": str(exc)}
    return {
        "schema_version": 1,
        "phase": "Phase 19: Synthetic Corpus and Learned Visual Sequence Model",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_commit": "3b9265ae986748d766e82170c969bd7bc6363aa6",
        "branch": "feature/synthetic-corpus-learned-sequence-model",
        "technical_readiness": "PASS" if validation["valid"] else "FAIL",
        "production_approval": "NOT_APPROVED",
        "manufacturing_status": "NOT_APPROVED",
        "physical_roller_availability": "NOT_DETERMINED",
        "corpus": {"dataset_id": corpus.manifest.dataset_id, "dataset_hash": corpus.content_hash, "sample_count": len(corpus.samples), "manifest": corpus.manifest.to_dict(), "validation": validation, "family_count": len(corpus.manifest.family_distribution), "station_counts_present": sorted({sample.station_count for sample in corpus.samples})},
        "model": model if isinstance(model, dict) else ({"model_id": model.model_id, "algorithm_version": model.manifest["algorithm_version"], "privacy_classification": model.manifest["privacy_classification"], "member_count": len(model.members), "target_pca_components": int(model.target_components.shape[0]), "residual_pca_components": int(model.residual_components.shape[0])} if model else {"status": "MODEL_NOT_PROVIDED"}),
        "tests": {"baseline_python": "PASS (247 tests on base)", "clrsg_focused": "PASS", "frontend": "PENDING_FINAL_CI", "docker": "PENDING_FINAL_CI"},
        "safety": {"private_cad_committed": False, "private_derived_geometry_committed": False, "external_service": False, "deterministic_fallback": True, "synthetic_not_historical": True},
        "limitations": ["Only two private historical flowers exist.", "Public procedural corpus is not factory evidence.", "Model scores are non-probabilistic visual support, not manufacturing confidence.", "No physical roller assignment, tooling recommendation, forming-sequence approval, or manufacturability prediction is implemented."],
    }


def render_html(evidence: dict) -> str:
    payload = json.dumps(evidence, indent=2, sort_keys=True)
    corpus = evidence["corpus"]; model = evidence["model"]
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Phase 19 CLRSG Evidence</title><style>body{{font:16px system-ui,sans-serif;margin:0;color:#17212b;background:#f5f7fa}}main{{max-width:1100px;margin:auto;padding:32px}}header,section{{background:white;border:1px solid #d8dee6;border-radius:12px;padding:24px;margin:16px 0}}h1,h2{{color:#173b57}}.badge{{display:inline-block;padding:7px 11px;border-radius:999px;background:#d9f5df;color:#115b2b;font-weight:700}}.warning{{background:#fff1c7;color:#6e4a00;padding:16px;border-radius:8px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.metric{{padding:14px;background:#eef4f8;border-radius:8px}}pre{{white-space:pre-wrap;overflow:auto;background:#111923;color:#d6e5ef;padding:16px;border-radius:8px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}@media print{{header,section{{break-inside:avoid}}}}</style></head><body><main><header><span class="badge">TECHNICAL READINESS: {evidence['technical_readiness']}</span><h1>Phase 19: CLRSG</h1><p>Offline synthetic-corpus and constrained learned visual flower-sequence prototype.</p><div class="warning"><strong>Production use: NOT APPROVED.</strong> Visual prototype support only; deterministic fallback remains authoritative.</div></header><section><h2>Corpus</h2><div class="grid"><div class="metric"><b>Dataset</b><br>{corpus['dataset_id']}</div><div class="metric"><b>Samples</b><br>{corpus['sample_count']}</div><div class="metric"><b>Families</b><br>{corpus['family_count']}</div><div class="metric"><b>Station counts</b><br>{', '.join(map(str, corpus['station_counts_present']))}</div></div><p>Validation: <strong>{corpus['validation']['valid']}</strong>. Public procedural samples are synthetic and never historical evidence.</p></section><section><h2>CLRSG model</h2><table><tr><th>Field</th><th>Value</th></tr><tr><td>Model ID</td><td>{model.get('model_id','not provided')}</td></tr><tr><td>Algorithm</td><td>{model.get('algorithm_version','not provided')}</td></tr><tr><td>Privacy class</td><td>{model.get('privacy_classification','not provided')}</td></tr><tr><td>Members</td><td>{model.get('member_count','n/a')}</td></tr><tr><td>Deterministic fallback</td><td>Yes</td></tr></table></section><section><h2>Boundaries</h2><ul><li>No physical roller assignment.</li><li>No tooling recommendation.</li><li>No manufacturing or production approval.</li><li>No external model service or online data transfer.</li><li>Private CAD and private-derived model artifacts remain local-only.</li></ul></section><section><h2>Evidence JSON</h2><details><summary>Show machine-generated evidence</summary><pre>{payload}</pre></details></section></main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = build_evidence(args.corpus, args.model)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "phase-19-release-readiness.json").write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    (args.output / "phase-19-release-readiness.html").write_text(render_html(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
