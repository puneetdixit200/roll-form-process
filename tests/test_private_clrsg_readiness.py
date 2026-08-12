from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from rollform_extractor.clrsg_model import train_clrsg
from rollform_extractor.private_clrsg_readiness import (
    build_readiness_report,
    doctor_private_model,
    public_model_status,
    readiness_html,
)
from rollform_extractor.synthetic_sequence_factory import generate_public_corpus


def _rehash(root: Path) -> None:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    (root / "artifact_hashes.json").write_text(
        json.dumps(hashes, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _approved_private_fixture(root: Path) -> None:
    corpus = generate_public_corpus(samples_per_family=2, seed=1729)
    train_clrsg(corpus, root, ensemble_members=5, seed=1729)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "privacy_classification": "PRIVATE_PROTOTYPE_MODEL",
            "approval_status": "APPROVED_FOR_PRIVATE_PROTOTYPE",
            "activation_status": "ACTIVE",
            "ood_threshold_version": "validation_quantile_ood_v1",
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (root / "approval.json").write_text(
        json.dumps({"status": "APPROVED_FOR_PRIVATE_PROTOTYPE"}, indent=2),
        encoding="utf-8",
    )
    (root / "evaluation_metrics.json").write_text(
        json.dumps(
            {
                "quality_status": "PASS",
                "test": {
                    "baseline_rms": 0.48,
                    "learned_rms": 0.12,
                    "relative_improvement": 0.75,
                    "fallback_rate": 0.05,
                },
                "ood": {
                    "true_positive_rate": 1.0,
                    "validation_false_rejection_rate": 0.03,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (root / "ood_thresholds.json").write_text(
        json.dumps(
            {
                "thresholds": {
                    "in_distribution": 1.21,
                    "near_distribution": 1.31,
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _rehash(root)


def test_public_model_status_is_ready_and_path_safe(tmp_path: Path):
    model_root = tmp_path / "private-model"
    _approved_private_fixture(model_root)
    status = public_model_status(model_root)
    serialized = json.dumps(status)
    assert status["health"] == "READY"
    assert status["artifact_health"] == "VERIFIED"
    assert status["approval_status"] == "APPROVED_FOR_PRIVATE_PROTOTYPE"
    assert status["activation_status"] == "ACTIVE"
    assert status["evaluation"]["ood_true_positive_rate"] == 1.0
    assert str(tmp_path) not in serialized
    assert "model_root" not in serialized


def test_doctor_requires_active_environment_wiring(tmp_path: Path):
    model_root = tmp_path / "private-model"
    _approved_private_fixture(model_root)
    ready = doctor_private_model(model_root, str(model_root))
    not_ready = doctor_private_model(model_root, "")
    assert ready["status"] == "READY"
    assert ready["checks"]["environment_points_to_model"] is True
    assert not_ready["status"] == "NOT_READY"


def test_readiness_report_and_html_are_redacted(tmp_path: Path):
    model_root = tmp_path / "private-model"
    _approved_private_fixture(model_root)
    report = build_readiness_report(
        model_root,
        source_commit="test-sha",
        verification={"python_tests": 260, "frontend_build": "PASS"},
    )
    rendered = readiness_html(report)
    serialized = json.dumps(report)
    assert report["technical_readiness"] == "FAIL"
    assert report["model"]["approval_status"] == "APPROVED_FOR_PRIVATE_PROTOTYPE"
    assert report["quality_gates"]["ood_true_positive_at_least_75_percent"] is True
    assert "Manufacturing approval: NOT APPROVED" in rendered
    assert str(tmp_path) not in serialized
    assert "model_root" not in serialized
