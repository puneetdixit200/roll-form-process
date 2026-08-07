#!/usr/bin/env python3
"""One-command local launcher and public-safe smoke verification for the visual demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from rollform_extractor.private_clrsg_readiness import doctor_private_model

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("ROLLFORM_DEMO_RUNTIME", "/tmp/rollform-visual-flower-demo"))
PID_FILE = RUNTIME / "pids.json"
LOG_DIR = RUNTIME / "logs"


def _configured(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value and Path(value).expanduser().exists() else None


def _port_available(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _get(path: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=5) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return response.status, body.decode("utf-8", "replace")
    except (OSError, urllib.error.URLError) as exc:
        return 0, {"error": type(exc).__name__}


def _post(path: str, payload: object) -> tuple[int, object]:
    request = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def doctor() -> dict:
    checks: dict[str, bool] = {}
    checks["repository_root"] = ROOT.is_dir() and (ROOT / "pyproject.toml").is_file()
    checks["python_version"] = sys.version_info >= (3, 12)
    try:
        __import__("rollform_extractor")
        checks["editable_package_import"] = True
    except ImportError:
        checks["editable_package_import"] = False
    checks["node"] = shutil.which("node") is not None
    checks["npm"] = shutil.which("npm") is not None
    checks["frontend_dependencies"] = (ROOT / "frontend" / "node_modules").is_dir()
    dataset = _configured("ROLLFORM_FLOWER_PROTOTYPE_DATASET")
    model_root = _configured("ROLLFORM_ACTIVE_CLRSG_MODEL")
    checks["private_dataset_configured"] = dataset is not None and Path(dataset).name == "dataset.json"
    checks["active_model_configured"] = model_root is not None
    checks["backend_port_available"] = _port_available(8000) or _get("/api/health")[0] == 200
    try:
        with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=2) as response:
            frontend_responding = response.status == 200
    except OSError:
        frontend_responding = False
    checks["frontend_port_available"] = _port_available(5173) or frontend_responding
    checks["runtime_writable"] = os.access(RUNTIME.parent, os.W_OK)
    model = {"status": "NOT_CONFIGURED", "private_paths_redacted": True}
    if model_root:
        model = doctor_private_model(Path(model_root))
        checks["model_ready"] = model.get("status") == "READY"
        checks["artifact_hashes"] = model.get("checks", {}).get("artifact_verified", False)
    else:
        checks["model_ready"] = False
        checks["artifact_hashes"] = False
    status = "PASS" if all(checks.values()) else "WARN" if checks.get("editable_package_import") and checks.get("runtime_writable") else "FAIL"
    return {"status": status, "checks": checks, "model": model, "private_paths_redacted": True, "production_approval": "NOT_APPROVED"}


def _owned_process(pid: int, marker: str) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        return False
    return marker in command


def _read_pids() -> dict[str, int]:
    try:
        return {key: int(value) for key, value in json.loads(PID_FILE.read_text()).items()}
    except (OSError, ValueError, TypeError):
        return {}


def start() -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True); LOG_DIR.mkdir(exist_ok=True)
    existing = _read_pids()
    if existing and all(_owned_process(pid, "uvicorn") or _owned_process(pid, "vite") for pid in existing.values()):
        return status()
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    backend_log = (LOG_DIR / "backend.log").open("ab")
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.api.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT, env=env, stdout=backend_log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if _get("/api/health")[0] == 200:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("backend health check timed out")
        frontend_log = (LOG_DIR / "frontend.log").open("ab")
        frontend = subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], cwd=ROOT / "frontend", env=env, stdout=frontend_log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError("frontend HTTP check timed out")
        PID_FILE.write_text(json.dumps({"backend": backend.pid, "frontend": frontend.pid}, sort_keys=True), encoding="utf-8")
        model = _get("/api/visual-flower/model/status")[1]
        active = (model.get("active_models") or [{}])[0]
        return {"status": "PASS", "frontend_url": "http://127.0.0.1:5173/", "backend_url": "http://127.0.0.1:8000/", "active_model": active.get("model_id", "DETERMINISTIC_ONLY"), "private_paths_redacted": True}
    except Exception:
        os.killpg(backend.pid, signal.SIGTERM)
        raise


def stop() -> dict:
    stopped = []
    for name, pid in _read_pids().items():
        owned = _owned_process(pid, "uvicorn") if name == "backend" else (_owned_process(pid, "npm run dev") or _owned_process(pid, "vite"))
        if owned:
            os.killpg(pid, signal.SIGTERM); stopped.append(name)
    if PID_FILE.exists():
        PID_FILE.unlink()
    return {"status": "PASS", "stopped": stopped}


def status() -> dict:
    pids = _read_pids()
    backend_status, model = _get("/api/visual-flower/model/status")
    health = _get("/api/health")[0] == 200
    try:
        with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=3) as response:
            frontend = response.status == 200
    except OSError:
        frontend = False
    active = (model.get("active_models") or [{}])[0] if isinstance(model, dict) else {}
    return {"status": "PASS" if health and frontend else "WARN", "backend_running": health, "frontend_running": frontend, "health_endpoint": health, "model_status_endpoint": backend_status == 200, "active_model": active.get("model_id", "DETERMINISTIC_ONLY"), "approval": model.get("production_approval", "NOT_APPROVED") if isinstance(model, dict) else "NOT_APPROVED", "deterministic_fallback": model.get("deterministic_fallback", True) if isinstance(model, dict) else True, "pid_state": pids, "private_paths_redacted": True}


def verify() -> dict:
    checks: dict[str, object] = {"backend_health": _get("/api/health")[0] == 200, "frontend_http": False, "model_status": False, "model_doctor": False}
    try:
        with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=5) as response:
            checks["frontend_http"] = response.status == 200
    except OSError:
        pass
    status_code, model = _get("/api/visual-flower/model/status"); checks["model_status"] = status_code == 200 and bool(model.get("deterministic_fallback"))
    doctor_code, doctor_result = _get("/api/visual-flower/model/doctor"); checks["model_doctor"] = doctor_code == 200 and doctor_result.get("private_paths_redacted") is True
    fixture = ROOT / "tests" / "fixtures" / "visual_profiles" / "open_channel.json"
    profile = json.loads(fixture.read_text(encoding="utf-8")); created_code, created = _post("/api/visual-flower/targets", {"profile": profile})
    generated_code, generated = _post(f"/api/visual-flower/targets/{created.get('target_id')}/generate", {"generation_engine": "COMPARE_ALL", "station_mode": "EXACT", "exact_station_count": 16, "candidate_limit": 3}) if created_code == 200 else (0, {})
    candidates = generated.get("candidates", []) if isinstance(generated, dict) else []
    checks["public_target_generation"] = generated_code == 200
    checks["candidate_count"] = len(candidates)
    checks["sixteen_station_candidate"] = any(item.get("station_count") == 16 for item in candidates)
    checks["final_target_anchoring"] = all(item.get("passes", [{}])[-1].get("profile", {}).get("points") for item in candidates)
    if candidates:
        candidate_id = candidates[0]["candidate_id"]
        checks["json_export"] = _get(f"/api/visual-flower/candidates/{candidate_id}/export.json")[0] == 200
        checks["zip_export"] = _get(f"/api/visual-flower/candidates/{candidate_id}/export/zip")[0] == 200
    else:
        checks["json_export"] = False; checks["zip_export"] = False
    negative = json.loads(fixture.read_text(encoding="utf-8")); negative["profile_id"] = "PUBLIC-OOD-HIGH-FREQUENCY"; negative["name"] = "Public OOD probe"
    negative["vertices"] = [{"vertex_id": f"ood-v{index}", "x": -3.0 + index * 0.3, "y": 0.45 if index % 2 else -0.45} for index in range(21)]
    negative["segments"] = [{"segment_id": f"ood-s{index}", "type": "LINE", "start_vertex_id": negative["vertices"][index]["vertex_id"], "end_vertex_id": negative["vertices"][index + 1]["vertex_id"]} for index in range(20)]
    neg_code, neg_target = _post("/api/visual-flower/targets", {"profile": negative})
    neg_gen_code, neg_result = _post(f"/api/visual-flower/targets/{neg_target.get('target_id')}/generate", {"generation_engine": "COMPARE_ALL", "station_mode": "EXACT", "exact_station_count": 16, "candidate_limit": 3}) if neg_code == 200 else (0, {})
    learned = [item for item in (neg_result.get("candidates", []) if isinstance(neg_result, dict) else []) if str(item.get("candidate_style", "")).startswith("CLRSG")]
    checks["ood_probe"] = neg_gen_code == 200 and bool(learned) and all((item.get("learned_support") or {}).get("ood_status") == "OUT_OF_DISTRIBUTION" and item.get("status") == "LEARNED_SEQUENCE_FALLBACK" for item in learned)
    return {"status": "PASS" if all(value is True or isinstance(value, int) and value > 0 for value in checks.values()) else "WARN", "checks": checks, "ood_probe": "high-frequency public contour", "private_paths_redacted": True, "production_approval": "NOT_APPROVED"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline visual flower demo")
    parser.add_argument("command", choices=("doctor", "start", "stop", "status", "verify"))
    args = parser.parse_args()
    try:
        result = {"doctor": doctor, "start": start, "stop": stop, "status": status, "verify": verify}[args.command]()
    except Exception as exc:
        result = {"status": "FAIL", "error_code": type(exc).__name__, "message": str(exc), "private_paths_redacted": True}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
