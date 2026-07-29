from __future__ import annotations

import html
import json
from pathlib import Path

from rollform_extractor.database import ExtractionBundle
from rollform_extractor.models import WarningRecord
from rollform_extractor.report.report_data import build_report_data


ROOT = Path(__file__).resolve().parent


def write_engineering_report(bundle: ExtractionBundle, project_path: Path, warnings: tuple[WarningRecord, ...]) -> None:
    data = build_report_data(bundle, project_path, warnings)
    data_json = json.dumps(data, indent=2, sort_keys=True)
    (project_path / "report_data.json").write_text(data_json, encoding="utf-8")
    template = (ROOT / "templates" / "report.html.j2").read_text(encoding="utf-8")
    css = (ROOT / "static" / "report.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "report.js").read_text(encoding="utf-8")
    html_text = template.replace("{{ title }}", html.escape(bundle.drawing_id))
    html_text = html_text.replace("{{ css }}", css)
    html_text = html_text.replace("{{ report_data_json }}", html.escape(data_json, quote=False))
    html_text = html_text.replace("{{ js }}", js)
    (project_path / "report.html").write_text(html_text, encoding="utf-8")
