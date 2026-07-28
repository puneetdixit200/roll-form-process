from __future__ import annotations

from pathlib import Path

import ezdxf


def write_sample_dxf(path: Path) -> Path:
    doc = ezdxf.new("R2013", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.layers.add("PROFILE", color=3, linetype="CONTINUOUS")
    doc.layers.add("EMPTY", color=1, linetype="CONTINUOUS")
    block = doc.blocks.new("ROLLER")
    block.add_circle((0, 0), radius=2, dxfattribs={"layer": "PROFILE"})
    modelspace = doc.modelspace()
    modelspace.add_line((1, 2), (5, 2), dxfattribs={"layer": "PROFILE"})
    modelspace.add_text("ST01", dxfattribs={"layer": "PROFILE"}).set_placement((1, 3))
    modelspace.add_blockref("ROLLER", (10, 20), dxfattribs={"layer": "PROFILE"})
    layout = doc.layouts.new("CHECKS")
    layout.add_text("paper", dxfattribs={"layer": "PROFILE"}).set_placement((0, 0))
    doc.saveas(path)
    return path


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
