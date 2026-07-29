from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from rollform_extractor.pipeline import ExtractionRequest, extract_project
from rollform_extractor.review_apply import apply_review_decisions
from rollform_extractor.web.backend.jobs.store import PIPELINE_STAGES, JobStore


class AnalysisService:
    def __init__(self, store: JobStore):
        self.store = store

    def run_job(self, project_id: str, job_id: str) -> None:
        project = self.store.read_project(project_id)
        source = Path(project["source"]["stored_path"])
        try:
            for stage in PIPELINE_STAGES[1:-1]:
                self.store.record_stage(job_id, stage, "running")
                if stage == "CONVERTING":
                    self.store.record_stage(job_id, stage, "complete", "Input staged for converter/pipeline")
                elif stage in {"PARSING", "DETECTING_FLOWERS", "EXTRACTING_PASSES", "ANALYSING_GEOMETRY"}:
                    self.store.record_stage(job_id, stage, "complete", "Handled by deterministic Python extraction pipeline")
            output_root = self.store.project_output_root(project_id)
            summary = extract_project(ExtractionRequest(source, output_root))
            report_data = _read_report(summary.project_path)
            self.store.record_stage(job_id, "GENERATING_REPORT", "complete", "Report and artifacts generated")
            self.store.update_project(
                project_id,
                status="CANDIDATE_READY",
                summary=_summary(summary.project_path, report_data),
                report_data_path=str(summary.project_path / "report_data.json"),
                project_path=str(summary.project_path),
            )
            self.store.update_job(job_id, status="CANDIDATE_READY")
            self.store.record_stage(job_id, "CANDIDATE_READY", "complete")
        except Exception as exc:
            self.store.record_stage(job_id, "FAILED", "failed", str(exc))
            self.store.update_project(project_id, status="FAILED", error=str(exc))
            self.store.update_job(job_id, status="FAILED")

    def apply_review(self, project_id: str, decisions: dict[str, Any]) -> dict[str, Any]:
        project_path = self.store.project_output_path(project_id)
        if project_path is None:
            raise FileNotFoundError("Project has no analysis output yet")
        revision = int(self.store.read_project(project_id).get("revision", 1)) + 1
        review_dir = self.store.project_dir(project_id) / "review_decisions"
        review_dir.mkdir(parents=True, exist_ok=True)
        decisions_path = review_dir / f"manual_review_decisions_r{revision:03d}.json"
        decisions_path.write_text(json.dumps(decisions, indent=2, sort_keys=True), encoding="utf-8")
        applied_path = apply_review_decisions(project_path, decisions_path)
        report_data = _read_report(project_path)
        return self.store.update_project(
            project_id,
            revision=revision,
            status="CANDIDATE_READY",
            summary=_summary(project_path, report_data),
            last_review_decisions=str(decisions_path),
            last_applied_review=str(applied_path),
        )

    def create_resume_job(self, project_id: str) -> str:
        job_id = uuid4().hex
        self.store._write_job(  # intentional local store write for resume command
            job_id,
            {
                "job_id": job_id,
                "project_id": project_id,
                "status": "PENDING",
                "stages": [{"stage": "UPLOADED", "status": "complete", "started_at": _now(), "ended_at": _now(), "logs": [], "warnings": []}],
                "logs": [],
                "warnings": [],
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        return job_id


def _read_report(project_path: Path) -> dict[str, Any]:
    report = project_path / "report_data.json"
    if not report.exists():
        return {"project": {}, "sequences": [], "composite_flowers": [], "warnings": []}
    return json.loads(report.read_text(encoding="utf-8"))


def _summary(project_path: Path, report_data: dict[str, Any]) -> dict[str, Any]:
    flowers = report_data.get("composite_flowers", [])
    passes = [item for flower in flowers for item in flower.get("passes", [])]
    return {
        "project_path": str(project_path),
        "candidate_extraction": True,
        "production_approved": False,
        "composite_flower_count": len(flowers),
        "candidate_pass_count": len(passes),
        "canonical_bend_zone_count": len({bend["bend_id"] for item in passes for bend in item.get("bend_zones", item.get("physical_bends", []))}),
        "profile_step_change_count": sum(len(flower.get("profile_step_changes", [])) for flower in flowers),
        "bend_change_event_count": sum(len(flower.get("bend_change_events", [])) for flower in flowers),
        "segment_change_event_count": sum(len(flower.get("segment_change_events", [])) for flower in flowers),
        "confirmed_transition_count": int((report_data.get("project") or {}).get("confirmed_transitions") or 0),
        "units_confirmed": bool(((report_data.get("project") or {}).get("units") or {}).get("confirmed")),
        "unresolved_review_items": [
            {"from": change.get("from_pass_id"), "to": change.get("to_pass_id"), "choices": change.get("review_choices")}
            for flower in flowers
            for change in flower.get("profile_step_changes", [])
            if change.get("review_choices")
        ],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
