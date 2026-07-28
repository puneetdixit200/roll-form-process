# Roll-Forming DWG Extractor Design

## Purpose

Build an offline Python 3.11+ command-line application that converts or reads a
roll-forming flower-sequence drawing, preserves every CAD entity, detects a
variable number of forming stations, classifies profiles and tooling where
evidence permits, and produces an auditable SQLite database plus segregated
engineering files and review artifacts.

The first integration-test drawing is:

`/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg`

This path is not an application default. Every source path is supplied through
the CLI or a batch input directory. The originally requested
`/mnt/data/D0064-D0065-FlowerSequence(1).dwg` is not present in the execution
environment. Every source drawing is read-only input and must never be modified.

## Scope

The first version is deterministic. It does not train or require a machine
learning model. Classification combines independent CAD evidence and routes
ambiguous cases to manual review.

The application supports DWG through an external conversion layer and supports
DXF directly. It operates on model-space and paper-space entities but excludes
paper-space and marked drawing-support entities from mechanical classification.
No entity is deleted from the entity ledger.

## Architecture

The pipeline has eight boundaries:

1. **Input staging and conversion** validates the input, fingerprints it, copies
   converter output into the project output, and leaves the source untouched.
2. **Lossless drawing inspection and parsing** creates metadata and entity
   records before classification.
3. **Classification** marks drawing support, detects stations, profiles, and
   roller components using independent evidence.
4. **Normalization and feature extraction** creates comparison geometry while
   retaining original coordinates and dimensional scale.
5. **Persistence and export** writes one transactional SQLite database and
   segregated DXF, JSON, CSV, PNG, and HTML artifacts.
6. **Validation and review** verifies relational and filesystem integrity and
   exposes uncertain decisions through JSON/CSV overrides and review queues.
7. **Cross-project indexing** maps drawing occurrences to physical roller
   identities, reusable assembly templates, and geometry fingerprints.
8. **Batch orchestration** resumes idempotent per-project stages and aggregates
   project databases into a master database and dashboard.

Each stage accepts typed domain models and returns new models or classifications.
Stages do not mutate source CAD objects in place.

## Conversion

The converter resolver checks, in order:

1. ODA File Converter commands and common installation paths.
2. LibreDWG `dwg2dxf`.
3. Direct DXF input.

ODA conversion targets AutoCAD 2013 ASCII DXF first, then AutoCAD 2007 ASCII
DXF when necessary. Conversion runs in a temporary directory because ODA accepts
directory-oriented input and output. The resulting DXF is validated by opening
it with `ezdxf` before it is copied to
`output/<project>/source/converted.dxf`.

When no converter exists, DWG commands fail with a nonzero status and exact
instructions to export an AutoCAD 2013 or 2007 ASCII DXF. DXF commands remain
fully usable.

The application records SHA-256 hashes of the source before and after processing
and fails validation if they differ.

## Drawing Inspection

Inspection precedes classification and records:

- source and converted filenames, hashes, versions, units, extents, timestamps,
  model-space and paper-space counts;
- layers, colours, line types, visibility, and entity counts;
- block definitions, inserts, nested references, and external references;
- text, multiline text, dimension entities, creation metadata, and modification
  metadata when present.

The inspection command emits structured JSON and a readable console summary.
Missing optional metadata is stored as unavailable, not fabricated.

## Entity Ledger

The parser supports `LINE`, `LWPOLYLINE`, `POLYLINE`, `ARC`, `CIRCLE`,
`ELLIPSE`, `SPLINE`, `INSERT`, `TEXT`, `MTEXT`, `DIMENSION`, `HATCH`, and
`POINT`.

Every parsed entity stores:

- handle, type, layer, colour, line type, layout, block path, and original DXF
  attributes;
- authoritative original CAD primitives and bounding box;
- normalized CAD primitives transformed without curve approximation;
- sampled comparison geometry and Shapely WKT where valid;
- classification, evidence, confidence, and station ownership.

Shapely and sampled point sequences are comparison and preview representations,
not authoritative engineering geometry. Original primitives reconstruct DXF and
support radii and manufacturing measurements. Normalized primitives preserve
entity types and dimensional scale.

Every block insertion and nested occurrence records translation on all axes,
rotation, scale on all axes, parent block, mirror state, and its composed 4x4
transformation matrix. Child primitives retain both their block-local coordinates
and world-coordinate transform provenance.

Unsupported entities are also recorded with raw attributes and an
`unsupported` classification. A parsing problem creates a warning tied to the
handle and does not silently discard the entity.

## Drawing-Support Classification

Support detection marks title blocks, borders, tables, dimensions, notes, logos,
revision data, centre lines, construction lines, hidden layers, and paper-space
objects. Evidence includes layout, entity type, layer and block names, line
types, text density, large border-like extents, and table-like grids.

Support classifications remain reversible. Their entities stay in SQLite and
may be included in complete-station exports when explicitly overridden, but are
excluded from station, profile, and roller candidate generation by default.

## Station Detection

Station detection produces candidates through three independent strategies:

- **Text:** case-insensitive station/pass/stand patterns, compact labels such as
  `S1`, and isolated numbered labels with mechanical geometry nearby.
- **Blocks:** repeated inserts, nested blocks, repeated block signatures, and
  similarly structured entity groups.
- **Spatial:** connected-component grouping followed by adaptive clustering
  using entity-size-aware gaps and bounding-box relationships.

Candidate reconciliation builds an overlap graph with `networkx`. Compatible
candidates merge; geometry claimed by conflicting candidates stays associated
with both candidate records and enters review until resolution.

Layout ordering compares row and column separation. It supports horizontal,
vertical, reversed, and multi-row arrangements. Explicit numeric labels dominate
spatial order when they are internally consistent. When label and spatial order
conflict, the selected order is marked uncertain. There is no fixed or default
station count.

Station confidence is a weighted score in `[0, 1]` based on label evidence,
block repetition, spatial cohesion, topology similarity, overlap conflicts, and
ordering agreement. Scores below `0.60`, missing labels, or ordering conflicts
require manual review. Temporary labels use `Station_Unknown_NN`.

## Profile Detection

Profile candidates are connected line, arc, spline, ellipse, and polyline
chains within each station. Candidate evidence includes:

- profile-related layer or block names;
- continuous open or closed sheet-like contours;
- developed-length consistency between consecutive stations;
- repeated topology and colour or line-type consistency;
- proximity to station and roller centre lines;
- single-centreline or parallel-boundary sheet representation;
- long connected chains relative to other station geometry.

The highest-scoring candidate becomes the station profile only when its margin
over the next candidate and its absolute confidence exceed configured
thresholds. Multiple plausible contours enter review.

Features include original and cleaned contours, width, height, developed length,
segment and arc counts, bend count, bend positions, angles, radii, segment
lengths, symmetry, bounding box, centre, sampled normalized points, and
confidence. Broken contours are retained with warnings and may still be
exported.

Each profile receives exact and mirrored geometry fingerprints based on developed
length, width, height, bend sequence, radii, curvature distribution, and sampled
contour points. Fingerprints group exact and similar profiles without replacing
the underlying engineering geometry.

The final station is the largest resolved sequence index, never an assumed
sixteenth station.

## Roller and Assembly Detection

Roller candidates are connected mechanical components containing circular,
arc-based, or rotational contour evidence. Bore/outer-circle relationships,
shared shaft centres, block and layer names, nearby identifiers, and placement
relative to the profile contribute evidence.

Components remain distinct unless connectivity and annotations show that they
form one component. Position classification uses profile-relative vertical and
horizontal regions to assign upper/lower, left/centre/right, side, guide,
support, shaft, spacer, or distance-ring roles. Weak role evidence produces an
unidentified roller rather than a guessed role.

Every station receives one assembly record, including profile-only stations.
Assemblies relate zero or more rollers through explicit membership rows.
Tooling absence is represented as unavailable and is not an extraction failure.

Repeated assembly arrangements may receive a reusable identity such as
`Assembly_Template_AT-0042`. A project assembly references the template while
retaining occurrence-specific roles, positions, provenance, and overrides.

## Physical Roller Identity

Drawing roller records describe detected geometry in one station. They do not
implicitly represent a unique factory asset. Cross-project physical identity is
stored separately:

- `roller_catalog` stores permanent factory ID, geometry fingerprint, bore,
  width, diameter, keyway, condition, storage location, and availability;
- `roller_occurrences` links source handles and a detected drawing role and
  position to a project, station, and optional catalog item;
- `project_roll_usage` links a catalog item to the station assembly where it is
  actually used.

Catalog matching uses exact identifiers first, then exact geometry fingerprints,
then configurable similarity candidates. Automatic catalog claims require high
confidence and uniqueness; otherwise the occurrence enters review. The first
implementation defers catalog matching until station and profile extraction pass
their reliability checks.

## Geometry Normalization

Units are converted to millimetres using the DXF unit declaration or an explicit
override. Unknown units remain uncertain and generate a blocking review item for
dimensional claims.

Normalization:

- keeps original coordinates unchanged;
- translates the station reference centre to the origin;
- mirrors only the comparison copy when needed for a consistent left-to-right
  orientation;
- never independently scales width or height;
- samples curves at configurable millimetre spacing;
- joins endpoints within a configurable millimetre tolerance;
- removes only duplicate comparison geometry below a configurable tolerance;
- records transformations and mirrored status.

Original CAD primitives, normalized CAD primitives, and sampled comparison
geometry are persisted separately. Every transformation stores a 4x4 matrix and
its inverse when invertible.

## Reproducible Configuration

All extraction tolerances live in one version-controlled YAML file:

```yaml
units:
  default: null
geometry:
  endpoint_join_tolerance_mm: 0.05
  duplicate_tolerance_mm: 0.01
  curve_sampling_spacing_mm: 0.25
  minimum_entity_length_mm: 0.02
stations:
  minimum_confidence: 0.60
  label_search_radius_mm: 100
  cluster_gap_factor: 1.5
profiles:
  minimum_confidence: 0.70
  minimum_score_margin: 0.15
rollers:
  minimum_confidence: 0.65
```

Each extraction run stores the fully resolved configuration and its SHA-256
hash. CLI overrides are serialized into that snapshot. Configuration changes
invalidate only dependent processing stages.

## Persistence

SQLAlchemy models provide the required tables:

`projects`, `extraction_runs`, `layers`, `stations`, `profiles`, `rollers`,
`assemblies`, `assembly_members`, `cad_entities`, `annotations`, `dimensions`,
`station_transitions`, `extraction_warnings`, `roller_catalog`,
`roller_occurrences`, `project_roll_usage`, `assembly_templates`,
`geometry_fingerprints`, `processing_stages`, and `result_provenance`.

Additional fields may store source hashes, metadata JSON, evidence JSON,
override provenance, and timestamps. SQLite foreign keys are enabled for every
connection. A run is committed transactionally after parsed entities and
classifications are complete. Failed runs retain a failed extraction-run record
when the database is writable.

Station transitions compare each consecutive resolved pair. Missing profiles
produce nullable measurements and a warning rather than preventing the row.

Every calculated engineering value has provenance containing source handles,
calculation method, configuration version, confidence, and optional warning.

Filenames are drawing identifiers, not guaranteed project identifiers. A project
code resolver stores a drawing such as `D0064-D0065-FlowerSequence` once and may
associate `D0064` and `D0065` as related project codes. Ambiguous codes enter
review or come from imported metadata.

## Material and Production Metadata

CSV and Excel imports may provide material grade, steel thickness, strip width,
coil width, machine ID, shaft diameter, product code, customer code, production
status, whether tooling worked, known defects, engineer notes, and COPRA project
reference. Rows resolve by explicit drawing ID or project code. Imported values
store source-file and row provenance.

Geometry extraction does not depend on this metadata. Missing fields remain
unknown and conflicting imports enter review.

## Batch and Master Database

Single-project databases remain the audit boundary. Batch aggregation creates:

```text
output/
├── master/
│   ├── master_rollform.sqlite
│   ├── projects.csv
│   ├── rollers.csv
│   └── extraction_dashboard.html
└── projects/
    └── <drawing-id>/
```

The master database contains all projects, stations, profiles, physical rollers,
assemblies, transitions, duplicate-profile groups, assembly templates, and
cross-project roller reuse. Master rows retain their source project database,
run ID, and local primary key so aggregation is traceable and repeatable.

Batch execution isolates project failures, writes an incremental run ledger, and
reports totals for files, conversions, review cases, failures, stations,
profiles, and rollers.

## Resumability and Idempotency

Each project records stage status for conversion, parsing, support
classification, station detection, profile detection, roller detection,
catalog matching, persistence, export, preview, and validation. A stage records
input hash, configuration subset hash, software version, timestamps, status, and
artifact hashes.

The runner can skip unchanged drawings, resume failed batches, rerun profile or
roller detection independently, and rebuild previews from persisted geometry.
Reprocessing creates a new run and preserves history. A stage is reused only
when all its declared input hashes and artifact validations match.

## Exports and Previews

The dynamic output tree follows the requested structure. Every detected station
gets one directory. DXFs reconstruct entities from stored geometry while
preserving original coordinates, layers, colours, and line types where possible.
Role-specific files are created when components exist; empty role files are not
used to imply detected tooling.

Matplotlib and Pillow generate:

- entire drawing preview;
- station boundary and label preview;
- profile preview per station;
- roller-role preview per station;
- colour-coded classification preview;
- unidentified-geometry preview.

Plots use equal aspect ratio and content-derived extents. Labels include station
or component identity and confidence. Profile, upper, lower, side, shaft,
dimension, and unidentified colours are visually distinct.

The HTML report links all exports, summarizes inspection and validation, lists
confidence and warnings, and embeds preview images.

## Manual Review and Overrides

The review queue is emitted as JSON and CSV. Review categories include uncertain
boundaries, missing labels, profile ambiguity, unidentified rollers, duplicate
IDs, low confidence, order conflict, overlapping ownership, broken contours,
and unit uncertainty.

`review` prints unresolved items and creates `manual_overrides.json` when absent.
Overrides support:

- units;
- station count and order;
- station bounding boxes;
- profile entity handles;
- roller entity handles and roles.

Overrides are schema-versioned and validated. Unknown handles, duplicate orders,
invalid boxes, and contradictory assignments fail clearly. `reprocess` reruns
from the converted DXF and applies overrides as explicit high-priority evidence.
It does not edit the prior run or source drawing.

The initial release keeps CLI, CSV, JSON, and static HTML review. A later local
browser interface will display the original drawing with classifications and
allow engineers to drag station boundaries, select profile entities, assign
roller roles, correct order, inspect handles, and confirm or reject detections.
It writes the same versioned override format rather than maintaining separate
correction logic. Confirmed corrections may later form a labelled training set.

## CLI

The package exposes:

```text
python -m rollform_extractor inspect INPUT
python -m rollform_extractor extract INPUT --output OUTPUT
python -m rollform_extractor review PROJECT_OUTPUT
python -m rollform_extractor reprocess INPUT --config OVERRIDES [--output OUTPUT]
python -m rollform_extractor validate PROJECT_OUTPUT
python -m rollform_extractor import-metadata METADATA.xlsx [--master MASTER_DB]
python -m rollform_extractor batch-extract INPUT_DIRECTORY --output OUTPUT --pattern "*.dwg"
python -m rollform_extractor batch-validate OUTPUT
python -m rollform_extractor batch-report OUTPUT
```

Batch extraction supports `--resume`, `--skip-unchanged`, and stage selection.

All commands return meaningful nonzero exit codes for input, conversion, parsing,
override, extraction, and validation failures. Logs distinguish warnings from
errors.

## Validation

Validation checks:

- source hash immutability;
- at least one station;
- unique station indices and a dynamically derived count;
- connected or explicitly warned profile geometry;
- consistent developed-length calculation;
- known or explicitly uncertain units;
- manifest and database agreement;
- existence and readability of every declared export;
- SQLite foreign-key integrity;
- separate original and normalized geometry;
- visible low-confidence and unresolved classifications;
- DXF re-import for generated DXFs.

Validation results are stored in JSON and included in the HTML report.

## Quantitative Accuracy

A benchmark command evaluates 10-20 engineer-labelled gold-standard drawings.
Initial targets are:

- station count accuracy at least 95%;
- station-boundary overlap at least 90%;
- profile identification accuracy at least 90%;
- roller-component recall at least 85%;
- roller-role accuracy at least 80%;
- incorrect automatic claims below 5%.

Geometry metrics include Hausdorff distance, mean contour distance,
developed-length error, bend-position error, bend-angle error, and bend-radius
error. Provisional limits are mean contour error at most 0.20 mm, developed
length error at most 0.10%, and bend-position error at most 0.50 mm. A
roll-forming engineer must approve or revise these provisional dimensional limits
before they become release gates.

## Testing

Tests generate synthetic DXFs with real `ezdxf` entities. Parametrized station
tests cover counts `8`, `12`, `15`, `16`, `18`, and `20`. Additional fixtures
cover unlabeled layouts, repeated blocks, multiple rows, profile-only and
profile-plus-roller drawings, millimetres and inches, mirrors, broken contours,
duplicates, missing rollers, empty layers, converter failure, database foreign
keys, and DXF export/re-import.

Converter invocation tests isolate external processes with temporary directories.
The installed ODA converter and supplied DWG are exercised as an integration run,
not treated as unit-test dependencies.

Tests also cover block transforms, nested mirrors, configuration snapshots,
idempotent stage reuse, interrupted batch resume, metadata imports, project-code
resolution, master aggregation, fingerprint grouping, catalog occurrence
linking, provenance, and deliberate refusal of ambiguous catalog matches.

## Implementation Order

Implementation proceeds through independently usable milestones:

1. DXF inspection and conversion.
2. Lossless entity ledger with exact CAD primitives and transforms.
3. Full-drawing preview.
4. Manual station bounding boxes.
5. Automatic station detection.
6. Manual profile selection.
7. Automatic profile detection.
8. Roller and component detection.
9. Physical roller catalog matching.
10. Batch processing and resumability.
11. Master database and metadata import.
12. Similarity fingerprints and assembly templates.
13. Historical transition database and quantitative benchmark tooling.
14. Optional local browser review interface after the CLI workflow is stable.

## Acceptance Criteria

The application is acceptable when:

1. The complete automated test suite passes.
2. The real DWG converts to a readable ASCII DXF or produces a precise conversion
   failure report.
3. The inspection report exists before classification results.
4. Every source entity is represented in SQLite or has a handle-specific parsing
   warning.
5. Station count is derived from evidence and no code path assumes 16 stations.
6. Every station has a database record and dynamic output directory.
7. Profiles and rollers are only claimed with recorded evidence and confidence.
8. Uncertain and unclassified geometry remains accessible in SQLite, DXF, and
   review artifacts.
9. All manifest-declared outputs validate and exported DXFs re-import.
10. Real-drawing previews are visually inspected for segmentation quality, with
    unresolved ambiguities reported rather than concealed.
11. Project and master databases keep roller catalog identities separate from
    drawing occurrences.
12. Batch processing is resumable and does not duplicate unchanged projects.
13. Original, normalized, and sampled geometry are stored separately.
14. Every calculated result has queryable provenance.
15. Accuracy reports compute all defined benchmark metrics and clearly mark
    provisional limits awaiting engineering approval.
