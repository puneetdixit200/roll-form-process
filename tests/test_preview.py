from __future__ import annotations

import ezdxf
import numpy as np
from PIL import Image

from rollform_extractor.config import ExtractionConfig
from rollform_extractor.entity_parser import parse_entities
from rollform_extractor.preview import render_drawing_preview


def test_full_drawing_preview_contains_non_background_pixels(tmp_path):
    doc = ezdxf.new("R2013", setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (20, 0))
    msp.add_arc((10, 5), 5, 180, 360)
    msp.add_circle((10, 14), 3)

    parsed = parse_entities(doc, ExtractionConfig.load())

    image_path = render_drawing_preview(parsed.entities, tmp_path / "drawing.png")
    image = np.asarray(Image.open(image_path).convert("RGB"))

    assert image_path == tmp_path / "drawing.png"
    assert image.shape[0] <= 1200
    assert image.shape[1] <= 1200
    assert np.unique(image.reshape(-1, 3), axis=0).shape[0] > 4


def test_preview_extents_use_actual_content_not_far_title_block(tmp_path):
    doc = ezdxf.new("R2013", setup=True)
    msp = doc.modelspace()
    msp.add_circle((0, 0), 5)
    msp.add_text("DRAWING NO 123").set_placement((100_000, 100_000))

    parsed = parse_entities(doc, ExtractionConfig.load())

    image_path = render_drawing_preview(parsed.entities, tmp_path / "bounded.png")
    image = np.asarray(Image.open(image_path).convert("RGB"))

    assert image.shape[0] >= 128
    assert image.shape[1] >= 128
    assert np.count_nonzero(np.any(image != image[0, 0], axis=2)) > 40
