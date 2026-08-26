"""Offline DWG/DXF import adapter for the visual flower workflow.

This module deliberately reuses the repository converter and ezdxf reader. It
stores only redacted import metadata and derived profile JSON in the web
workspace; source CAD remains in the private staging directory.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from rollform_extractor.converter import ConversionUnavailableError, stage_input
from rollform_extractor.dxf_reader import inspect_drawing
from rollform_extractor.visual_cad_profile_detection import detect_profiles, thumbnail_svg
from rollform_extractor.visual_cad_preview import build_drawing_preview


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _state_path(root: Path, import_id: str) -> Path:
    return root / "visual_imports" / import_id / "import.json"


def _preview_path(root: Path, import_id: str) -> Path:
    return root / "visual_imports" / import_id / "preview.json"


def _profile_candidates(dxf_path: Path) -> list[dict[str, Any]]:
    return detect_profiles(dxf_path)


def create_import(root: Path, filename: str, data: bytes) -> dict[str, Any]:
    safe_name = Path(filename or "profile.dxf").name
    if Path(safe_name).suffix.lower() not in {".dxf", ".dwg"}:
        raise ValueError("only .dxf and .dwg files are supported")
    import_id = "vimport-" + uuid4().hex[:16]
    directory = root / "visual_imports" / import_id
    source = directory / safe_name
    directory.mkdir(parents=True, exist_ok=False)
    source.write_bytes(data)
    try:
        staged = stage_input(source, directory / "staged")
        inspection = inspect_drawing(staged.converted_file).to_dict()
        profiles = _profile_candidates(staged.converted_file)
        preview = build_drawing_preview(staged.converted_file, import_id, _hash(data))
        _preview_path(root, import_id).write_text(json.dumps(preview, sort_keys=True), encoding="utf-8")
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "converter": staged.converter, "inspection": {"units": inspection.get("units"), "modelspace_entity_count": inspection.get("modelspace_entity_count"), "layers": sorted(inspection.get("layers", {})), "private_paths_redacted": True}, "status": "PROFILES_READY" if profiles else "NO_PROFILES", "profiles": profiles, "preview_version": preview["preview_version"], "source_not_exported": True}
    except ConversionUnavailableError as exc:
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "status": "FAILED", "profiles": [], "error_code": "CONVERSION_UNAVAILABLE", "error": str(exc), "private_paths_redacted": True, "source_not_exported": True}
    except Exception:
        state = {"import_id": import_id, "original_filename": safe_name, "source_sha256": _hash(data), "status": "FAILED", "profiles": [], "error_code": "CAD_IMPORT_FAILED", "error": "offline CAD import failed; inspect server diagnostics without exposing source paths", "private_paths_redacted": True, "source_not_exported": True}
    _state_path(root, import_id).write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return summary(state)


def summary(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "profiles"} | {"profile_count": len(state.get("profiles", []))}


def get_import(root: Path, import_id: str) -> dict[str, Any] | None:
    path = _state_path(root, import_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_profiles(root: Path, import_id: str) -> list[dict[str, Any]] | None:
    state = get_import(root, import_id)
    return None if state is None else [{key: value for key, value in item.items() if key != "profile"} for item in state.get("profiles", [])]


def selected_profile(root: Path, import_id: str, profile_id: str) -> dict[str, Any] | None:
    state = get_import(root, import_id)
    if state is None:
        return None
    for item in state.get("profiles", []):
        if item.get("profile_id") == profile_id:
            return item["profile"]
    return None


def get_preview(root: Path, import_id: str) -> dict[str, Any] | None:
    path = _preview_path(root, import_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
