from __future__ import annotations

from pathlib import Path

from rollform_extractor.web.backend.demo_auth import configuration_errors, hash_password
from rollform_extractor.web.backend.jobs.store import JobStore


def test_job_store_sanitizes_uploaded_filename(tmp_path):
    store = JobStore(tmp_path / "workspace")
    content = b"0\nSECTION\n0\nEOF\n"
    record = store.create_upload("../../outside/evil.dxf", content)

    assert record.original_filename == "evil.dxf"
    assert record.source_path.name == "evil.dxf"
    assert record.source_path.parent.name == "source"
    assert (tmp_path / "outside" / "evil.dxf").exists() is False
    assert record.source_path.is_file()


def test_demo_auth_configuration_rejects_missing_or_weak_secrets(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.delenv("DEMO_USERNAME", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("DEMO_SESSION_SECRET", "short")

    errors = configuration_errors()
    assert any("DEMO_USERNAME" in item for item in errors)
    assert any("DEMO_PASSWORD_HASH" in item for item in errors)
    assert any("DEMO_SESSION_SECRET" in item for item in errors)


def test_demo_auth_configuration_accepts_valid_configuration(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEMO_USERNAME", "customer-demo")
    monkeypatch.setenv("DEMO_PASSWORD_HASH", hash_password("a sufficiently long demo password"))
    monkeypatch.setenv("DEMO_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("DEMO_SESSION_TTL_SECONDS", "28800")

    assert configuration_errors() == []


def test_railway_dockerfile_uses_fail_closed_entrypoint():
    dockerfile = (Path(__file__).parents[1] / "Dockerfile.railway").read_text(encoding="utf-8")
    assert "backend.api.railway_main:app" in dockerfile
    assert "backend.api.main:app" not in dockerfile
