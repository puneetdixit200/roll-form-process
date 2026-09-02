# RollForm Intelligence

A visual engineering prototype for **DWG/DXF roll-forming analysis, flower-sequence generation, historical similarity search, and roller-design evidence traceability**.

The project combines deterministic CAD extraction, a learned visual sequence model with an out-of-distribution fallback, historical pass matching, explainable roller-design recognition, and an engineer-facing React/FastAPI application.

> **Engineering boundary:** this system provides visual geometry and historical design evidence. It does **not** approve manufacturing feasibility, automatically select a physical production roller, or replace engineering review.

## Why this project exists

Roll-forming engineers often need to move between CAD drawings, historical flower sequences, roller records, and review notes before deciding which previous tooling evidence is relevant to a new profile. That process is slow when the evidence is scattered.

This project puts those steps into one traceable workflow:

```text
Upload DWG/DXF
      ↓
Inspect drawing and select the final target profile
      ↓
Validate target geometry
      ↓
Generate candidate flower sequences
      ↓
Compare every generated station with the top historical matches
      ↓
Rank roller-design evidence by role and provenance
      ↓
Open the exact historical source flower/pass behind the evidence
      ↓
Engineer accepts, rejects, or flags the evidence for review
```

## Key capabilities

### CAD ingestion and visual profile selection

- Accepts DXF directly and supports DWG when an external converter is available.
- Stages source files without modifying the original CAD.
- Renders a safe vector drawing preview in the browser.
- Detects connected profile candidates from CAD geometry.
- Supports line, polyline, arc and LWPOLYLINE-oriented workflows, including arc-aware DXF handling.
- Lets the engineer inspect, pan, zoom, fit, select, edit and validate the target profile before generation.

### Flower-sequence generation

- Generates configurable multi-stage visual flower candidates from a validated final profile.
- Uses deterministic geometry as a safe fallback.
- Supports the private CLRSG learned residual model when its readiness/OOD checks pass.
- Enforces the existing constant-centerline-length constraint on generated open profiles.
- Keeps model provenance separate from the active historical retrieval dataset.

### Historical matching

- Compares every generated pass against the historical flower dataset.
- Keeps the top historical matches with explainable score components and provenance.
- Stores the exact source flower/pass used for each match.
- Uses safe derived historical geometry rather than exposing original private CAD.

### Roller-design evidence

- Reuses the existing deterministic roller-recognition and historical-usage systems.
- Ranks **roller designs**, not physical roller assets.
- Preserves multiple supporting historical origins for the same design.
- Reports support such as `2 of top 3 historical matches` without converting it into a fake probability.
- Distinguishes direct uploaded-project evidence from historical-match evidence.
- Shows inventory assets separately as informational enrichment only.

### Historical source traceability

The engineer can navigate from a generated station back to the exact historical evidence:

```text
Generated station
  ├── Top match #1 → historical flower/pass
  ├── Top match #2 → historical flower/pass
  └── Top match #3 → historical flower/pass
          ↓
     Roller design evidence
          ↓
     Historical Source Flower Explorer
          ↓
     Exact source pass highlighted
```

The source explorer supports pass navigation and shows reviewed roller-role/design evidence for the selected historical pass.

### Review and auditability

- Engineer review is append-only.
- Decisions support accept, reject and needs-review states.
- Review records preserve selected roller design/revision, evidence-bundle hash, and historical source provenance when available.
- Historical datasets and generated evidence are version/hash aware for reproducibility.

## Architecture

```text
                           ┌─────────────────────────┐
                           │      React / Vite       │
                           │  Visual Engineering UI  │
                           └────────────┬────────────┘
                                        │ HTTP / JSON
                           ┌────────────▼────────────┐
                           │       FastAPI API       │
                           │ auth · jobs · exports   │
                           └───────┬────────┬────────┘
                                   │        │
                  ┌────────────────┘        └─────────────────┐
                  │                                           │
       ┌──────────▼──────────┐                    ┌───────────▼───────────┐
       │ CAD / Flower Engine │                    │ Roller Evidence Engine │
       │ ezdxf · geometry    │                    │ recognition · history  │
       │ CLRSG · OOD fallback│                    │ provenance · review    │
       └──────────┬──────────┘                    └───────────┬───────────┘
                  │                                           │
       ┌──────────▼──────────┐                    ┌───────────▼───────────┐
       │ Historical Dataset  │                    │ SQLite / SQLAlchemy   │
       │ versioned + hashed  │                    │ projects · inventory  │
       └─────────────────────┘                    └───────────────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the detailed component and data-flow breakdown.

## Technology stack

| Area | Technologies |
| --- | --- |
| Backend | Python 3.11+, FastAPI, SQLAlchemy |
| CAD / geometry | ezdxf, NumPy, SciPy, Shapely, NetworkX |
| Frontend | React, TypeScript, Vite |
| Data | SQLite, JSON, CSV, versioned evidence artifacts |
| Learned generation | CLRSG prototype: PCA-style latent representation + ridge residual ensemble, guarded by readiness/OOD logic |
| Deployment | Docker, Railway |
| Quality | Pytest, frontend test runner, GitHub Actions, Docker/Railway smoke tests |

## Repository structure

```text
src/rollform_extractor/
  flower_generation.py              # deterministic flower generation
  visual_flower_engine.py           # visual candidate construction and matching
  flower_roller_evidence.py         # station-by-station roller-design evidence
  historical_source_traceability.py # historical source navigation/provenance
  roller_recognition.py             # explainable roller-design recognition
  validated_usage.py                # confirmed historical design usage
  flower_prototype_dataset.py       # historical flower dataset ingestion/schema
  flower_dataset_validation.py      # shared dataset validation
  web/backend/                      # FastAPI application services

frontend/src/features/visual-flower/
  VisualFlowerWorkspace.tsx
  CadDrawingCanvas.tsx
  HistoricalSourceFlowerExplorer.tsx

backend/                             # API entry points
scripts/                             # synthetic validation / release tooling
tests/                               # Python regression suite
frontend/                            # React application
docs/                                # architecture, specs, reports and resume guide
```

## Installation

Python 3.11+ is required.

```bash
python -m pip install -e ".[backend,test]"
```

Frontend:

```bash
cd frontend
npm ci
```

## Run locally

Backend:

```bash
PYTHONPATH=src uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
VITE_API_ROOT=http://127.0.0.1:8000 npm run dev
```

Then open:

```text
http://127.0.0.1:5173
```

Docker Compose:

```bash
docker compose up --build
```

## Railway-style production image

The repository includes:

```text
Dockerfile.railway
railway.toml
```

The Railway image serves the built React frontend and FastAPI backend from one service and includes authenticated/runtime smoke coverage in CI.

## Useful CLI commands

The project includes a broader extraction/inventory toolchain in addition to the visual app.

```bash
rollform-extractor inspect SOURCE
rollform-extractor extract SOURCE OUTPUT_ROOT
rollform-extractor validate PROJECT_DIR
rollform-extractor batch-extract SOURCE_ROOT OUTPUT_ROOT --resume --skip-unchanged

rollform-extractor roller-inventory-validate INVENTORY.csv --database inventory.sqlite
rollform-extractor roller-inventory-import INVENTORY.csv --database inventory.sqlite
rollform-extractor roller-recognition-run PROJECT_DIR --inventory DATABASE --output OUTPUT_DIR

rollform-extractor flower-prototype-ingest SOURCE_ROOT OUTPUT_ROOT \
  --manifest FLOWERS.json \
  --database prototype.sqlite
```

Use `rollform-extractor --help` for the complete command list.

## Historical data and privacy

Private customer CAD, runtime databases, credentials, and private model artifacts are intentionally not committed to this repository.

The hosted/customer-safe application exposes only derived/redacted geometry and evidence identifiers. Historical source navigation uses redacted flower/pass IDs rather than local file paths.

The project also supports public/synthetic fixtures so CI can test the pipeline without private source material.

## Engineering safety model

The distinction below is deliberate:

```text
Roller design
    ≠
Physical roller asset
    ≠
Manufacturing approval
```

The system may show:

- best-supported roller-design candidates;
- confirmed historical design usage;
- recognition scores and evidence coverage;
- known inventory assets for a design;
- exact historical source flower/pass provenance.

It does **not** automatically claim:

- that a generated flower is physically manufacturable;
- that a roller design is approved for production;
- that a physical roller asset is compatible or available for use;
- that springback, force, roll gap, shaft loading or FEA requirements are satisfied.

## Validation and CI

The GitHub Actions quality pipeline runs on `main`, `feature/**`, `fix/**` and `release/**` branches and covers:

- Python compile and Pytest regression suites;
- deterministic synthetic recognition/validation checks;
- CLRSG public-fixture/model regressions;
- React tests and production build;
- Docker Compose build/smoke;
- Railway image build/readiness smoke;
- authenticated Railway-image API smoke.

Run locally:

```bash
python -m compileall src backend scripts
pytest -q

cd frontend
npm test -- --run
npm run build
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Historical Roller Traceability](docs/HISTORICAL_TRACEABILITY.md)
- [Resume & Interview Guide](docs/RESUME_GUIDE.md)
- [Pass Feature Schema](docs/pass-feature-schema-v1.md)
- [Phase 16 Roller Inventory](docs/specs/phase-16-roller-inventory.md)
- [Phase 17 Roller Recognition](docs/specs/phase-17-roller-recognition.md)
- [Phase 18 Validated Usage Search](docs/specs/phase-18-validated-usage-search.md)

## Resume-safe project summary

> **RollForm Intelligence** — Built a full-stack CAD engineering prototype using Python/FastAPI, React/TypeScript, SQLite and ezdxf to import DWG/DXF profiles, generate multi-stage roll-form flower sequences, retrieve similar historical passes, and rank traceable roller-design evidence with engineer review and deterministic fallbacks.

For stronger resume bullets and interview talking points, see [docs/RESUME_GUIDE.md](docs/RESUME_GUIDE.md).

## Status

This repository is an **engineering prototype**, with deterministic fallbacks, explicit evidence provenance and automated regression/deployment checks. Manufacturing approval remains outside the software boundary and requires qualified engineering review.
