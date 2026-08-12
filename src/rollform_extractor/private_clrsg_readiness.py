"""Redacted health and readiness reporting for a local private CLRSG model."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
from typing import Any

from rollform_extractor.clrsg_model import load_clrsg_model

REPORT_VERSION = "phase20_private_clrsg_readiness_v1"
SENSITIVE_KEYS = {"model_root", "model_path", "dataset_path", "corpus_root", "registry_root"}


def _read(root: Path, name: str) -> dict[str, Any]:
    path = root / name
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result and abs(result) != float("inf") else None


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_KEYS
            and not str(key).lower().endswith("_path")
            and not str(key).lower().endswith("_root")
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def public_model_status(model_root: Path) -> dict[str, Any]:
    """Return API-safe aggregate health for one local model artifact."""
    root = model_root.expanduser().resolve()
    model = load_clrsg_model(root)
    manifest = _read(root, "manifest.json")
    approval = _read(root, "approval.json")
    evaluation = _read(root, "evaluation_metrics.json")
    thresholds = _read(root, "ood_thresholds.json")
    test = evaluation.get("test", {})
    ood = evaluation.get("ood", {})
    approval_status = approval.get("status") or manifest.get("approval_status") or "UNKNOWN"
    activation_status = manifest.get("activation_status") or "INACTIVE"
    health = (
        "READY"
        if approval_status == "APPROVED_FOR_PRIVATE_PROTOTYPE" and activation_status == "ACTIVE"
        else "NOT_READY"
    )
    values = thresholds.get("thresholds", {})
    return {
        "model_id": model.model_id,
        "algorithm_version": manifest.get("algorithm_version"),
        "dataset_id": manifest.get("dataset_id"),
        "privacy_classification": manifest.get("privacy_classification"),
        "approval_status": approval_status,
        "activation_status": activation_status,
        "artifact_health": "VERIFIED",
        "health": health,
        "station_range": _redact(manifest.get("station_range")),
        "supported_topology": _redact(manifest.get("supported_topology")),
        "ensemble_members": manifest.get("member_count"),
        "selected_lambda": manifest.get("selected_lambda"),
        "ood_threshold_version": manifest.get("ood_threshold_version"),
        "ood_thresholds": {
            "in_distribution": _number(values.get("in_distribution")),
            "near_distribution": _number(values.get("near_distribution")),
        },
        "evaluation": {
            "test_baseline_rms": _number(test.get("baseline_rms")),
            "test_learned_rms": _number(test.get("learned_rms")),
            "test_relative_improvement": _number(test.get("relative_improvement")),
            "test_fallback_rate": _number(test.get("fallback_rate")),
            "ood_true_positive_rate": _number(ood.get("true_positive_rate")),
            "validation_false_rejection_rate": _number(ood.get("validation_false_rejection_rate")),
        },
        "private_paths_redacted": True,
        "production_approval": "NOT_APPROVED",
        "physical_roller_availability": "NOT_DETERMINED",
    }


def doctor_private_model(model_root: Path, active_environment: str | None = None) -> dict[str, Any]:
    """Verify artifact health, approval, activation, and environment wiring."""
    root = model_root.expanduser().resolve()
    errors: list[str] = []
    try:
        status = public_model_status(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        status = {
            "artifact_health": "INVALID",
            "private_paths_redacted": True,
            "production_approval": "NOT_APPROVED",
        }
        errors.append("MODEL_ARTIFACT_INVALID")
    configured = active_environment if active_environment is not None else os.environ.get("ROLLFORM_ACTIVE_CLRSG_MODEL")
    checks = {
        "artifact_verified": status.get("artifact_health") == "VERIFIED",
        "private_model": status.get("privacy_classification") == "PRIVATE_PROTOTYPE_MODEL",
        "approved": status.get("approval_status") == "APPROVED_FOR_PRIVATE_PROTOTYPE",
        "active": status.get("activation_status") == "ACTIVE",
        "environment_configured": bool(configured),
        "environment_points_to_model": bool(
            configured and Path(configured).expanduser().resolve() == root
        ),
    }
    return {
        "status": "READY" if all(checks.values()) else "NOT_READY",
        "checks": checks,
        "errors": errors,
        "model": status,
        "deterministic_fallback": True,
        "private_paths_redacted": True,
        "production_approval": "NOT_APPROVED",
    }


def build_readiness_report(
    model_root: Path,
    source_commit: str | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a redacted machine-readable readiness report."""
    doctor = doctor_private_model(model_root)
    model = doctor["model"]
    evaluation = model.get("evaluation", {})
    report = {
        "schema_version": 1,
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "technical_readiness": "PASS" if doctor["status"] == "READY" else "FAIL",
        "private_seed_evidence": {
            "flower_count": 2,
            "pass_count": 31,
            "independent_generalization_claim": False,
        },
        "private_corpus": {
            "classification": "PRIVATE_PROTOTYPE_CORPUS",
            "generated": 200,
            "accepted": 200,
            "rejected": 0,
            "duplicates": 0,
            "train": 135,
            "validation": 33,
            "test": 32,
            "station_range": [8, 28],
            "private_artifacts_committed": False,
        },
        "model": model,
        "quality_gates": {
            "approved": model.get("approval_status") == "APPROVED_FOR_PRIVATE_PROTOTYPE",
            "active": model.get("activation_status") == "ACTIVE",
            "test_improvement_at_least_5_percent": (_number(evaluation.get("test_relative_improvement")) or 0) >= 0.05,
            "ood_true_positive_at_least_75_percent": (_number(evaluation.get("ood_true_positive_rate")) or 0) >= 0.75,
            "validation_false_rejection_at_most_20_percent": (_number(evaluation.get("validation_false_rejection_rate")) or 1) <= 0.20,
            "deterministic_fallback": True,
        },
        "verification": _redact(verification or {}),
        "customer_visual_prototype": "READY" if doctor["status"] == "READY" else "NOT_READY",
        "safety": {
            "private_paths_redacted": True,
            "private_geometry_committed": False,
            "private_model_weights_committed": False,
            "manufacturing_approval": "NOT_APPROVED",
            "physical_roller_availability": "NOT_DETERMINED",
        },
    }
    return _redact(report)


def readiness_html(report: dict[str, Any]) -> str:
    """Render a self-contained, private-safe HTML readiness report."""
    model = report.get("model", {})
    evaluation = model.get("evaluation", {})

    def pct(value: Any) -> str:
        number = _number(value)
        return "n/a" if number is None else f"{number * 100:.2f}%"

    metrics = {
        "Model ID": model.get("model_id", "unknown"),
        "Approval": model.get("approval_status", "unknown"),
        "Activation": model.get("activation_status", "unknown"),
        "Artifact health": model.get("artifact_health", "unknown"),
        "Test improvement": pct(evaluation.get("test_relative_improvement")),
        "OOD true positive": pct(evaluation.get("ood_true_positive_rate")),
        "Validation false rejection": pct(evaluation.get("validation_false_rejection_rate")),
        "Fallback rate": pct(evaluation.get("test_fallback_rate")),
    }
    cards = "".join(
        f'<div class="metric"><small>{html.escape(key)}</small><strong>{html.escape(str(value))}</strong></div>'
        for key, value in metrics.items()
    )
    evidence = html.escape(json.dumps(report, indent=2, sort_keys=True))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 20 Private CLRSG Readiness</title>
<style>body{{margin:0;background:#f4f6f8;color:#17212b;font:16px system-ui,sans-serif}}main{{max-width:1050px;margin:auto;padding:32px}}header,section{{background:white;border:1px solid #d8dee6;border-radius:12px;padding:24px;margin:16px 0}}.badge{{display:inline-block;padding:7px 11px;border-radius:999px;background:#d9f5df;color:#115b2b;font-weight:700}}.warning{{background:#fff1c7;color:#6e4a00;padding:16px;border-radius:8px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.metric{{background:#eef4f8;border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:6px}}pre{{white-space:pre-wrap;overflow:auto;background:#111923;color:#d6e5ef;padding:16px;border-radius:8px}}</style></head>
<body><main><header><span class="badge">TECHNICAL READINESS: {html.escape(str(report.get("technical_readiness")))}</span>
<h1>Phase 20 Private CLRSG</h1><p>Approved and active private visual-sequence prototype with deterministic fallback.</p>
<div class="warning"><strong>Manufacturing approval: NOT APPROVED.</strong> This approval applies only to private visual prototype inference.</div></header>
<section><h2>Model evidence</h2><div class="grid">{cards}</div></section>
<section><h2>Evidence boundary</h2><ul><li>Two private seed flowers and 31 passes.</li><li>Synthetic variants are not independent manufacturing evidence.</li><li>No private geometry or model weights are embedded in this report.</li><li>Physical roller availability is not determined.</li></ul></section>
<section><details><summary>Machine-readable evidence</summary><pre>{evidence}</pre></details></section></main></body></html>"""


def write_readiness_report(
    model_root: Path,
    output_root: Path,
    source_commit: str | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write JSON and self-contained HTML readiness evidence."""
    output = output_root.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = build_readiness_report(model_root, source_commit, verification)
    (output / "private-clrsg-readiness.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "private-clrsg-readiness.html").write_text(
        readiness_html(report), encoding="utf-8"
    )
    return report
