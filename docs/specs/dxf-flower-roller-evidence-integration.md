# DXF Flower and Station Roller Design Evidence

This additive visual-flower integration accepts connected DXF profile geometry
and attaches deterministic, station-level **roller design evidence** to each
generated flower candidate.

## Flow

```text
DXF LINE / ARC / POLYLINE entities
→ connected-component profile detector
→ selected VisualProfile target
→ existing constant-strip-length flower generation
→ existing historical pass matching
→ historical station roller evidence aggregation
→ design-only evidence bundle and export
```

`visual_cad_profile_detection.py` groups source geometry by scale-aware endpoint
connectivity. It preserves handles, layers, units, topology, warnings, and true
DXF ARC parameters. A branching graph remains visible but is labelled
`BRANCHED_PROFILE_REVIEW_REQUIRED`; the detector never silently chooses a branch.

`flower_roller_evidence.py` consumes only pass-linked historical roller records.
It sorts candidates deterministically by evidence tier, confirmation, recognition
score, evidence coverage, historical-match score, design ID, then revision ID.
No roller evidence is fabricated when there is no explicit station/pass linkage.

## Evidence boundary

Evidence tiers range from a direct confirmed drawing design through confirmed
historical usage and recognition candidates to inventory-geometry support. The
fallback is `INSUFFICIENT_ROLLER_EVIDENCE`.

Every generated bundle records `manufacturing_approval: NOT_APPROVED` and
`physical_asset_assignment: false`. Physical inventory assets, when supplied,
are informational enrichment under a selected **design**; they are never an
automatic assignment or tooling recommendation.

## Persistence and exports

The generated candidate JSON persists its evidence bundle and a separate
`visual_flower_roller_evidence_bundles` row stores its hashes and snapshot
metadata. Exports include `roller_evidence.csv`, the candidate JSON, the ZIP,
and the station-by-station HTML table. The report footer retains the manufacturing
safety boundary.

## Current limitations

The integration deliberately does not run a second CAD parser, infer an
unproven station-to-roller relationship, synthesize new roller surfaces, select
a physical asset, calculate roll forces, or approve manufacturing tooling.
Historical records must contain a defensible `flower_id` + `pass_id` association
before they can support a generated station.
