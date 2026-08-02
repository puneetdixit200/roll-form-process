"""Strict corpus-readiness gate for canonical extraction artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from rollform_extractor.pass_features import PASS_FEATURE_SCHEMA_VERSION
from rollform_extractor.validation import validate_project


@dataclass(frozen=True)
class DatasetReadiness:
    status: str
    structural_validation: str
    manifest_validation: str
    canonical_geometry: str
    feature_completeness: str
    units_confirmation: str
    pass_order_confirmation: str
    determinism: str
    eligible_for_corpus_import: bool
    blockers: tuple[str, ...]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"blockers": list(self.blockers)}


def assess_dataset_readiness(project_path: Path) -> DatasetReadiness:
    validation = validate_project(project_path)
    blockers: list[str] = []
    report_data = _load_json(project_path / "report_data.json")
    project = _load_json(project_path / "project.json")
    flowers = report_data.get("composite_flowers", ())
    passes = [item for flower in flowers for item in flower.get("passes", ())]
    feature_count = sum(1 for item in passes if item.get("features"))
    units = (project.get("configuration_snapshot") or {}).get("units", {})
    project_units = project.get("units") if isinstance(project.get("units"), dict) else {}
    units_confirmed = bool(units.get("confirmed") or project_units.get("confirmed"))
    orders_confirmed = bool(passes) and all(item.get("engineer_confirmed_order") is not None for item in passes)
    if not units_confirmed:
        blockers.append("drawing units are not engineer-confirmed")
    if not orders_confirmed:
        blockers.append("pass order is not engineer-confirmed")
    if feature_count != len(passes):
        blockers.append(f"feature completeness is {feature_count}/{len(passes)}")
    if not validation.valid:
        blockers.append("structural validator has errors")
    if any(item.get("feature_schema_version") != PASS_FEATURE_SCHEMA_VERSION for item in passes if item.get("features")):
        blockers.append("feature schema is not current")
    determinism = _load_json(project_path / "determinism_summary.json")
    deterministic = bool(determinism.get("equal", False))
    if not deterministic:
        blockers.append("deterministic regeneration has not been recorded")
    if not flowers:
        blockers.append("no accepted canonical composite flower exists")
    status = "READY" if not blockers else "BLOCKED"
    return DatasetReadiness(
        status=status,
        structural_validation="PASS" if validation.valid else "FAIL",
        manifest_validation="PASS" if not any(issue.code in {"hash_mismatch", "missing_file", "source_hash_mismatch"} for issue in validation.issues) else "FAIL",
        canonical_geometry="PASS" if flowers and all(item.get("passes") for item in flowers) else "FAIL",
        feature_completeness="PASS" if feature_count == len(passes) else "FAIL",
        units_confirmation="PASS" if units_confirmed else "BLOCKED",
        pass_order_confirmation="PASS" if orders_confirmed else "BLOCKED",
        determinism="PASS" if deterministic else "BLOCKED",
        eligible_for_corpus_import=status == "READY",
        blockers=tuple(dict.fromkeys(blockers)),
        counts={"composite_flowers": len(flowers), "composite_passes": len(passes), "feature_sets": feature_count},
    )


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
