from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from ezdxf import bbox

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.geometry_normalizer import compose_insert_matrix, normalize_primitives
from rollform_extractor.models import (
    BBox,
    CadEntityRecord,
    CadPrimitive,
    ParseResult,
    TransformRecord,
    WarningRecord,
)


SUPPORTED_TYPES = {
    "LINE",
    "LWPOLYLINE",
    "POLYLINE",
    "ARC",
    "CIRCLE",
    "ELLIPSE",
    "SPLINE",
    "INSERT",
    "TEXT",
    "MTEXT",
    "DIMENSION",
    "HATCH",
    "POINT",
}


def parse_entities(doc, config: ExtractionConfig) -> ParseResult:
    config_hash = config.hash_for("parsing")
    warnings: list[WarningRecord] = []
    entities = [
        _record_entity(
            entity,
            layout.name,
            _top_level_matrix(entity),
            (),
            config,
            config_hash,
            warnings,
        )
        for layout in doc.layouts
        for entity in layout
    ]
    expanded: list[CadEntityRecord] = []
    for layout in doc.layouts:
        for entity in layout:
            if entity.dxftype() == "INSERT":
                expanded.extend(
                    _expand_insert(entity, doc, layout.name, np.identity(4), (), (), config, config_hash, warnings)
                )
    return ParseResult(
        entities=tuple(entities),
        expanded_entities=tuple(expanded),
        warnings=tuple(warnings),
        method="entity_parser",
        configuration_hash=config_hash,
    )


def _expand_insert(
    insert,
    doc,
    layout: str,
    parent_matrix: np.ndarray,
    block_path: tuple[str, ...],
    insert_path: tuple[str, ...],
    config: ExtractionConfig,
    config_hash: str,
    warnings: list[WarningRecord],
) -> tuple[CadEntityRecord, ...]:
    matrix = compose_insert_matrix(insert, parent_matrix)
    name = str(insert.dxf.name)
    path = (*block_path, name)
    occurrence_path = (*insert_path, f"{name}:{insert.dxf.handle}")
    try:
        block = doc.blocks[name]
    except Exception as exc:
        warnings.append(_warning("missing_block", str(exc), (insert.dxf.handle,), config_hash))
        return ()
    records: list[CadEntityRecord] = []
    for entity in block:
        if entity.dxftype() == "INSERT":
            records.extend(_expand_insert(entity, doc, layout, matrix, path, occurrence_path, config, config_hash, warnings))
        else:
            records.append(_record_entity(entity, layout, matrix, path, config, config_hash, warnings, occurrence_path))
    return tuple(records)


def _record_entity(
    entity,
    layout: str,
    matrix: np.ndarray,
    block_path: tuple[str, ...],
    config: ExtractionConfig,
    config_hash: str,
    warnings: list[WarningRecord],
    occurrence_path: tuple[str, ...] = (),
) -> CadEntityRecord:
    handle = str(entity.dxf.handle)
    ledger_handle = f"{handle}@{'/'.join(occurrence_path)}" if occurrence_path else handle
    entity_type = entity.dxftype()
    attrs = _dxf_attributes(entity)
    primitive = None
    if entity_type in SUPPORTED_TYPES:
        try:
            primitive = _primitive(entity)
        except Exception as exc:
            warnings.append(_warning("primitive_parse_failed", str(exc), (handle,), config_hash))
    else:
        warnings.append(_warning("unsupported_entity", entity_type, (handle,), config_hash))
    normalized = None
    if primitive is not None:
        try:
            normalized = normalize_primitives(
                (primitive,),
                matrix,
                _unit_factor(entity.doc.header.get("$INSUNITS", 0)),
                config.geometry.curve_sampling_spacing_mm,
                config.geometry.endpoint_join_tolerance_mm,
            )
        except Exception as exc:
            warnings.append(_warning("normalization_failed", str(exc), (handle,), config_hash))
    transform = TransformRecord(
        matrix_4x4=_matrix_tuple(matrix),
        block_path=block_path,
        parent_block=block_path[-2] if len(block_path) > 1 else (block_path[-1] if block_path else None),
        mirrored=bool(np.linalg.det(np.asarray(matrix)[:3, :3]) < 0),
    )
    return CadEntityRecord(
        handle=ledger_handle,
        entity_type=entity_type,
        layer=str(getattr(entity.dxf, "layer", "0")),
        color=getattr(entity.dxf, "color", None),
        line_type=getattr(entity.dxf, "linetype", None),
        layout=layout,
        bbox=_bbox(entity, config_hash, warnings),
        original_primitives=(primitive,) if primitive is not None else (),
        normalized_primitives=normalized.primitives if normalized is not None else (),
        sampled_geometry=normalized.sampled_points if normalized is not None else (),
        source_handles=(handle,),
        method="entity_parser",
        configuration_hash=config_hash,
        confidence=1.0 if primitive is not None else 0.0,
        attributes=attrs,
        transform=transform,
    )


def _primitive(entity) -> CadPrimitive:
    kind = entity.dxftype()
    attrs: dict[str, Any]
    if kind == "LINE":
        attrs = {"start": _point(entity.dxf.start), "end": _point(entity.dxf.end)}
    elif kind == "LWPOLYLINE":
        vertices = tuple(
            {
                "point": (float(x), float(y), 0.0),
                "bulge": float(bulge),
                "start_width": float(start_width),
                "end_width": float(end_width),
            }
            for x, y, bulge, start_width, end_width in entity.get_points("xybse")
        )
        attrs = {
            "vertices": vertices,
            "points": tuple(vertex["point"] for vertex in vertices),
            "closed": bool(entity.closed),
        }
    elif kind == "POLYLINE":
        vertices = tuple(
            {
                "point": _point(vertex.dxf.location),
                "bulge": float(getattr(vertex.dxf, "bulge", 0.0) or 0.0),
                "start_width": float(getattr(vertex.dxf, "start_width", 0.0) or 0.0),
                "end_width": float(getattr(vertex.dxf, "end_width", 0.0) or 0.0),
            }
            for vertex in entity.vertices
        )
        attrs = {
            "vertices": vertices,
            "points": tuple(vertex["point"] for vertex in vertices),
            "closed": bool(getattr(entity, "is_closed", False)),
        }
    elif kind == "ARC":
        attrs = {
            "center": _point(entity.dxf.center),
            "radius": float(entity.dxf.radius),
            "start_angle": float(entity.dxf.start_angle),
            "end_angle": float(entity.dxf.end_angle),
        }
    elif kind == "CIRCLE":
        attrs = {"center": _point(entity.dxf.center), "radius": float(entity.dxf.radius)}
    elif kind == "ELLIPSE":
        attrs = {
            "center": _point(entity.dxf.center),
            "major_axis": _point(entity.dxf.major_axis),
            "ratio": float(entity.dxf.ratio),
            "start_param": float(entity.dxf.start_param),
            "end_param": float(entity.dxf.end_param),
        }
    elif kind == "SPLINE":
        attrs = {
            "control_points": tuple(_point(point) for point in getattr(entity, "control_points", ())),
            "fit_points": tuple(_point(point) for point in getattr(entity, "fit_points", ())),
            "knots": tuple(float(value) for value in getattr(entity, "knots", ())),
            "weights": tuple(float(value) for value in getattr(entity, "weights", ())),
            "degree": int(getattr(entity.dxf, "degree", 0) or 0),
        }
    elif kind == "INSERT":
        attrs = {"name": str(entity.dxf.name), "insert": _point(entity.dxf.insert)}
    elif kind == "TEXT":
        attrs = {
            "text": entity.dxf.text,
            "insert": _point(entity.dxf.insert),
            "height": float(getattr(entity.dxf, "height", 0.0) or 0.0),
            "rotation": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
        }
    elif kind == "MTEXT":
        attrs = {
            "text": entity.text,
            "insert": _point(entity.dxf.insert),
            "height": float(getattr(entity.dxf, "char_height", 0.0) or 0.0),
            "rotation": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
        }
    elif kind == "DIMENSION":
        attrs = _dxf_attributes(entity)
        attrs.update(
            {
                "dimtype": int(entity.dimtype),
                "text": str(getattr(entity.dxf, "text", "")),
                "measurement": float(entity.get_measurement()),
            }
        )
    elif kind == "HATCH":
        attrs = {
            "path_count": len(entity.paths),
            "solid_fill": bool(entity.dxf.solid_fill),
            "paths": tuple(_hatch_path(path) for path in entity.paths),
        }
    elif kind == "POINT":
        attrs = {"point": _point(entity.dxf.location)}
    else:
        raise ValueError(f"unsupported entity type: {kind}")
    return CadPrimitive(kind=kind, attributes=attrs, source_handle=str(entity.dxf.handle))


def _dxf_attributes(entity) -> dict[str, Any]:
    return {
        key: _json_safe(value)
        for key, value in entity.dxf.all_existing_dxf_attribs().items()
    }


def _bbox(entity, config_hash: str, warnings: list[WarningRecord]) -> BBox | None:
    try:
        return _bbox_from_entity(entity)
    except Exception as exc:
        warnings.append(_warning("bbox_failed", str(exc), (str(entity.dxf.handle),), config_hash))
        return None


def _bbox_from_entity(entity) -> BBox | None:
    box = bbox.extents([entity])
    if not box.has_data:
        return None
    return BBox(float(box.extmin[0]), float(box.extmin[1]), float(box.extmax[0]), float(box.extmax[1]))


def _warning(code: str, message: str, handles: Iterable[str], config_hash: str) -> WarningRecord:
    return WarningRecord(
        code=code,
        message=message,
        source_handles=tuple(handles),
        method="entity_parser",
        configuration_hash=config_hash,
        confidence=0.0,
    )


def _matrix_tuple(matrix: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in np.asarray(matrix, dtype=float))


def _top_level_matrix(entity) -> np.ndarray:
    if entity.dxftype() == "INSERT":
        return compose_insert_matrix(entity, np.identity(4))
    return np.identity(4)


def _hatch_path(path) -> dict[str, Any]:
    if hasattr(path, "edges"):
        return {
            "kind": "EDGE",
            "edges": tuple(_hatch_edge(edge) for edge in path.edges),
        }
    return {
        "kind": "POLYLINE",
        "vertices": tuple(_point(vertex[:2]) for vertex in getattr(path, "vertices", ())),
        "closed": bool(getattr(path, "is_closed", False)),
    }


def _hatch_edge(edge) -> dict[str, Any]:
    name = type(edge).__name__.replace("Edge", "").upper()
    data = {"kind": name}
    for key in ("start", "end", "center"):
        if hasattr(edge, key):
            data[key] = _point(getattr(edge, key))
    for key in ("radius", "start_angle", "end_angle", "ccw"):
        if hasattr(edge, key):
            data[key] = _json_safe(getattr(edge, key))
    return data


def _point(value) -> tuple[float, float, float]:
    if hasattr(value, "xyz"):
        value = value.xyz
    values = tuple(value)
    if len(values) == 2:
        return (float(values[0]), float(values[1]), 0.0)
    return (float(values[0]), float(values[1]), float(values[2]))


def _json_safe(value: Any) -> Any:
    if hasattr(value, "xyz"):
        return tuple(value.xyz)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_json_safe(item) for item in value)
    return str(value)


def _unit_factor(insunits: int) -> float:
    return {
        0: 1.0,
        1: 25.4,
        2: 304.8,
        4: 1.0,
        5: 10.0,
        6: 1000.0,
    }.get(int(insunits or 0), 1.0)
