from pathlib import Path

from fastapi.testclient import TestClient

from rollform_extractor.web.backend.api.app import create_app
from rollform_extractor.web.backend.demo_auth import hash_password


def _app(monkeypatch, tmp_path, enabled=True):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("DEMO_USERNAME", "demo")
    monkeypatch.setenv("DEMO_PASSWORD_HASH", hash_password("correct horse"))
    monkeypatch.setenv("DEMO_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("ROLLFORM_REQUIRE_PRIVATE_DATASET", "false")
    monkeypatch.setenv("ROLLFORM_REQUIRE_ACTIVE_MODEL", "false")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><body>demo</body></html>", encoding="utf-8")
    monkeypatch.setenv("ROLLFORM_FRONTEND_DIST", str(frontend))
    return create_app(tmp_path / "workspace", auto_run_jobs=False)


def test_auth_boundary_and_logout(monkeypatch, tmp_path):
    client = TestClient(_app(monkeypatch, tmp_path))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ready").status_code == 200
    assert client.get("/api/inventory/stats").status_code == 401
    assert client.post("/api/auth/login", json={"username": "demo", "password": "wrong"}).status_code == 401
    login = client.post("/api/auth/login", json={"username": "demo", "password": "correct horse"})
    assert login.status_code == 200
    assert client.get("/api/inventory/stats").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/inventory/stats").status_code == 401


def test_cad_upload_limits_and_extension(monkeypatch, tmp_path):
    client = TestClient(_app(monkeypatch, tmp_path, enabled=False))
    bad = client.post("/api/visual-flower/import", files={"file": ("input.txt", b"x", "text/plain")})
    assert bad.status_code == 400
    monkeypatch.setenv("ROLLFORM_MAX_UPLOAD_BYTES", "3")
    large = client.post("/api/visual-flower/import", files={"file": ("input.dxf", b"1234", "application/dxf")})
    assert large.status_code == 413


def test_railway_image_contract_and_same_origin_defaults():
    root = Path(__file__).parents[1]
    dockerfile = (root / "Dockerfile.railway").read_text(encoding="utf-8")
    client = (root / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "uvicorn backend.api.railway_main:app" in dockerfile
    assert "VITE_API_ROOT ?? \"\"" in client
    assert "/home/pd" not in dockerfile
