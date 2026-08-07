# Visual Flower Demo User Guide

1. Start the local app with `python scripts/run_visual_flower_demo.py start`.
2. Open `http://127.0.0.1:5173/`.
3. Load the public example or draw/import a target profile.
4. Validate the profile, choose `COMPARE_ALL`, and generate 16 stages.
5. Compare deterministic, learned, and conservative candidates. Use the
   overlay and top historical matches to understand the evidence.
6. Use ZIP/JSON/DXF/SVG/PNG/CSV/HTML exports for review.
7. Submit an engineer review only for visual prototype evidence.

The learned score is visual geometry support only. It is not manufacturing,
tooling, physical-roller, or production confidence. Unsupported geometry should
remain on deterministic fallback or be marked for review.
