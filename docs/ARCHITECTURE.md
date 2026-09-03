# Architecture

This document describes the architecture of **RollForm Intelligence**, the visual roll-form engineering prototype in this repository.

The system is intentionally split into deterministic extraction/generation layers, historical evidence layers, review/audit layers, and a browser-facing application. The backend remains the source of truth for CAD and engineering geometry. The frontend visualizes and orchestrates those results rather than reimplementing the engineering pipeline in JavaScript.

## 1. System context

```text
Engineer
   │
   ▼
React / TypeScript UI
   │
   ▼
FastAPI application
   │
   ├── CAD import / profile detection
   ├── profile validation
   ├── visual flower generation
   ├── historical pass matching
   ├── roller-design evidence
   ├── historical source traceability
   ├── engineer review
   └── export / deployment health
   │
   ├───────────────┬──────────────────────┬───────────────────┐
   ▼               ▼                      ▼                   ▼
CAD workspace   Historical dataset   Roller inventory   SQLite audit data
```

## 2. Primary workflow

```text
DWG / DXF
   ↓
Safe staged CAD
   ↓
Drawing preview + connected profile candidates
   ↓
Engineer selects target profile
   ↓
Backend validation
   ↓
Flower generation
   ↓
Constant-length projection / geometry constraints
   ↓
Historical top-match retrieval
   ↓
Roller-design evidence by generated station
   ↓
Historical source flower/pass traceability
   ↓
Engineer evidence decision
   ↓
Reproducible export package
```

## 3. CAD ingestion

Relevant modules include:

```text
visual_flower_import.py
visual_cad_profile_detection.py
visual_profile_schema.py
visual_profile_validation.py
converter.py
dxf_reader.py
```

### Responsibilities

- stage source CAD without modifying the original file;
- convert DWG to DXF when a supported converter is available;
- read modelspace with `ezdxf`;
- create safe browser preview primitives;
- preserve source handles/layers as provenance;
- assemble connected candidate target profiles;
- validate the selected `VisualProfile` contract.

The browser receives derived vector geometry, not the private source path or raw CAD file.

## 4. Visual target representation

The browser/backend exchange a versioned `VisualProfile` containing:

```text
vertices
segments
LINE / ARC geometry
topology
computational seam for closed contours
visual-only metadata
```

The profile validator checks structural and geometric invariants before generation. Client state keeps the validated profile snapshot separate from the backend validation hash so a profile edit invalidates prior validation without confusing provenance identifiers.

## 5. Flower generation

Relevant modules:

```text
flower_generation.py
visual_flower_engine.py
strip_length_constraint.py
clrsg_inference.py
private_clrsg.py
```

The system has two generation paths.

### Deterministic generation

Provides a repeatable geometry-only fallback and remains available even when the learned model is unavailable or rejects the target as out of distribution.

### CLRSG learned generation

The private CLRSG prototype learns a residual correction over a compact profile representation. Readiness and OOD logic gate its use.

The learned path does not remove deterministic safety behavior:

```text
Target profile
   ↓
CLRSG readiness/OOD decision
   ├── accepted → learned residual candidate
   └── rejected → deterministic fallback
   ↓
constant-centerline-length projection
```

The active retrieval dataset and model-training provenance are intentionally tracked as different concepts. Adding historical retrieval data does not imply the current learned model was trained on that data.

## 6. Historical matching

`visual_flower_engine.py` compares each generated pass with the active historical flower dataset and retains top matches with provenance such as:

```text
source_flower_id
source_pass_id
match_rank
overall_score
evidence_coverage
score components
historical geometry
```

These match records are the bridge between generated geometry and historical roller-design evidence.

## 7. Historical dataset

Relevant modules:

```text
flower_prototype_dataset.py
flower_dataset_validation.py
historical_source_traceability.py
```

Historical data is versioned and hashed. The active dataset can evolve independently from the CLRSG model.

A dataset contains:

```text
historical flowers
historical passes
safe derived shape geometry
source hashes for local provenance
coarse roller evidence
station-level roller-design evidence
quality flags
extractor-mode metadata
```

Dataset readiness is structural rather than tied to one fixed historical count.

Private source CAD itself is not stored in Git.

## 8. Roller design evidence

Core module:

```text
flower_roller_evidence.py
```

The system ranks **roller design evidence**, not physical roller assets.

Evidence may come from:

```text
DIRECT_PROJECT
    extracted from the currently uploaded drawing/project

HISTORICAL_MATCH
    associated with one of the generated pass's historical source matches
```

Evidence tiers prioritize stronger provenance. Candidate aggregation preserves multiple historical origins when the same design is supported by more than one top match.

Example:

```text
Generated station 7

UPPER RD-017
  ├── top match #1 → FLOWER-003 / P9
  └── top match #2 → FLOWER-001 / P7

Historical support: 2 of top 3 matches
```

The support count represents distinct historical match ranks, not a probability of manufacturing correctness.

## 9. Roller recognition and inventory

Relevant modules:

```text
roller_recognition.py
roller_inventory.py
validated_usage.py
database.py
```

Recognition is deterministic and explainable. It can use:

```text
shape similarity
physical dimensions when units are confirmed
role compatibility
fingerprints
curvature/groove evidence
confirmed historical usage
```

The system supports abstention when evidence is insufficient or ambiguous.

### Domain distinction

```text
Roller Design
    describes reusable geometry/design evidence

Physical Roller Asset
    describes an actual inventory item
```

A design match does not automatically assign a physical asset.

## 10. Historical source traceability

The source-traceability layer resolves an evidence origin back to the exact historical flower/pass.

```text
Generated station
   ↓
Roller candidate
   ↓
Supporting origin
   ↓
source_reference_id
   ↓
Historical flower
   ↓
Historical pass
```

The browser's historical source explorer loads the full redacted sequence and separately loads detail for the selected pass so pass-level roller roles/designs can be displayed.

A missing source pass fails explicitly rather than silently navigating to another historical station.

## 11. Engineer review

Review is append-only.

A review can capture:

```text
candidate / generated pass
roller role
selected design
selected revision
decision
reviewer
selected historical source when applicable
evidence bundle hash
notes / reason codes
```

Supported decisions include:

```text
ACCEPT_DESIGN_EVIDENCE
REJECT_DESIGN_EVIDENCE
NEEDS_REVIEW
```

Historical source IDs submitted by the browser are validated against the actual selected candidate's supporting origins.

## 12. Persistence

The project uses SQLite/SQLAlchemy for project, inventory and review/audit persistence.

Important persistence principles:

- generated evidence stores snapshot/hash identity;
- external project/design IDs are persisted without brittle cross-database foreign keys;
- historical dataset identity is explicit;
- reviews do not rewrite previous evidence bundles;
- old datasets/reviews remain readable through compatibility paths where practical.

## 13. Frontend

Primary visual components include:

```text
VisualFlowerWorkspace.tsx
CadDrawingCanvas.tsx
ProfileSketcher.tsx
HistoricalSourceFlowerExplorer.tsx
```

The browser handles:

```text
workflow navigation
canvas interaction
profile selection/editing
visual comparison
source navigation
review actions
```

Engineering geometry calculations remain server-side unless they are purely display transforms.

## 14. API layer

The FastAPI service exposes routes for:

```text
authentication
health/readiness
CAD import/workflow status
visual profile validation
flower generation
historical dataset status
historical source flower/pass detail
roller evidence and review
inventory/project analysis
exports
```

In Railway mode the built React application and API are served same-origin.

## 15. Deployment

`Dockerfile.railway` builds the frontend and Python runtime into a single production image.

`railway.toml` configures Railway health/readiness behavior.

Runtime state belongs under the configured persistent data volume. Secrets and private datasets are injected at deployment time and are not committed.

## 16. CI / quality gates

`.github/workflows/quality.yml` covers:

```text
Python compile
Pytest suite
flower-generation regressions
roller-recognition regressions
synthetic determinism checks
CLRSG public-fixture checks
React tests
frontend production build
Docker Compose smoke
Railway image health/readiness smoke
authenticated Railway-image smoke
```

## 17. Safety boundary

This architecture intentionally stops before production tooling approval.

Not implemented as automatic claims:

```text
manufacturing feasibility approval
springback compensation approval
roll-force simulation approval
roll-gap optimization approval
shaft/bearing sizing approval
physical asset assignment
FEA / production tooling release
```

The system is an evidence and decision-support prototype. Qualified engineering review remains authoritative.
