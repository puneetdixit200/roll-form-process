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


def test_connected_line_arc_chain_imports_as_one_editable_target(tmp_path):
    document = ezdxf.new("R2018")
    document.header["$INSUNITS"] = 4
    modelspace = document.modelspace()
    modelspace.add_line((0, 0), (10, 0), dxfattribs={"layer": "PROFILE"})
    modelspace.add_arc((10, 5), 5, 270, 360, dxfattribs={"layer": "PROFILE"})
    modelspace.add_line((15, 5), (22, 5), dxfattribs={"layer": "PROFILE"})
    with TestClient(create_app(tmp_path, auto_run_jobs=False)) as client:
        response = client.post("/api/visual-flower/import", files={"file": ("connected.dxf", _save_bytes(document), "application/dxf")})
        assert response.status_code == 200
        profiles = client.get(f"/api/visual-flower/imports/{response.json()['import_id']}/profiles").json()
        assert len(profiles) == 1
        assert profiles[0]["entity_count"] == 3
        assert profiles[0]["source_units"] == "mm"
        target = client.post(f"/api/visual-flower/imports/{response.json()['import_id']}/profiles/{profiles[0]['profile_id']}/use")
        assert target.status_code == 200
        assert target.json()["profile"]["segments"][1]["type"] == "ARC"


def test_integrated_import_creates_linked_visual_and_project_workflow(tmp_path):
    with TestClient(create_app(tmp_path, auto_run_jobs=False)) as client:
        response = client.post("/api/rollform-workflows/import", files={"file": ("synthetic.dxf", _dxf_bytes(), "application/dxf")})
        assert response.status_code == 200
        workflow = response.json()
        assert workflow["visual_import_id"].startswith("vimport-")
        assert workflow["project_id"]
        status = client.get(f"/api/rollform-workflows/{workflow['workflow_id']}")
        assert status.status_code == 200
        assert status.json()["source_sha256"] == workflow["source_sha256"]


def test_integrated_workflow_exposes_profiles_and_requires_selected_target_for_generation(tmp_path):
    with TestClient(create_app(tmp_path, auto_run_jobs=False)) as client:
        imported = client.post("/api/rollform-workflows/import", files={"file": ("synthetic.dxf", _dxf_bytes(), "application/dxf")}).json()
        profiles = client.get(f"/api/rollform-workflows/{imported['workflow_id']}/profiles")
        assert profiles.status_code == 200
        assert len(profiles.json()) == 2
        generate = client.post(f"/api/rollform-workflows/{imported['workflow_id']}/generate", json={"station_mode": "EXACT", "exact_station_count": 16})
        assert generate.status_code == 409
