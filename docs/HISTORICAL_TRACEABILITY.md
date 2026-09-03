# Historical Roller Traceability

This document explains how the visual flower generator connects a generated station to historical flower passes and then to explainable roller-design evidence.

The feature is designed to reduce engineer search time without turning historical similarity into an automatic manufacturing recommendation.

## Goal

For every generated station, answer four questions:

1. Which historical passes are geometrically most similar?
2. Which roller designs were associated with those historical passes?
3. Does the same design receive support from more than one top historical match?
4. Can the engineer open the exact source flower/pass and review the evidence before recording a decision?

## Evidence chain

```text
Generated Candidate
      ↓
Generated Pass / Station
      ↓
Top historical matches
      ↓
Historical flower + pass identifiers
      ↓
Station-level roller evidence
      ↓
Roller design candidates by role
      ↓
Supporting origins
      ↓
Historical Source Flower Explorer
      ↓
Engineer review
```

## Generated pass matching

Each generated pass contains historical matching information produced by the visual flower engine.

A match contains provenance including:

```text
match_rank
source_flower_id
source_pass_id
overall_score
evidence_coverage
score components
historical geometry
```

The traceability layer consumes the top matches already produced by the generator. It does not perform a second independent search.

## Roller design evidence

`flower_roller_evidence.py` builds station-by-station roller-design evidence.

Evidence can come from two distinct origin classes.

### Direct project evidence

```text
origin_kind = DIRECT_PROJECT
```

This is evidence extracted from the currently uploaded project/drawing and then passed through the existing roller-recognition system.

It may contain:

```text
source_project_id
source_station_id
source_occurrence_id
recognition score
role
design/revision
```

It does not pretend to be historical source evidence.

### Historical match evidence

```text
origin_kind = HISTORICAL_MATCH
```

This connects a roller-design record to one of the historical flower/pass matches for the generated station.

It may contain:

```text
source_reference_id
source_flower_id
source_pass_id
match_rank
historical similarity
evidence coverage
confirmation status
association method
```

## Evidence tiers

The system ranks evidence by strength before secondary scoring.

Conceptually:

```text
Tier 1  direct + engineer-confirmed design evidence
Tier 2  direct + recognized design evidence
Tier 3  confirmed historical usage from a matched pass
Tier 4  historical recognition candidate
Tier 5  inventory/geometry evidence
Tier 6  insufficient support / abstention
```

The exact runtime constants are defined in `flower_roller_evidence.py`.

## Multiple historical origins

A key design requirement is that aggregation does not destroy provenance.

Example:

```text
Top match #1
PRIVATE-FLOWER-003 / P9
UPPER → RD-017

Top match #2
PRIVATE-FLOWER-001 / P7
UPPER → RD-017

Top match #3
PRIVATE-FLOWER-002 / P8
UPPER → RD-021
```

The result should preserve:

```text
RD-017
  support count: 2 of top 3
  origins:
    #1 PRIVATE-FLOWER-003 / P9
    #2 PRIVATE-FLOWER-001 / P7

RD-021
  support count: 1 of top 3
  origin:
    #3 PRIVATE-FLOWER-002 / P8
```

`2 of top 3` means two distinct historical match ranks support the design. It is not interpreted as a 67% manufacturing probability.

## Best support origin

Every aggregated candidate can expose a `best_support_origin` for convenience.

That origin is chosen by semantic evidence ranking, not by source-reference hash order.

Ranking should prefer stronger evidence, confirmed records, stronger match rank/recognition/evidence coverage, then deterministic identifiers as tie-breakers.

All other valid origins remain visible.

## Historical source reference

Historical evidence can carry a deterministic redacted source reference such as:

```text
hsr-...
```

The identifier is derived from dataset/source evidence identity and is safe to persist in review records. It does not encode a local filesystem path.

Direct-project evidence does not need a fake historical source reference.

## Historical Source Flower Explorer

The browser can open an exact historical source from either:

- a top historical match card; or
- a supporting historical origin under a roller-design candidate.

The explorer loads:

```text
Historical flower sequence
      ↓
Requested source pass highlighted
      ↓
Selected pass detail
      ↓
Historical roller roles/designs for that pass
```

The full flower endpoint provides the sequence, while the pass-detail endpoint can provide richer station-level evidence for the selected pass.

The explorer supports:

```text
Previous
Play/Pause
Next
pass buttons
Back to generated station
```

A missing requested pass produces an explicit error rather than silently displaying another station.

## Engineer review

The engineer can record:

```text
Accept evidence
Reject evidence
Needs review
```

A review may preserve:

```text
selected design ID
selected revision ID
selected historical source reference
source flower/pass
match rank
reviewer
evidence bundle hash
notes/reason codes
```

The backend validates that a submitted historical source actually belongs to the selected roller candidate.

## Source-selection scope

Historical source selection is scoped to the active:

```text
candidate
+ generated pass/station
+ role
+ design
+ revision
```

This prevents an engineer's source selection from one generated station leaking into another station that happens to use the same design ID.

## Historical dataset

The historical retrieval dataset is versioned and hashed.

It may contain:

```text
historical flowers
passes
safe shape geometry
station-level roller evidence
quality flags
extractor metadata
```

The runtime dataset can grow independently from the learned model's original training dataset.

## Ingestion modes

Historical flower ingestion retains compatibility with legacy POLYLINE sources and supports LWPOLYLINE-oriented ingestion. Extractor-mode metadata records the requested and actually used ingestion path.

If a source cannot be safely extracted into a usable multi-pass flower sequence, it should remain review-required rather than entering the active dataset as fabricated geometry.

## Privacy

The customer-facing traceability workflow should expose only:

```text
redacted flower IDs
redacted pass IDs
derived geometry
reviewed roller design evidence
source-reference IDs
```

It should not expose:

```text
original private CAD
local paths
machine usernames
credentials
private deployment files
```

## Engineering boundary

Traceability answers:

> "What historical evidence supports this roller design candidate, and where did it come from?"

It does not answer:

> "Is this production tooling approved?"

The final engineering state remains:

```text
MANUFACTURING APPROVAL: NOT_APPROVED
PHYSICAL ROLLER AUTO-SELECTION: FALSE
```
