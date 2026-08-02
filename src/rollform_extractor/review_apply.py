from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rollform_extractor.pipeline import regenerate_project


class ReviewApplyError(ValueError):
    pass


def apply_review_decisions(project_path: Path, decisions_path: Path, *, dry_run: bool = False) -> Path | dict[str, Any]:
    """Validate and apply review through atomic regeneration.

    The original review file is immutable evidence.  Calculated JSON and HTML
    are never patched in place.  Schema-v1 station/unit overrides remain
    compatible; schema-v2 pass-order decisions are preserved as authoritative
    review evidence and remain blocked until the domain pipeline consumes an
    engineer-confirmed order.
    """
    if not project_path.is_dir():
        raise ReviewApplyError(f"project path does not exist: {project_path}")
    if not decisions_path.is_file():
        raise ReviewApplyError(f"review decision file does not exist: {decisions_path}")
    try:
        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
        project = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewApplyError(f"invalid review input: {exc}") from exc
    if not isinstance(decisions, dict) or decisions.get("schema_version") not in {1, 2}:
        raise ReviewApplyError("review schema_version must be 1 or 2")
    source_sha = project.get("source_sha256")
    expected_source_sha = decisions.get("source_sha256") or decisions.get("drawing_sha256")
    if expected_source_sha and source_sha and expected_source_sha != source_sha:
        raise ReviewApplyError("review source hash does not match current project")
    _validate_handles(project, decisions)
    proposed = _proposed_changes(project, decisions)
    if dry_run:
        # Dry-run is intentionally side-effect free. The caller owns display
        # or temporary capture of this proposal; no project artifact is
        # created and no manifest can be invalidated.
        return {"dry_run": True, "proposed_changes": proposed}

    review_dir = project_path / "review"
    review_dir.mkdir(exist_ok=True)
    review_sha = _sha256(decisions_path)
    applied = review_dir / f"applied_review_{review_sha[:16]}.json"
    applied.write_text(json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8")
    # Keep the long-standing compatibility path while retaining the
    # content-addressed immutable copy for audit and supersession tracking.
    (review_dir / "applied_review.json").write_text(
        json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8"
    )
    regenerate_project(project_path, review_decisions=decisions)
    return applied


def _validate_handles(project: dict[str, Any], decisions: dict[str, Any]) -> None:
    known = {handle for profile in project.get("profiles", ()) for handle in profile.get("source_handles", ())}
    known.update(handle for station in project.get("stations", ()) for handle in station.get("source_handles", ()))
    rows = decisions.get("pass_order_decisions", decisions.get("composite_passes", ()))
    for row in rows:
        for handle in row.get("source_handles", ()):
            if handle not in known:
                raise ReviewApplyError(f"review references unknown source handle: {handle}")


def _proposed_changes(project: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    rows = decisions.get("pass_order_decisions", decisions.get("composite_passes", ()))
    return {
        "pass_order_changes": [
            {"pass_id": row.get("pass_id"), "confirmed_order": row.get("confirmed_order"), "station_id": row.get("confirmed_station_id"), "decision": row.get("decision")}
            for row in rows
        ],
        "unit_change": decisions.get("drawing_units", {}),
        "affected_feature_sets": len(rows),
        "affected_transitions": max(0, len(rows) - 1),
        "affected_files": ["project.json", "project.sqlite", "report_data.json", "report.html", "manifest.json"],
        "readiness_blockers_remaining": ["reviewed values require engineer confirmation and deterministic regeneration"],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
