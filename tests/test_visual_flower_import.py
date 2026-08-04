import ezdxf
from fastapi.testclient import TestClient

from rollform_extractor.web.backend.api.app import create_app


def _dxf_bytes() -> bytes:
    document = ezdxf.new("R2018")
    document.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
    document.modelspace().add_lwpolyline([(20, 0), (25, 0), (25, 2)])
    return _save_bytes(document)


def _save_bytes(document) -> bytes:
    import io
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def test_dxf_import_detects_multiple_profiles_and_selects_target(tmp_path):
    with TestClient(create_app(tmp_path, auto_run_jobs=False)) as client:
        response = client.post("/api/visual-flower/import", files={"file": ("synthetic.dxf", _dxf_bytes(), "application/dxf")})
        assert response.status_code == 200
        import_id = response.json()["import_id"]
        profiles = client.get(f"/api/visual-flower/imports/{import_id}/profiles")
        assert profiles.status_code == 200
        assert len(profiles.json()) == 2
        selected = profiles.json()[0]["profile_id"]
        target = client.post(f"/api/visual-flower/imports/{import_id}/profiles/{selected}/use")
        assert target.status_code == 200
        assert target.json()["profile"]["schema_version"] == 1
        assert target.json()["profile"]["metadata"]["source"] == "OFFLINE_CAD_IMPORT"


def test_invalid_cad_extension_is_rejected(tmp_path):
    with TestClient(create_app(tmp_path, auto_run_jobs=False)) as client:
        response = client.post("/api/visual-flower/import", files={"file": ("secret.txt", b"not cad", "text/plain")})
        assert response.status_code == 400
