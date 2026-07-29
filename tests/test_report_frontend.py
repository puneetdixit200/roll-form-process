from __future__ import annotations

from pathlib import Path


STATIC = Path("src/rollform_extractor/report/static/report.js")
TEMPLATE = Path("src/rollform_extractor/report/templates/report.html.j2")


def test_flower_viewer_javascript_wires_navigation_and_pass_selection():
    script = STATIC.read_text(encoding="utf-8")

    assert 'document.querySelector(\'[data-action="prev"]\').onclick' in script
    assert 'document.querySelector(\'[data-action="next"]\').onclick' in script
    assert 'el("sequence-slider").oninput' in script
    assert 'el("pass-selector").onchange' in script
    assert 'document.querySelectorAll("[data-card]")' in script


def test_flower_viewer_javascript_exposes_required_view_modes():
    script = STATIC.read_text(encoding="utf-8")

    for mode in ("single", "previous-current", "overlay", "cumulative", "complete", "original-normalized"):
        assert mode in script


def test_flower_viewer_filters_missing_download_links_and_uses_embedded_data():
    script = STATIC.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert 'document.getElementById("report-data").textContent' in script
    assert "filter(([, v]) => v)" in script
    assert 'id="report-data"' in template
    assert "report_data_json" in template
