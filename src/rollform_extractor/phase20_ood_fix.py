"""Re-evaluate an existing private CLRSG model after OOD guard updates.

This module changes no private geometry and does not retrain the model. It
re-runs held-out evaluation with the current inference code, refreshes artifact
hashes, applies the existing approval gates, and optionally activates only an
approved model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rollform_extractor.private_clrsg import (
    _refresh_hashes,
    activate_private_model,
    approve_private_model,
    evaluate_model,
    evaluate_real_seed_sequences,
    load_private_seeds,
)
from rollform_extractor.synthetic_corpus_schema import load_corpus


def reevaluate_private_model(
    corpus_root: Path,
    model_root: Path,
    *,
    dataset_path: Path | None = None,
    registry_root: Path | None = None,
    activate_if_approved: bool = False,
) -> dict[str, Any]:
    """Re-evaluate and gate an existing local private model.

    Paths remain local and are omitted from the returned redacted summary.
    """
    corpus_root = corpus_root.expanduser().resolve()
    model_root = model_root.expanduser().resolve()
    corpus = load_corpus(corpus_root)
    evaluation = evaluate_model(model_root, corpus)
    if dataset_path is not None:
        evaluation["real_seed_diagnostics"] = evaluate_real_seed_sequences(
            model_root,
            load_private_seeds(dataset_path),
        )

    (model_root / "evaluation_metrics.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (model_root / "validation_metrics.json").write_text(
        json.dumps(
            {
                **evaluation["validation"],
                "ood": evaluation["ood"],
                "geometry_guard": {
                    "version": "visual_geometry_guard_v1",
                    "purpose": "Reject non-smooth high-frequency contours before learned inference.",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (model_root / "calibration.json").write_text(
        json.dumps(evaluation["calibration"], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _refresh_hashes(model_root)

    approval = approve_private_model(model_root)
    activation: dict[str, Any] = {"status": "INACTIVE"}
    if (
        activate_if_approved
        and approval["status"] == "APPROVED_FOR_PRIVATE_PROTOTYPE"
    ):
        if registry_root is None:
            raise ValueError("registry_root is required for activation")
        activation = activate_private_model(model_root, registry_root)

    return {
        "model_id": evaluation["model_id"],
        "quality_status": evaluation["quality_status"],
        "approval": approval,
        "activation": activation,
        "test": evaluation["test"],
        "ood": evaluation["ood"],
        "real_seed_diagnostics": evaluation.get("real_seed_diagnostics"),
        "private_paths_redacted": True,
        "manufacturing_approval": "NOT_APPROVED",
    }
