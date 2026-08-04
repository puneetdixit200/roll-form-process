"""Public procedural visual-profile families for CI and model infrastructure."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any

from rollform_extractor.visual_profile_schema import VisualProfile, validate_profile


PUBLIC_FAMILIES = (
    "OPEN_U_CHANNEL", "OPEN_C_CHANNEL", "OPEN_Z_PROFILE", "OPEN_HAT_PROFILE",
    "OPEN_STEP_PROFILE", "OPEN_ASYMMETRIC_CHANNEL", "OPEN_CURVED_WAVE",
    "OPEN_MIXED_LINE_ARC", "CLOSED_ROUNDED_RECTANGLE", "CLOSED_ASYMMETRIC_LOOP",
)


def _profile(profile_id: str, points: list[tuple[float, float]], *, closed: bool = False, name: str = "Public synthetic profile") -> dict[str, Any]:
    vertices = [{"vertex_id": f"v{i:03d}", "x": round(x, 8), "y": round(y, 8)} for i, (x, y) in enumerate(points)]
    segments = [{"segment_id": f"s{i:03d}", "type": "LINE", "start_vertex_id": f"v{i:03d}", "end_vertex_id": f"v{(i + 1) % len(points) if closed else i + 1:03d}"} for i in range(len(points) if closed else len(points) - 1)]
    payload = {"schema_version": 1, "profile_id": profile_id, "name": name, "coordinate_system": {"x_axis": "right", "y_axis": "up", "units": "VISUAL_UNIT"}, "topology": "CLOSED_CONTOUR" if closed else "OPEN_PATH", "closed": closed, "computational_seam_vertex_id": "v000" if closed else None, "vertices": vertices, "segments": segments, "metadata": {"source": "PUBLIC_PROCEDURAL_SYNTHETIC", "visual_only": True}}
    return validate_profile(payload).to_dict()


def make_family(family_id: str, index: int = 0) -> dict[str, Any]:
    if family_id not in PUBLIC_FAMILIES:
        raise ValueError(f"unknown public family: {family_id}")
    q = (index % 7) / 6.0
    if family_id == "OPEN_U_CHANNEL":
        points = [(-1.2, 0), (-1.0, 0.55 + .1*q), (0, 0.75), (1.0, 0.55), (1.2, 0)]
    elif family_id == "OPEN_C_CHANNEL":
        points = [(-1.1, .6), (-.75, .9), (.9, .9), (.65, .55), (-.35, .55), (-.65, 0), (.65, 0), (.9, -.35), (-.75, -.35)]
    elif family_id == "OPEN_Z_PROFILE":
        points = [(-1.1, .65), (0, .65), (.7, 0), (0, -.65), (1.1, -.65)]
    elif family_id == "OPEN_HAT_PROFILE":
        points = [(-1.2, 0), (-.9, .65), (-.35, .65), (0, .15), (.35, .65), (.9, .65), (1.2, 0)]
    elif family_id == "OPEN_STEP_PROFILE":
        points = [(-1.2, 0), (-.6, 0), (-.6, .55), (.25, .55), (.25, .1), (1.2, .1)]
    elif family_id == "OPEN_ASYMMETRIC_CHANNEL":
        points = [(-1.2, 0), (-.9, .8), (0, .8), (.4, .25), (1.1, .55)]
    elif family_id == "OPEN_CURVED_WAVE":
        points = [(x, .45 * math.sin(x * 2.2 + q)) for x in (-1.2, -.9, -.6, -.3, 0, .3, .6, .9, 1.2)]
    elif family_id == "OPEN_MIXED_LINE_ARC":
        points = [(-1.2, 0), (-.7, .6), (0, .75), (.7, .6), (1.2, 0)]
    elif family_id == "CLOSED_ROUNDED_RECTANGLE":
        points = [(-.95, -.55), (.95, -.55), (.95, .55), (-.95, .55)]
        return _profile(f"public-{family_id.lower()}-{index:03d}", points, closed=True, name=family_id)
    else:
        points = [(-1.0, -.55), (.2, -.55), (1.0, 0), (.2, .55), (-.8, .55)]
        return _profile(f"public-{family_id.lower()}-{index:03d}", points, closed=True, name=family_id)
    return _profile(f"public-{family_id.lower()}-{index:03d}", points, name=family_id)


def family_recipe_hash(family_id: str) -> str:
    return sha256(json.dumps({"family": family_id, "version": "public_families_v1"}, sort_keys=True).encode()).hexdigest()


def public_family_catalog() -> list[dict[str, Any]]:
    return [{"family_id": family, "recipe_hash": family_recipe_hash(family), "classification": "PUBLIC_PROCEDURAL_SYNTHETIC"} for family in PUBLIC_FAMILIES]
