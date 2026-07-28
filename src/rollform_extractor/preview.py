from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw

from rollform_extractor.models import BBox, CadEntityRecord, CadPrimitive


def render_drawing_preview(
    entities: Iterable[CadEntityRecord], path: Path, overlays=()
) -> Path:
    records = tuple(entities)
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

    image = image.resize((width, height), Image.Resampling.LANCZOS)
    image.save(path)
    return path


def _draw_primitive(draw, primitive: CadPrimitive, sampled, bounds: BBox, scale: float, height: int, color, antialias: int) -> None:
    attrs = primitive.attributes
    if primitive.kind == "LINE":
        draw.line((_pixel(attrs["start"], bounds, scale, height, antialias), _pixel(attrs["end"], bounds, scale, height, antialias)), fill=color, width=2 * antialias)
    elif primitive.kind in {"LWPOLYLINE", "POLYLINE"}:
        points = tuple(vertex["point"] for vertex in attrs.get("vertices", ())) or tuple(attrs.get("points", ()))
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
