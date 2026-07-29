from __future__ import annotations

import html
import json
from pathlib import Path


class ReviewApplyError(ValueError):
    pass


def apply_review_decisions(project_path: Path, decisions_path: Path) -> Path:
    if not project_path.exists():
        raise ReviewApplyError(f"project path does not exist: {project_path}")
    if not decisions_path.exists():
        raise ReviewApplyError(f"review decision file does not exist: {decisions_path}")
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    if decisions.get("schema_version") != 1:
        raise ReviewApplyError("manual_review_decisions schema_version must be 1")
    review_dir = project_path / "review"
    review_dir.mkdir(exist_ok=True)
    applied_path = review_dir / "applied_review.json"
    applied_path.write_text(json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8")
    report_data_path = project_path / "report_data.json"
    if report_data_path.exists():
        data = json.loads(report_data_path.read_text(encoding="utf-8"))
        data["manual_review_decisions"] = decisions
        data["project"]["units_review"] = decisions.get("drawing_units", {})
        _apply_pass_decisions(data, decisions)
        report_data_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        _replace_embedded_report_data(project_path / "report.html", data)
    return applied_path


def _apply_pass_decisions(data: dict, decisions: dict) -> None:
    by_pass = {item.get("pass_id"): item for item in decisions.get("composite_passes", ())}
    confirmed = 0
    for flower in data.get("composite_flowers", ()):
        for item in flower.get("passes", ()):
            decision = by_pass.get(item.get("pass_id"))
            if not decision:
                continue
            item["engineer_review"] = decision
            item["engineer_confirmed_order"] = decision.get("confirmed_order", item.get("engineer_confirmed_order"))
            if decision.get("confirmed"):
                item["status"] = "Engineer confirmed"
                item["requires_review"] = False
                confirmed += 1
        flower["review_completion"] = {
            "passes_confirmed": confirmed,
            "orders_confirmed": sum(1 for item in flower.get("passes", ()) if item.get("engineer_confirmed_order") is not None),
            "bends_confirmed": 0,
            "units_confirmed": bool(decisions.get("drawing_units", {}).get("engineer_confirmed_unit")),
            "station_links_confirmed": 0,
            "tooling_links_confirmed": 0,
        }


def _replace_embedded_report_data(report_path: Path, data: dict) -> None:
    if not report_path.exists():
        return
    text = report_path.read_text(encoding="utf-8")
    start_tag = '<script id="report-data" type="application/json">'
    end_tag = "</script>"
    start = text.find(start_tag)
    if start < 0:
        return
    content_start = start + len(start_tag)
    end = text.find(end_tag, content_start)
    if end < 0:
        return
    encoded = html.escape(json.dumps(data, indent=2, sort_keys=True), quote=False)
    report_path.write_text(text[:content_start] + encoded + text[end:], encoding="utf-8")
