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
from rollform_extractor.strip_length_constraint import (
    STRIP_LENGTH_RELATIVE_TOLERANCE,
    STRIP_LENGTH_CONSTRAINT_VERSION,
    centerline_length,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("ROLLFORM_DEMO_RUNTIME", "/tmp/rollform-visual-flower-demo"))
PID_FILE = RUNTIME / "pids.json"
LOG_DIR = RUNTIME / "logs"
CONFIG_KEYS = {
    "dataset": "ROLLFORM_FLOWER_PROTOTYPE_DATASET",
    "model": "ROLLFORM_ACTIVE_CLRSG_MODEL",
    "registry": "ROLLFORM_MODEL_REGISTRY_ROOT",
}


def _config_path() -> Path:
    configured = os.environ.get("ROLLFORM_DEMO_CONFIG")
    if configured:
        return Path(configured).expanduser()
    config_root = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    ).expanduser()
    return config_root / "rollform-extractor" / "visual-flower-demo.json"


def _saved_configuration() -> dict[str, str]:
    try:
        payload = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for label, environment_name in CONFIG_KEYS.items():
        value = payload.get(label)
        if isinstance(value, str) and Path(value).expanduser().exists():
            result[environment_name] = str(Path(value).expanduser().resolve())
    return result


def _runtime_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name, value in _saved_configuration().items():
        env.setdefault(name, value)
    return env


def _configured(name: str) -> str | None:
    value = _runtime_environment().get(name)
    return value if value and Path(value).expanduser().exists() else None


def configure(
    dataset: str | None,
    model: str | None,
    registry: str | None,
) -> dict[str, object]:
    if not dataset:
        raise ValueError("--dataset is required")
    resolved = {
        "dataset": Path(dataset).expanduser().resolve(),
        "model": Path(model).expanduser().resolve() if model else None,
        "registry": Path(registry).expanduser().resolve() if registry else None,
    }
    if not resolved["dataset"].is_file() or resolved["dataset"].name != "dataset.json":
        raise ValueError("dataset must point to an existing dataset.json")
    for label in ("model", "registry"):
        path = resolved[label]
        if path is not None and not path.is_dir():
            raise ValueError(f"{label} must point to an existing directory")
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        label: str(path)
        for label, path in resolved.items()
        if path is not None
    }
    config_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return {
        "status": "PASS",
        "configuration_saved": True,
        "dataset_configured": True,
        "model_configured": resolved["model"] is not None,
        "registry_configured": resolved["registry"] is not None,
        "private_paths_redacted": True,
    }


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
        with urllib.request.urlopen(
            f"http://127.0.0.1:8000{path}", timeout=5
        ) as response:
            body = response.read()
            try:
                return response.status, json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return response.status, body.decode("utf-8", "replace")
    except (OSError, urllib.error.URLError) as exc:
        return 0, {"error": type(exc).__name__}


def _post(path: str, payload: object) -> tuple[int, object]:
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
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
    checks["private_dataset_configured"] = (
        dataset is not None and Path(dataset).name == "dataset.json"
    )
    checks["active_model_configured"] = model_root is not None
    checks["backend_port_available"] = (
        _port_available(8000) or _get("/api/health")[0] == 200
    )
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
        checks["artifact_hashes"] = model.get("checks", {}).get(
            "artifact_verified", False
        )
    else:
        checks["model_ready"] = False
        checks["artifact_hashes"] = False
    status_value = (
        "PASS"
        if all(checks.values())
        else "WARN"
        if checks.get("editable_package_import") and checks.get("runtime_writable")
        else "FAIL"
    )
    return {
        "status": status_value,
        "checks": checks,
        "model": model,
        "private_paths_redacted": True,
        "production_approval": "NOT_APPROVED",
    }


def _owned_process(pid: int, marker: str) -> bool:
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().decode(
            "utf-8", "replace"
        )
    except OSError:
        return False
    return marker in command


def _read_pids() -> dict[str, int]:
    try:
        return {
            key: int(value)
            for key, value in json.loads(PID_FILE.read_text()).items()
        }
    except (OSError, ValueError, TypeError):
        return {}


def start() -> dict:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    existing = _read_pids()
    if existing and all(
        _owned_process(pid, "uvicorn") or _owned_process(pid, "vite")
        for pid in existing.values()
    ):
        return status()
    env = _runtime_environment()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    backend_log = (LOG_DIR / "backend.log").open("ab")
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=ROOT,
        env=env,
        stdout=backend_log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if _get("/api/health")[0] == 200:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("backend health check timed out")
        frontend_log = (LOG_DIR / "frontend.log").open("ab")
        frontend = subprocess.Popen(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
            ],
            cwd=ROOT / "frontend",
            env=env,
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:5173/", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("frontend HTTP check timed out")
        PID_FILE.write_text(
            json.dumps(
                {"backend": backend.pid, "frontend": frontend.pid},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        model = _get("/api/visual-flower/model/status")[1]
        active = (model.get("active_models") or [{}])[0]
        return {
            "status": "PASS",
            "frontend_url": "http://127.0.0.1:5173/",
            "backend_url": "http://127.0.0.1:8000/",
            "active_model": active.get("model_id", "DETERMINISTIC_ONLY"),
            "private_paths_redacted": True,
        }
    except Exception:
        os.killpg(backend.pid, signal.SIGTERM)
        raise


def stop() -> dict:
    stopped = []
    for name, pid in _read_pids().items():
        owned = (
            _owned_process(pid, "uvicorn")
            if name == "backend"
            else (_owned_process(pid, "npm run dev") or _owned_process(pid, "vite"))
        )
        if owned:
            os.killpg(pid, signal.SIGTERM)
            stopped.append(name)
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
    active = (
        (model.get("active_models") or [{}])[0]
        if isinstance(model, dict)
        else {}
    )
    return {
        "status": "PASS" if health and frontend else "WARN",
        "backend_running": health,
        "frontend_running": frontend,
        "health_endpoint": health,
        "model_status_endpoint": backend_status == 200,
        "active_model": active.get("model_id", "DETERMINISTIC_ONLY"),
        "approval": model.get("production_approval", "NOT_APPROVED")
        if isinstance(model, dict)
        else "NOT_APPROVED",
        "deterministic_fallback": model.get("deterministic_fallback", True)
        if isinstance(model, dict)
        else True,
        "pid_state": pids,
        "private_paths_redacted": True,
    }


def _strip_length_checks(
    candidates: list[dict],
) -> tuple[dict[str, bool], dict[str, object]]:
    """Recompute the invariant independently of stored metadata."""
    metadata_ok = bool(candidates)
    all_passes_ok = bool(candidates)
    maximum_relative_error = 0.0
    evaluated_passes = 0

    for candidate in candidates:
        summary = candidate.get("geometry_constraints") or {}
        metadata_ok = metadata_ok and bool(summary.get("enabled")) and bool(
            summary.get("satisfied")
        )
        passes = candidate.get("passes") or []
        if not passes:
            all_passes_ok = False
            continue
        final_profile = passes[-1].get("profile") or {}
        topology = str(final_profile.get("topology") or "OPEN_PATH")
        target_points = final_profile.get("points") or []
        target_length = centerline_length(target_points, topology)
        if target_length <= 1e-12:
            all_passes_ok = False
            continue

        for item in passes:
            evaluated_passes += 1
            profile = item.get("profile") or {}
            actual_length = centerline_length(
                profile.get("points") or [], topology
            )
            relative_error = abs(actual_length - target_length) / target_length
            maximum_relative_error = max(
                maximum_relative_error, relative_error
            )
            stored = (
                item.get("generation", {}).get("strip_length_constraint") or {}
            )
            metadata_ok = (
                metadata_ok
                and bool(stored.get("enabled"))
                and bool(stored.get("satisfied"))
            )
            if relative_error > STRIP_LENGTH_RELATIVE_TOLERANCE:
                all_passes_ok = False

    checks = {
        "constant_strip_length_metadata": metadata_ok,
        "constant_strip_length_all_passes": all_passes_ok,
        "constant_strip_length_tolerance": (
            bool(candidates)
            and evaluated_passes > 0
            and maximum_relative_error <= STRIP_LENGTH_RELATIVE_TOLERANCE
        ),
    }
    summary = {
        "constraint_version": STRIP_LENGTH_CONSTRAINT_VERSION,
        "relative_tolerance": STRIP_LENGTH_RELATIVE_TOLERANCE,
        "maximum_relative_error": maximum_relative_error,
        "evaluated_passes": evaluated_passes,
        "independently_recomputed": True,
    }
    return checks, summary


def verify() -> dict:
    checks: dict[str, object] = {
        "backend_health": _get("/api/health")[0] == 200,
        "frontend_http": False,
        "model_status": False,
        "model_doctor": False,
    }
    try:
        with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=5) as response:
            checks["frontend_http"] = response.status == 200
    except OSError:
        pass

    status_code, model = _get("/api/visual-flower/model/status")
    checks["model_status"] = (
        status_code == 200
        and isinstance(model, dict)
        and bool(model.get("deterministic_fallback"))
    )
    doctor_code, doctor_result = _get("/api/visual-flower/model/doctor")
    checks["model_doctor"] = (
        doctor_code == 200
        and isinstance(doctor_result, dict)
        and doctor_result.get("private_paths_redacted") is True
    )

    fixture = ROOT / "tests" / "fixtures" / "visual_profiles" / "open_channel.json"
    profile = json.loads(fixture.read_text(encoding="utf-8"))
    created_code, created = _post("/api/visual-flower/targets", {"profile": profile})
    if created_code == 200 and isinstance(created, dict):
        generated_code, generated = _post(
            f"/api/visual-flower/targets/{created.get('target_id')}/generate",
            {
                "generation_engine": "COMPARE_ALL",
                "station_mode": "EXACT",
                "exact_station_count": 16,
                "candidate_limit": 3,
            },
        )
    else:
        generated_code, generated = 0, {}
    candidates = (
        generated.get("candidates", []) if isinstance(generated, dict) else []
    )
    checks["public_target_generation"] = generated_code == 200
    checks["candidate_count"] = len(candidates)
    checks["sixteen_station_candidate"] = any(
        item.get("station_count") == 16 for item in candidates
    )
    checks["final_target_anchoring"] = bool(candidates) and all(
        item.get("passes", [{}])[-1].get("profile", {}).get("points")
        for item in candidates
    )

    strip_checks, strip_summary = _strip_length_checks(candidates)
    checks.update(strip_checks)

    if candidates:
        candidate_id = candidates[0]["candidate_id"]
        checks["json_export"] = (
            _get(f"/api/visual-flower/candidates/{candidate_id}/export.json")[0]
            == 200
        )
        checks["zip_export"] = (
            _get(f"/api/visual-flower/candidates/{candidate_id}/export/zip")[0]
            == 200
        )
    else:
        checks["json_export"] = False
        checks["zip_export"] = False

    negative = json.loads(fixture.read_text(encoding="utf-8"))
    negative["profile_id"] = "PUBLIC-OOD-HIGH-FREQUENCY"
    negative["name"] = "Public OOD probe"
    negative["vertices"] = [
        {
            "vertex_id": f"ood-v{index}",
            "x": -3.0 + index * 0.3,
            "y": 0.45 if index % 2 else -0.45,
        }
        for index in range(21)
    ]
    negative["segments"] = [
        {
            "segment_id": f"ood-s{index}",
            "type": "LINE",
            "start_vertex_id": negative["vertices"][index]["vertex_id"],
            "end_vertex_id": negative["vertices"][index + 1]["vertex_id"],
        }
        for index in range(20)
    ]
    neg_code, neg_target = _post(
        "/api/visual-flower/targets", {"profile": negative}
    )
    if neg_code == 200 and isinstance(neg_target, dict):
        neg_gen_code, neg_result = _post(
            f"/api/visual-flower/targets/{neg_target.get('target_id')}/generate",
            {
                "generation_engine": "COMPARE_ALL",
                "station_mode": "EXACT",
                "exact_station_count": 16,
                "candidate_limit": 3,
            },
        )
    else:
        neg_gen_code, neg_result = 0, {}
    learned = [
        item
        for item in (
            neg_result.get("candidates", [])
            if isinstance(neg_result, dict)
            else []
        )
        if str(item.get("candidate_style", "")).startswith("CLRSG")
    ]
    checks["ood_probe"] = (
        neg_gen_code == 200
        and bool(learned)
        and all(
            (item.get("learned_support") or {}).get("ood_status")
            == "OUT_OF_DISTRIBUTION"
            and item.get("status") == "LEARNED_SEQUENCE_FALLBACK"
            for item in learned
        )
    )

    passed = all(
        value is True or (isinstance(value, int) and not isinstance(value, bool) and value > 0)
        for value in checks.values()
    )
    return {
        "status": "PASS" if passed else "WARN",
        "checks": checks,
        "strip_length": strip_summary,
        "ood_probe": "high-frequency public contour",
        "private_paths_redacted": True,
        "production_approval": "NOT_APPROVED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline visual flower demo")
    parser.add_argument(
        "command",
        choices=("configure", "doctor", "start", "stop", "status", "verify"),
    )
    parser.add_argument("--dataset")
    parser.add_argument("--model")
    parser.add_argument("--registry")
    args = parser.parse_args()
    try:
        result = {
            "configure": lambda: configure(
                args.dataset, args.model, args.registry
            ),
            "doctor": doctor,
            "start": start,
            "stop": stop,
            "status": status,
            "verify": verify,
        }[args.command]()
    except Exception as exc:
        result = {
            "status": "FAIL",
            "error_code": type(exc).__name__,
            "message": str(exc),
            "private_paths_redacted": True,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
