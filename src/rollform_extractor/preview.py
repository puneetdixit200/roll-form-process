from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive


def render_drawing_preview(
    entities: Iterable[CadEntityRecord], path: Path, overlays=()
) -> Path:
    return _render_preview(tuple(entities), path, overlays, show_handles=False)


def render_manual_review_preview(
    entities: Iterable[CadEntityRecord], path: Path, overlays=()
) -> Path:
    return _render_preview(tuple(entities), path, overlays, show_handles=True)


def render_stage_review_preview(
    entities: Iterable[CadEntityRecord],
    path: Path,
    stage_bbox: BBox,
    title: str,
    profile_handles: Iterable[str] = (),
    upper_handles: Iterable[str] = (),
    lower_handles: Iterable[str] = (),
    side_handles: Iterable[str] = (),
) -> Path:
    records = tuple(entity for entity in entities if entity.bbox and _intersects(stage_bbox, entity.bbox))
    points = _all_points(records) + [
        (stage_bbox.min_x, stage_bbox.min_y, 0.0),
        (stage_bbox.max_x, stage_bbox.max_y, 0.0),
    ]
    bounds = _bounds(points)
    width, height, scale = _canvas(bounds)
    antialias = 3
    image = Image.new("RGB", (width * antialias, height * antialias), "white")
    draw = ImageDraw.Draw(image)
    profile = set(profile_handles)
    upper = set(upper_handles)
    lower = set(lower_handles)
    side = set(side_handles)
    for entity in records:
        handles = set(entity.source_handles or (entity.handle,))
        color = (35, 35, 35)
        if handles & profile:
            color = (20, 150, 70)
        elif handles & upper:
            color = (40, 105, 220)
        elif handles & lower:
            color = (220, 105, 35)
        elif handles & side:
            color = (150, 70, 190)
        for primitive in entity.normalized_primitives or entity.original_primitives:
            _draw_primitive(draw, primitive, entity.sampled_geometry, bounds, scale * antialias, height * antialias, color, antialias)
        if not entity.normalized_primitives and not entity.original_primitives:
            _draw_points(draw, entity.sampled_geometry, bounds, scale * antialias, height * antialias, color, antialias)
        x, y = _pixel((entity.bbox.min_x, entity.bbox.max_y, 0.0), bounds, scale * antialias, height * antialias, antialias)
        draw.text((x + 2 * antialias, y - 8 * antialias), ",".join(entity.source_handles or (entity.handle,)), fill=(180, 0, 0), font=ImageFont.load_default())
    _draw_bbox(draw, stage_bbox, bounds, scale * antialias, height * antialias, (210, 40, 40), antialias)
    draw.text((12 * antialias, 10 * antialias), title, fill=(0, 0, 0), font=ImageFont.load_default())
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    image.save(path)
    return path


def _render_preview(
    records: tuple[CadEntityRecord, ...], path: Path, overlays=(), show_handles: bool = False
) -> Path:
    points = _content_points(records) or _all_points(records)
    if not points:
        image = Image.new("RGB", (256, 256), "white")
        image.save(path)
        return path

    bounds = _bounds(points)
    width, height, scale = _canvas(bounds)
    antialias = 3
    image = Image.new("RGB", (width * antialias, height * antialias), "white")
    draw = ImageDraw.Draw(image)

    for entity in records:
        color = _color(entity)
        for primitive in entity.normalized_primitives or entity.original_primitives:
            _draw_primitive(draw, primitive, entity.sampled_geometry, bounds, scale * antialias, height * antialias, color, antialias)
        if not entity.normalized_primitives and not entity.original_primitives:
            _draw_points(draw, entity.sampled_geometry, bounds, scale * antialias, height * antialias, color, antialias)
    for overlay in overlays:
        _draw_points(draw, tuple(overlay), bounds, scale * antialias, height * antialias, (214, 80, 48), antialias)
    if show_handles:
        font = ImageFont.load_default()
        for entity in records:
            if entity.bbox is None or entity.entity_type in {"TEXT", "MTEXT"}:
                continue
            x, y = _pixel((entity.bbox.min_x, entity.bbox.max_y, 0.0), bounds, scale * antialias, height * antialias, antialias)
            handle = ",".join(entity.source_handles or (entity.handle,))
            draw.text((x + 2 * antialias, y - 8 * antialias), handle, fill=(180, 0, 0), font=font)

    image = image.resize((width, height), Image.Resampling.LANCZOS)
    image.save(path)
    return path


def _draw_primitive(draw, primitive: CadPrimitive, sampled, bounds: BBox, scale: float, height: int, color, antialias: int) -> None:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        draw.line((_pixel(attrs["start"], bounds, scale, height, antialias), _pixel(attrs["end"], bounds, scale, height, antialias)), fill=color, width=2 * antialias)
    elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = _polyline_points(primitive, sampled)
        if len(points) > 1:
            draw.line([_pixel(point, bounds, scale, height, antialias) for point in points], fill=color, width=2 * antialias)
            if attrs.get("closed"):
                draw.line((_pixel(points[-1], bounds, scale, height, antialias), _pixel(points[0], bounds, scale, height, antialias)), fill=color, width=2 * antialias)
    elif primitive.kind == "CIRCLE":
        x, y = _pixel(attrs["center"], bounds, scale, height, antialias)
        r = max(1, int(float(attrs["radius"]) * scale))
        draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=2 * antialias)
    else:
        _draw_points(draw, sampled, bounds, scale, height, color, antialias)


def _draw_points(draw, points, bounds: BBox, scale: float, height: int, color, antialias: int) -> None:
    pixels = [_pixel(point, bounds, scale, height, antialias) for point in points]
    if len(pixels) > 1:
        draw.line(pixels, fill=color, width=2 * antialias)
    elif pixels:
        x, y = pixels[0]
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)


def _draw_bbox(draw, bbox: BBox, bounds: BBox, scale: float, height: int, color, antialias: int) -> None:
    left, top = _pixel((bbox.min_x, bbox.max_y, 0.0), bounds, scale, height, antialias)
    right, bottom = _pixel((bbox.max_x, bbox.min_y, 0.0), bounds, scale, height, antialias)
    draw.rectangle((left, top, right, bottom), outline=color, width=2 * antialias)


def _pixel(point, bounds: BBox, scale: float, height: int, antialias: int) -> tuple[int, int]:
    margin = 24 * antialias
    return (
        int(round((float(point[0]) - bounds.min_x) * scale + margin)),
        int(round(height - ((float(point[1]) - bounds.min_y) * scale + margin))),
    )


def _canvas(bounds: BBox) -> tuple[int, int, float]:
    margin = 48
    span_x = max(bounds.max_x - bounds.min_x, 1.0)
    span_y = max(bounds.max_y - bounds.min_y, 1.0)
    scale = min(1152 / span_x, 1152 / span_y)
    width = max(128, min(1200, int(round(span_x * scale + margin))))
    height = max(128, min(1200, int(round(span_y * scale + margin))))
    return width, height, scale


def _content_points(entities: tuple[CadEntityRecord, ...]) -> list[tuple[float, float, float]]:
    points = [
        point
        for entity in entities
        if _likely_drawing_geometry(entity)
        if len(entity.sampled_geometry) > 1
        for point in entity.sampled_geometry
    ]
    if points:
        return points
    points = [
        point
        for entity in entities
        if len(entity.sampled_geometry) > 1
        for point in entity.sampled_geometry
    ]
    return points


def _all_points(entities: tuple[CadEntityRecord, ...]) -> list[tuple[float, float, float]]:
    points = [point for entity in entities for point in entity.sampled_geometry]
    for entity in entities:
        if entity.bbox is not None:
            points.extend(
                (
                    (entity.bbox.min_x, entity.bbox.min_y, 0.0),
                    (entity.bbox.max_x, entity.bbox.max_y, 0.0),
                )
            )
    return points


def _bounds(points) -> BBox:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def _color(entity: CadEntityRecord) -> tuple[int, int, int]:
    if entity.entity_type in {"TEXT", "MTEXT", "DIMENSION"}:
        return (40, 96, 180)
    if "CENTER" in (entity.line_type or "").upper():
        return (160, 90, 30)
    return (20, 20, 20)


def _likely_drawing_geometry(entity: CadEntityRecord) -> bool:
    layer = entity.layer.upper()
    if entity.layout.lower() != "model":
        return False
    if entity.entity_type in {"TEXT", "MTEXT", "DIMENSION"}:
        return False
    if any(token in layer for token in ("TITLE", "BORDER", "FRAME", "REV", "LOGO", "TABLE", "NOTE", "TEXT")):
        return False
    return True


def _intersects(left: BBox, right: BBox) -> bool:
    return not (left.max_x < right.min_x or left.min_x > right.max_x or left.max_y < right.min_y or left.min_y > right.max_y)


def _polyline_points(primitive: CadPrimitive, sampled) -> tuple:
    attrs = primitive.attributes
    vertices = tuple(attrs.get("vertices", ()))
    if vertices and any(abs(float(vertex.get("bulge", 0.0) or 0.0)) > 1e-12 for vertex in vertices):
        points: list[tuple[float, float, float]] = []
        closed = bool(attrs.get("closed"))
        pairs = zip(vertices, vertices[1:] + ((vertices[0],) if closed else ()))
        for start, end in pairs:
            segment = _bulge_segment(start["point"], end["point"], float(start.get("bulge", 0.0) or 0.0))
            points.extend(segment if not points else segment[1:])
        return tuple(points)
    return tuple(vertex["point"] for vertex in vertices) or tuple(attrs.get("points", ())) or tuple(sampled)


def _bulge_segment(start, end, bulge: float) -> tuple[tuple[float, float, float], ...]:
    if abs(bulge) <= 1e-12:
        return (start, end)
    x1, y1, z1 = start
    x2, y2, _z2 = end
    chord = math.hypot(x2 - x1, y2 - y1)
    if chord <= 1e-12:
        return (start, end)
    theta = 4.0 * math.atan(bulge)
    radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0
    normal_x = -(y2 - y1) / chord
    normal_y = (x2 - x1) / chord
    offset = chord / (2.0 * math.tan(abs(theta) / 2.0))
    side = 1.0 if bulge > 0 else -1.0
    center_x = mid_x + normal_x * offset * side
    center_y = mid_y + normal_y * offset * side
    start_angle = math.atan2(y1 - center_y, x1 - center_x)
    steps = max(8, math.ceil(abs(theta) * abs(radius) / 2.0))
    return tuple(
        (
            center_x + radius * math.cos(start_angle + theta * i / steps),
            center_y + radius * math.sin(start_angle + theta * i / steps),
            z1,
        )
        for i in range(steps + 1)
    )
