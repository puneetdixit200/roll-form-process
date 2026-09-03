# Resume & Interview Guide

This guide turns the repository into concise, defensible resume language and interview talking points.

The main rule is simple: **describe what the software actually does, and keep visual/design evidence separate from manufacturing approval.** That makes the project sound stronger, not weaker, because the architecture is explainable rather than magical.

## Recommended project name

Use:

```text
RollForm Intelligence
```

Alternative:

```text
AI-Assisted Roll-Form CAD & Tooling Evidence System
```

Avoid titles such as:

```text
Autonomous Roll-Form Manufacturing System
Production Tooling Optimizer
```

because the project intentionally does not claim automatic production approval.

## One-line resume description

> Built a full-stack roll-form engineering prototype that imports DWG/DXF profiles, generates multi-stage flower sequences, retrieves similar historical passes, and ranks traceable roller-design evidence using Python/FastAPI, React/TypeScript, SQLite and explainable geometry models.

## Recommended resume bullets

### Balanced software + ML version

- Built a **DWG/DXF roll-form engineering platform** using Python, FastAPI, React/TypeScript, SQLite and `ezdxf`, enabling CAD profile extraction, browser-based geometry inspection and multi-stage flower-sequence generation.
- Implemented a **hybrid learned + deterministic generation pipeline** with CLRSG residual modelling, out-of-distribution fallback and constant-centerline-length constraints for reproducible visual flower candidates.
- Designed an **explainable roller-design traceability system** that links each generated station to its top historical matches, aggregates multi-source roller evidence, and lets engineers navigate to the exact historical source pass before accepting/rejecting evidence.

### Strong software-engineering version

- Designed an end-to-end **CAD analysis and decision-support platform** with FastAPI, React, SQLAlchemy/SQLite and Docker, supporting authenticated DWG/DXF ingestion, asynchronous analysis, visual profile selection, generation, review and exports.
- Built deterministic **historical retrieval and provenance pipelines** that preserve source flower/pass IDs, evidence hashes, roller design revisions and append-only engineer review decisions for reproducible audits.
- Added CI/CD quality gates with Pytest, frontend tests, deterministic synthetic regressions, Docker smoke tests and Railway runtime/readiness checks.

### Strong ML / applied-algorithms version

- Developed a **history-constrained flower-sequence generator** using normalized profile geometry, a compact CLRSG residual model and deterministic fallback logic for unsupported/out-of-distribution profiles.
- Built multi-component historical similarity retrieval using geometry-derived evidence and top-match provenance, then fused results with roller-recognition and confirmed historical usage to rank roller-design candidates by station/role.
- Implemented deterministic evidence aggregation that preserves multiple historical origins for the same roller design instead of collapsing traceability into a single opaque confidence score.

## Best 3-bullet version for a one-page resume

Use this if space is limited:

```text
RollForm Intelligence | Python, FastAPI, React, TypeScript, SQLite, ezdxf, Docker

• Built a full-stack DWG/DXF roll-form engineering prototype for CAD profile extraction, visual validation and multi-stage flower-sequence generation.
• Developed a hybrid CLRSG + deterministic pipeline with OOD fallback and constant-length geometry constraints, then matched generated stations against historical flower passes.
• Designed explainable roller-design traceability that aggregates top historical evidence, links engineers to the exact source flower/pass, and persists append-only review provenance.
```

## Optional metrics

Metrics make resume bullets better only when you can reproduce them on the final merged SHA.

Safe metrics to consider after re-running the final suite:

```text
Python tests: use the exact final pytest count
Frontend tests: use the exact final test count
Docker/Railway smoke: PASS
Historical flowers/passes: use active dataset-status counts, not old hard-coded values
Constant centerline-length error: use the verified final measured maximum
```

Do not permanently write a test count or dataset count into your resume if it changes every few commits.

A good phrasing after final verification could be:

> Validated with 300+ automated Python tests plus frontend, Docker and Railway runtime smoke checks.

Only use that sentence after confirming the final branch still satisfies the number.

## Tech stack to list

### Core

```text
Python
FastAPI
React
TypeScript
SQLite
SQLAlchemy
Docker
GitHub Actions
```

### Geometry / data

```text
ezdxf
NumPy
SciPy
Shapely
NetworkX
Pandas
```

### Deployment

```text
Railway
Docker
Vite
```

Do not list every dependency on the resume. Pick the technologies relevant to the role.

## What makes the project interesting

### 1. It is not just CRUD

The backend performs actual geometry processing:

```text
CAD parsing
connected geometry extraction
arc/polyline handling
profile normalization
historical geometry comparison
sequence generation
roller-recognition evidence fusion
```

### 2. It has a real safety/fallback model

The learned generator is not trusted blindly.

```text
input profile
→ readiness/OOD check
→ learned CLRSG path OR deterministic fallback
→ geometry constraint projection
```

That is a good interview story because it shows you designed for failure rather than assuming every model prediction is usable.

### 3. It separates design evidence from physical inventory

This is a strong domain-modeling decision:

```text
Roller Design
    ≠
Physical Roller Asset
```

The system ranks reusable design evidence first and shows physical inventory separately.

### 4. It preserves provenance

If two different historical matches support the same roller design, both source paths are preserved.

This allows:

```text
generated station
→ candidate roller design
→ historical source #1
→ historical source #2
→ exact flower/pass
```

That is stronger than one unexplained confidence number.

## 30-second interview explanation

> The project is a decision-support system for roll-forming CAD. A user uploads a DWG or DXF, selects and validates the final profile, and the backend generates candidate flower sequences. Each generated station is compared with historical passes. I then combine those matches with roller-recognition and confirmed historical-usage records to rank roller design evidence by role. The UI can trace any recommendation back to the exact historical flower and pass, and an engineer can accept, reject or flag the evidence. The system uses a learned CLRSG path where supported and deterministic fallback otherwise.

## 60-second technical explanation

> The architecture has a React/TypeScript frontend and FastAPI backend. CAD processing stays server-side with ezdxf and geometry libraries. A selected profile is normalized into a versioned visual profile contract and validated before generation. The generation layer supports both deterministic interpolation and a learned residual model called CLRSG. Model readiness and OOD checks decide whether the learned path is safe to use, and generated open profiles are projected through a constant-centerline-length constraint. For every generated pass, the system calculates top historical matches. A separate roller-evidence layer joins those matches with station-level historical usage, deterministic roller-recognition candidates and inventory metadata. Evidence is ranked by provenance tier, and multiple supporting historical origins are retained. The frontend lets an engineer open the exact historical source pass and records review decisions with evidence hashes for reproducibility.

## Interview architecture answer

If asked, "How is the system divided?":

```text
1. CAD ingestion
   DWG/DXF → staged DXF → preview → candidate profile

2. Profile validation
   schema + geometry checks

3. Flower generation
   deterministic / CLRSG → constant-length constraint

4. Historical retrieval
   generated pass → top historical pass matches

5. Roller evidence
   direct project + historical usage + recognition + inventory

6. Traceability
   roller candidate → source flower/pass

7. Review / audit
   accept/reject/needs-review + hashes/provenance
```

## Interview question: "Where is AI used?"

Good answer:

> AI/ML is not used as a blanket replacement for geometry. The learned portion is the CLRSG residual sequence model, which adjusts a structured baseline using a compact learned representation. It is gated by readiness and OOD logic, and deterministic generation remains the fallback. Historical matching and roller evidence are intentionally explainable and deterministic rather than delegated to an LLM.

## Interview question: "Why not use a neural network for roller selection?"

> The available historical evidence is sparse and engineering provenance matters. A deterministic recognition system can expose shape, dimension, role, fingerprint and historical-usage evidence and can abstain when information is incomplete. For this domain, that is safer and easier to review than an opaque model that always returns a roller.

## Interview question: "How do you avoid stale evidence?"

> Generated evidence is tied to version/hash identity such as the historical dataset, inventory snapshot, algorithm version and evidence bundle. Reviews are append-only. When upstream evidence changes, new runs can generate a different snapshot without rewriting the evidence an engineer previously reviewed.

## Interview question: "What happens if a profile is unlike the training data?"

> The CLRSG path is gated by an out-of-distribution/readiness check. If the profile is unsupported, generation falls back to the deterministic geometry engine instead of forcing a learned prediction.

## Interview question: "What was the hardest engineering problem?"

A strong answer:

> One difficult part was preserving provenance while aggregating evidence. If two of the top three historical matches both support the same roller design, a naive `group by design_id` loses one source. I changed the evidence model so the candidate keeps all supporting origins, computes support across unique historical match ranks and separately chooses a semantically ranked best origin. That lets the engineer see consensus without losing auditability.

## Interview question: "How is the data model structured?"

Mention:

```text
Project
ExtractionRun
Station
Profile
RollerOccurrence
RollerDesign
GeometryRevision
RollerAsset
HistoricalUsage
HistoricalFlower
HistoricalPass
RollerStationEvidence
ReviewDecision
```

The key domain distinction is reusable design vs physical asset.

## What not to claim

Do not say:

```text
"The model designs production-ready rollers automatically."
"The generated flower is manufacturing approved."
"The software guarantees tooling compatibility."
"We trained on a large industrial dataset."
```

Better:

```text
"The system ranks historical roller-design evidence for engineer review."
"The generated flower is a visual/history-constrained candidate."
"Physical assets are informational and remain separate from design evidence."
"The pipeline is designed for sparse private historical data with deterministic fallbacks."
```

## GitHub presentation checklist

Before putting the repository on your resume:

```text
[ ] README reflects the current visual system
[ ] architecture doc is linked
[ ] historical traceability doc is linked
[ ] no private CAD is committed
[ ] no credentials/.env/runtime database is committed
[ ] final branch CI is green
[ ] screenshots, if added later, use only safe/public data
[ ] resume test metrics match the final merged SHA
```

## Suggested resume project block

```text
RollForm Intelligence | Python, FastAPI, React, TypeScript, SQLite, ezdxf, Docker
GitHub: github.com/puneetdixit200/roll-form-process

• Built a full-stack DWG/DXF engineering prototype for profile extraction, validation and multi-stage roll-form flower generation.
• Implemented a guarded CLRSG learned-generation path with deterministic OOD fallback and geometry constraints, plus historical pass retrieval.
• Built explainable roller-design traceability across top historical matches with exact source-pass navigation and append-only engineer review provenance.
```

That wording is technically defensible and gives an interviewer several useful threads to pull on.
