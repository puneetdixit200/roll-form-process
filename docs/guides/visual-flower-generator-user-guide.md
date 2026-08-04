# Visual Flower Generator user guide

1. Open the offline web application and navigate to **Visual Flower Generator**.
2. Click **Load Example** or draw with the SVG line/polyline tools. Vertices are
   world coordinates, not pixels. Use Undo/Redo before generating.
3. Choose Exact, Automatic, or Range station mode. Exact counts must be 8–28.
4. Click **Generate Flower Sequence**. The backend canonicalizes the profile,
   compares it with the configured local historical dataset, and returns up to
   three candidates.
5. Select a candidate tab, drag the station slider, and inspect the best
   historical flower/pass, visual similarity, evidence coverage, warnings and
   visual-confidence band.
6. Export JSON/CSV/SVG/DXF/HTML/ZIP from the local CLI or candidate export UI.

The score describes visual evidence only. It does not show that a physical
roller exists, that tooling is compatible, or that a sequence is safe to use.
