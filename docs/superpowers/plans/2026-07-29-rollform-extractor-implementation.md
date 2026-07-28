# Roll-Forming Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline, deterministic DWG/DXF extraction system that preserves exact CAD data, detects variable station layouts, segregates profiles and roller occurrences, supports cross-project physical roller identity, and produces auditable per-project and master databases.

**Architecture:** A staged pipeline converts and inspects drawings, persists a lossless entity ledger, classifies support/station/profile/roller geometry using recorded evidence, normalizes copies for comparison, and exports reviewable artifacts. Stage hashes make single and batch runs resumable; per-project SQLite databases remain audit records while a master database aggregates projects, fingerprints, assembly templates, and physical roller catalog links.

**Tech Stack:** Python 3.11+, ezdxf, Shapely, NumPy, SciPy, pandas, SQLAlchemy, Pillow, matplotlib, networkx, PyYAML, openpyxl, pytest.

## Global Constraints

- Never modify a source DWG or DXF.
- Source paths come only from CLI arguments or batch discovery.
- ODA File Converter is preferred, LibreDWG `dwg2dxf` is the fallback, and direct DXF input bypasses conversion.
- No fixed station count or assumed final station number is allowed.
- Never silently discard or confidently guess unclassified geometry.
- Original CAD primitives are authoritative; normalized primitives and sampled Shapely geometry are separate representations.
- Every calculated result records source handles, method, configuration hash, and confidence.
- Missing tooling or production metadata does not prevent profile extraction.
- Automatic physical roller matching starts only after station and profile extraction pass reliability gates.
- The initial review workflow is CLI, JSON, CSV, PNG, and HTML; the browser editor is a later milestone using the same override schema.
- Provisional dimensional accuracy limits require roll-forming engineer approval before becoming release gates.

---

## File Map

Core package files:

- `src/rollform_extractor/__init__.py`: package version.
- `src/rollform_extractor/__main__.py`: module entry point.
- `src/rollform_extractor/cli.py`: command definitions and exit-code mapping.
- `src/rollform_extractor/config.py`: YAML configuration loading, validation, snapshots, and stage subset hashes.
- `src/rollform_extractor/converter.py`: immutable input hashing, converter discovery, DWG conversion, and DXF staging.
- `src/rollform_extractor/dxf_reader.py`: drawing inspection and layout iteration.
- `src/rollform_extractor/entity_parser.py`: exact primitive serialization, block transforms, sampled geometry, and entity ledger creation.
- `src/rollform_extractor/models.py`: typed domain records and override schema.
- `src/rollform_extractor/support_classifier.py`: reversible support/noise classification.
- `src/rollform_extractor/station_detector.py`: text, block, spatial candidates, reconciliation, and ordering.
- `src/rollform_extractor/profile_detector.py`: manual and automatic profile candidate selection.
- `src/rollform_extractor/roller_detector.py`: roller occurrence, role, and assembly detection.
- `src/rollform_extractor/geometry_normalizer.py`: millimetre conversion, exact transforms, curve sampling, joining, and mirror handling.
- `src/rollform_extractor/feature_extractor.py`: engineering measurements, fingerprints, similarity metrics, and provenance.
- `src/rollform_extractor/database.py`: SQLAlchemy project schema, transactions, and persistence.
- `src/rollform_extractor/catalog.py`: physical roller catalog matching and assembly templates.
- `src/rollform_extractor/exporters.py`: DXF/JSON/CSV/manifest/HTML exports.
- `src/rollform_extractor/preview.py`: drawing and classification PNG rendering.
- `src/rollform_extractor/review.py`: review queue and override application.
- `src/rollform_extractor/pipeline.py`: staged project orchestration and cache invalidation.
- `src/rollform_extractor/batch.py`: batch ledger, resume, master aggregation, and reporting.
- `src/rollform_extractor/metadata_import.py`: CSV/XLSX production metadata import.
- `src/rollform_extractor/validation.py`: database, artifact, immutability, DXF, and benchmark validation.
- `src/rollform_extractor/benchmark.py`: gold-standard metrics and accuracy report.

Configuration and tests:

- `config/default.yaml`: all extraction tolerances.
- `tests/cad_factory.py`: synthetic DXF builders.
- `tests/test_*.py`: focused behavioral and integration tests.
- `pyproject.toml`, `requirements.txt`, `README.md`: packaging, dependencies, and operator documentation.

---

### Task 1: Package, Configuration, and Domain Contracts

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `config/default.yaml`
- Create: `src/rollform_extractor/__init__.py`
- Create: `src/rollform_extractor/__main__.py`
- Create: `src/rollform_extractor/config.py`
- Create: `src/rollform_extractor/models.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `ExtractionConfig.load(path: Path | None, overrides: dict | None) -> ExtractionConfig`
- Produces: `ExtractionConfig.snapshot() -> dict[str, Any]`
- Produces: `ExtractionConfig.hash_for(stage: str) -> str`
- Produces: immutable dataclasses `BBox`, `CadPrimitive`, `CadEntityRecord`, `StationRecord`, `ProfileRecord`, `RollerOccurrenceRecord`, `WarningRecord`, and `StageResult`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_default_configuration_has_engineering_tolerances():
    config = ExtractionConfig.load()
    assert config.geometry.endpoint_join_tolerance_mm == 0.05
    assert config.profiles.minimum_score_margin == 0.15

def test_stage_hash_changes_only_for_relevant_configuration(tmp_path):
    baseline = ExtractionConfig.load()
    changed = ExtractionConfig.load(overrides={"profiles": {"minimum_confidence": 0.8}})
    assert baseline.hash_for("profile_detection") != changed.hash_for("profile_detection")
    assert baseline.hash_for("conversion") == changed.hash_for("conversion")
```

- [ ] **Step 2: Run tests and verify missing-package failure**

Run: `pytest tests/test_config.py -q`

Expected: collection fails because `rollform_extractor.config` does not exist.

- [ ] **Step 3: Add packaging, dependencies, defaults, and typed models**

Implement strict YAML merging that rejects unknown keys. Serialize snapshots with
sorted keys and calculate SHA-256 stage hashes from explicit dependency maps:

```python
STAGE_CONFIG_KEYS = {
    "conversion": (),
    "parsing": ("geometry",),
    "station_detection": ("geometry", "stations"),
    "profile_detection": ("geometry", "profiles"),
    "roller_detection": ("geometry", "rollers"),
    "preview": ("geometry.curve_sampling_spacing_mm",),
}
```

The default YAML must contain the exact values approved in the design.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_config.py -q`

Expected: all configuration tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt config src/rollform_extractor tests/test_config.py
git commit -m "feat: establish extractor configuration and domain contracts"
```

---

### Task 2: Immutable Conversion and Drawing Inspection

**Files:**
- Create: `src/rollform_extractor/converter.py`
- Create: `src/rollform_extractor/dxf_reader.py`
- Create: `tests/test_converter.py`
- Create: `tests/test_dxf_reader.py`
- Create: `tests/cad_factory.py`

**Interfaces:**
- Consumes: `BBox`, `ExtractionConfig`
- Produces: `discover_converter() -> ConverterSpec | None`
- Produces: `stage_input(source: Path, destination: Path) -> ConversionResult`
- Produces: `inspect_drawing(dxf_path: Path) -> DrawingInspection`

- [ ] **Step 1: Write conversion failure and source immutability tests**

```python
def test_dwg_without_converter_fails_with_ascii_dxf_instructions(tmp_path, monkeypatch):
    source = tmp_path / "part.dwg"
    source.write_bytes(b"AC1027")
    monkeypatch.setattr(converter, "discover_converter", lambda: None)
    with pytest.raises(ConversionUnavailableError, match="AutoCAD 2013 or AutoCAD 2007 ASCII DXF"):
        converter.stage_input(source, tmp_path / "out")

def test_direct_dxf_is_staged_without_modifying_source(sample_dxf, tmp_path):
    before = sha256_file(sample_dxf)
    result = converter.stage_input(sample_dxf, tmp_path / "out")
    assert sha256_file(sample_dxf) == before
    assert ezdxf.readfile(result.converted_file)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_converter.py tests/test_dxf_reader.py -q`

Expected: imports fail because conversion and inspection modules do not exist.

- [ ] **Step 3: Implement converter discovery and ODA/LibreDWG adapters**

Use temporary input/output directories, validate output with `ezdxf.readfile`,
and hash the source before and after. ODA arguments target `AC1027`, `DXF`, and
ASCII output; retry `AC1021` only after a recorded first failure.

- [ ] **Step 4: Implement metadata inspection**

Inspect header variables, layouts, layers, linetypes, blocks, inserts, text,
dimensions, xrefs, extents, and available timestamps. Return JSON-safe domain
models without classifying geometry.

- [ ] **Step 5: Verify tests**

Run: `pytest tests/test_converter.py tests/test_dxf_reader.py -q`

Expected: direct DXF, missing converter, malformed DXF, layer, block, model-space,
paper-space, unit, and empty-layer tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/converter.py src/rollform_extractor/dxf_reader.py tests
git commit -m "feat: add immutable CAD conversion and inspection"
```

---

### Task 3: Lossless Entity Ledger and Nested Transform Matrices

**Files:**
- Create: `src/rollform_extractor/entity_parser.py`
- Create: `src/rollform_extractor/geometry_normalizer.py`
- Create: `tests/test_entity_parser.py`
- Create: `tests/test_geometry_normalizer.py`

**Interfaces:**
- Consumes: `DrawingInspection`, `CadPrimitive`, `CadEntityRecord`
- Produces: `parse_entities(doc: ezdxf.document.Drawing, config: ExtractionConfig) -> ParseResult`
- Produces: `normalize_primitives(primitives, transform, unit_factor, spacing) -> NormalizedGeometry`
- Produces: `compose_insert_matrix(insert, parent_matrix) -> numpy.ndarray`

- [ ] **Step 1: Write exact-primitive and transform tests**

```python
@pytest.mark.parametrize("entity_type", [
    "LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE",
    "SPLINE", "INSERT", "TEXT", "MTEXT", "DIMENSION", "HATCH", "POINT",
])
def test_supported_entity_retains_authoritative_primitive(entity_type, drawing_with_entity):
    parsed = parse_entities(drawing_with_entity(entity_type), ExtractionConfig.load())
    assert parsed.entities[0].original_primitive.kind == entity_type
    assert parsed.entities[0].original_dxf_attributes

def test_nested_insert_records_composed_mirror_rotation_and_scale(nested_block_doc):
    entity = parse_entities(nested_block_doc, ExtractionConfig.load()).expanded_entities[0]
    assert entity.transform.parent_block == "OUTER"
    assert np.asarray(entity.transform.matrix_4x4).shape == (4, 4)
    assert entity.transform.mirrored is True
```

- [ ] **Step 2: Run tests and verify missing implementation**

Run: `pytest tests/test_entity_parser.py tests/test_geometry_normalizer.py -q`

Expected: failures identify absent parser and transform functions.

- [ ] **Step 3: Implement entity serializers and block traversal**

Serialize each supported primitive without flattening curves. Recursively expand
inserts while retaining occurrence path, local coordinates, and composed 4x4
matrix. Catch per-handle failures into `WarningRecord`; keep unsupported entity
attributes in the ledger.

- [ ] **Step 4: Implement normalized and sampled representations**

Transform exact primitives into normalized CAD primitives. Sample comparison
points at configured spacing, join only comparison endpoints within tolerance,
and preserve independent original/normalized/sampled fields.

- [ ] **Step 5: Verify parser and round-trip invariants**

Run: `pytest tests/test_entity_parser.py tests/test_geometry_normalizer.py -q`

Expected: all primitive, nested transform, inch-to-mm, mirror, duplicate, and
broken-geometry tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/entity_parser.py src/rollform_extractor/geometry_normalizer.py tests
git commit -m "feat: preserve CAD primitives and nested transforms"
```

---

### Task 4: Project Database, Provenance, and Stage Ledger

**Files:**
- Create: `src/rollform_extractor/database.py`
- Create: `tests/test_database.py`

**Interfaces:**
- Consumes: all domain records from Tasks 1-3
- Produces: `create_project_database(path: Path) -> Engine`
- Produces: `persist_extraction(engine, ExtractionBundle) -> int`
- Produces: `record_stage(engine, project_id, StageResult) -> None`
- Produces: `foreign_key_violations(engine) -> list[tuple]`

- [ ] **Step 1: Write schema and foreign-key tests**

```python
def test_project_schema_contains_required_and_cross_project_tables(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    names = set(inspect(engine).get_table_names())
    assert REQUIRED_PROJECT_TABLES <= names
    assert {"roller_catalog", "roller_occurrences", "project_roll_usage",
            "processing_stages", "result_provenance"} <= names

def test_sqlite_foreign_keys_are_enforced(tmp_path):
    engine = create_project_database(tmp_path / "project.sqlite")
    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(Profile(station_id=999))
            session.commit()
```

- [ ] **Step 2: Run tests and verify schema failures**

Run: `pytest tests/test_database.py -q`

Expected: missing database API failures.

- [ ] **Step 3: Implement SQLAlchemy schema**

Create all requested project tables plus catalog, occurrence, usage, fingerprint,
assembly-template, project-code association, metadata, stage, and provenance
tables. Enable `PRAGMA foreign_keys=ON` through a connection event.

- [ ] **Step 4: Implement transactional persistence and stage history**

Store exact JSON primitives separately from normalized primitives and sampled
WKT/points. Failed extraction runs and stage failures retain diagnostic rows.

- [ ] **Step 5: Verify database tests**

Run: `pytest tests/test_database.py -q`

Expected: schema, cascade policy, foreign-key, run-history, configuration
snapshot, and provenance tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/database.py tests/test_database.py
git commit -m "feat: add auditable project database and stage history"
```

---

### Task 5: Full-Drawing Preview and Reversible Support Classification

**Files:**
- Create: `src/rollform_extractor/preview.py`
- Create: `src/rollform_extractor/support_classifier.py`
- Create: `tests/test_preview.py`
- Create: `tests/test_support_classifier.py`

**Interfaces:**
- Consumes: `ParseResult`, `DrawingInspection`
- Produces: `classify_support(entities, inspection, config) -> SupportClassification`
- Produces: `render_drawing_preview(entities, path, overlays=()) -> Path`

- [ ] **Step 1: Write nonblank preview and reversible support tests**

```python
def test_full_drawing_preview_contains_non_background_pixels(parsed_flower, tmp_path):
    image_path = render_drawing_preview(parsed_flower.entities, tmp_path / "drawing.png")
    image = np.asarray(Image.open(image_path).convert("RGB"))
    assert np.unique(image.reshape(-1, 3), axis=0).shape[0] > 4

def test_paperspace_and_dimensions_are_marked_not_removed(parsed_support_drawing):
    result = classify_support(parsed_support_drawing.entities,
                              parsed_support_drawing.inspection,
                              ExtractionConfig.load())
    assert len(result.entities) == len(parsed_support_drawing.entities)
    assert any(e.classification == "drawing_support" for e in result.entities)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_preview.py tests/test_support_classifier.py -q`

Expected: preview and support APIs are absent.

- [ ] **Step 3: Implement equal-aspect primitive rendering**

Render exact primitives, sampling curves only for display. Bound pixel size and
use content extents so extreme title-block coordinates cannot create empty plots.

- [ ] **Step 4: Implement evidence-based support marking**

Use layout, entity type, layer/block names, hidden state, line type, border
extent, and grid/text density. Store evidence and confidence on every mark.

- [ ] **Step 5: Verify focused tests**

Run: `pytest tests/test_preview.py tests/test_support_classifier.py -q`

Expected: title blocks, borders, notes, centre lines, construction lines, hidden
layers, dimensions, and paper-space tests pass without dropped entities.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/preview.py src/rollform_extractor/support_classifier.py tests
git commit -m "feat: render drawings and mark support geometry"
```

---

### Task 6: Manual Station Overrides Before Automatic Detection

**Files:**
- Create: `src/rollform_extractor/review.py`
- Create: `tests/test_review.py`

**Interfaces:**
- Consumes: parsed handles, `BBox`, configuration snapshot
- Produces: `load_overrides(path: Path, known_handles: set[str]) -> ManualOverrides`
- Produces: `apply_station_overrides(entities, overrides) -> list[StationRecord]`
- Produces: `write_review_queue(path, warnings, template) -> tuple[Path, Path]`

- [ ] **Step 1: Write override validation tests**

```python
def test_manual_station_boxes_define_variable_station_count(parsed_flower, tmp_path):
    overrides = write_overrides(tmp_path, station_boxes=[BOX_A, BOX_B, BOX_C])
    stations = apply_station_overrides(parsed_flower.entities,
                                        load_overrides(overrides, parsed_flower.handles))
    assert [station.sequence_index for station in stations] == [1, 2, 3]

def test_unknown_profile_handle_is_rejected(parsed_flower, tmp_path):
    path = write_overrides(tmp_path, profile_handles={"1": ["DOES_NOT_EXIST"]})
    with pytest.raises(OverrideValidationError, match="DOES_NOT_EXIST"):
        load_overrides(path, parsed_flower.handles)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_review.py -q`

Expected: missing review/override implementation.

- [ ] **Step 3: Implement schema-versioned override loading**

Validate units, count/order uniqueness, positive-area boxes, known handles,
nonconflicting ownership, roller roles, and station references. Generate JSON and
CSV queues without overwriting completed engineer decisions.

- [ ] **Step 4: Verify review tests**

Run: `pytest tests/test_review.py -q`

Expected: manual count/order/box/profile/roller/unit and invalid-override cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/rollform_extractor/review.py tests/test_review.py
git commit -m "feat: add validated manual review overrides"
```

---

### Task 7: Automatic Variable Station Detection

**Files:**
- Create: `src/rollform_extractor/station_detector.py`
- Create: `tests/test_station_detector.py`

**Interfaces:**
- Consumes: nonsupport `CadEntityRecord`, annotations, inserts, optional overrides
- Produces: `detect_stations(entities, inspection, config, overrides=None) -> StationDetectionResult`

- [ ] **Step 1: Write variable-count, unlabeled, block, and multi-row tests**

```python
@pytest.mark.parametrize("count", [8, 12, 15, 16, 18, 20])
def test_station_count_is_derived_from_labels_and_geometry(count):
    drawing = make_flower_dxf(station_count=count, labels=True)
    result = detect_stations(parse(drawing), inspect(drawing), config())
    assert len(result.stations) == count

def test_unlabelled_multirow_layout_uses_unknown_labels_and_review():
    drawing = make_flower_dxf(station_count=12, labels=False, rows=3)
    result = detect_stations(parse(drawing), inspect(drawing), config())
    assert len(result.stations) == 12
    assert all(s.drawing_label.startswith("Station_Unknown_") for s in result.stations)
    assert all(s.manual_review_required for s in result.stations)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_station_detector.py -q`

Expected: station detector API is absent.

- [ ] **Step 3: Implement candidate generators**

Implement station-label regex parsing, repeated block signatures, connected
components, adaptive spatial gaps, and candidate evidence records.

- [ ] **Step 4: Reconcile candidates and infer order**

Use a networkx overlap graph. Prefer consistent numeric labels; otherwise score
horizontal, vertical, reversed, and row-major arrangements. Mark conflicts and
shared geometry for review.

- [ ] **Step 5: Verify station tests**

Run: `pytest tests/test_station_detector.py -q`

Expected: all six variable counts, repeated blocks, absent labels, reversed,
vertical, and multi-row cases pass with confidence/review assertions.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/station_detector.py tests/test_station_detector.py
git commit -m "feat: detect variable station layouts"
```

---

### Task 8: Manual and Automatic Profile Extraction

**Files:**
- Create: `src/rollform_extractor/profile_detector.py`
- Create: `src/rollform_extractor/feature_extractor.py`
- Create: `tests/test_profile_detector.py`
- Create: `tests/test_feature_extractor.py`

**Interfaces:**
- Consumes: station-owned exact primitives, sampled geometry, optional profile-handle overrides
- Produces: `detect_profiles(stations, entities, config, overrides=None) -> ProfileDetectionResult`
- Produces: `extract_profile_features(profile, config_hash) -> ProfileFeatures`
- Produces: `fingerprint_profile(features, sampled_points, mirrored=False) -> GeometryFingerprint`

- [ ] **Step 1: Write manual selection and geometry-feature tests**

```python
def test_manual_profile_handles_take_precedence(station_with_two_contours):
    result = detect_profiles(*station_with_two_contours.data,
                             overrides=ManualOverrides(profile_handles={"1": ["A1", "A2"]}))
    assert result.profiles[0].source_handles == ("A1", "A2")
    assert result.profiles[0].method == "manual_override"

def test_arc_radius_and_developed_length_use_exact_primitives(profile_with_arc):
    features = extract_profile_features(profile_with_arc, "config-hash")
    assert features.bends[0].radius_mm == pytest.approx(3.0)
    assert features.developed_length_mm == pytest.approx(profile_with_arc.exact_length)
    assert features.provenance["developed_length_mm"].source_handles
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_profile_detector.py tests/test_feature_extractor.py -q`

Expected: absent detector and feature API failures.

- [ ] **Step 3: Implement connected-chain candidate generation and scoring**

Combine layer, colour, linetype, connectivity, long-chain, roller-relative,
developed-length, topology, and station-centre evidence. Require the configured
absolute confidence and score margin; send competing candidates to review.

- [ ] **Step 4: Implement exact feature extraction and fingerprints**

Calculate line/arc lengths from exact primitives, sample other curves
deterministically, identify bend sequence and radii, symmetry, bounding boxes,
centres, mirrored fingerprints, and per-value provenance.

- [ ] **Step 5: Verify profile tests**

Run: `pytest tests/test_profile_detector.py tests/test_feature_extractor.py -q`

Expected: profile-only, inches, mirror, broken contour, double boundary,
duplicate entity, ambiguity, and consecutive-length consistency cases pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/profile_detector.py src/rollform_extractor/feature_extractor.py tests
git commit -m "feat: extract exact profile geometry and features"
```

---

### Task 9: Roller Occurrences and Station Assemblies

**Files:**
- Create: `src/rollform_extractor/roller_detector.py`
- Create: `tests/test_roller_detector.py`

**Interfaces:**
- Consumes: stations, profiles, exact component primitives, annotations, overrides
- Produces: `detect_rollers(stations, profiles, entities, config, overrides=None) -> RollerDetectionResult`
- Produces: one `AssemblyRecord` per station and zero or more occurrence records

- [ ] **Step 1: Write separate-component and missing-tooling tests**

```python
def test_subrollers_remain_separate_and_receive_profile_relative_roles(profile_and_rolls):
    result = detect_rollers(*profile_and_rolls, config())
    assert len(result.rollers) == 4
    assert {roller.role for roller in result.rollers} == {
        "upper_left", "upper_right", "lower_left", "lower_right"
    }

def test_profile_only_station_still_creates_empty_assembly(profile_only_station):
    result = detect_rollers(*profile_only_station, config())
    assert len(result.assemblies) == 1
    assert result.assemblies[0].tooling_status == "unavailable"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_roller_detector.py -q`

Expected: roller detector API is absent.

- [ ] **Step 3: Implement connected component and rotational evidence**

Group connected primitives, detect concentric outer/bore circles, arcs,
rotational contours, shared shaft centres, identifiers, and annotations.

- [ ] **Step 4: Implement role classification and assemblies**

Assign upper/lower and left/centre/right relative to profile geometry. Preserve
guide, support, shaft, spacer, and ring candidates separately. Apply manual role
overrides and route weak roles or duplicate IDs to review.

- [ ] **Step 5: Verify roller tests**

Run: `pytest tests/test_roller_detector.py -q`

Expected: roles, IDs, bores, outer diameters, keyways, missing rollers, multiple
subrollers, ambiguity, override, and assembly count cases pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/roller_detector.py tests/test_roller_detector.py
git commit -m "feat: detect roller occurrences and assemblies"
```

---

### Task 10: Exports, Project Pipeline, CLI, and Validation

**Files:**
- Create: `src/rollform_extractor/exporters.py`
- Create: `src/rollform_extractor/pipeline.py`
- Create: `src/rollform_extractor/validation.py`
- Create: `src/rollform_extractor/cli.py`
- Create: `tests/test_exporters.py`
- Create: `tests/test_pipeline.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: all per-project stage outputs
- Produces: `extract_project(request: ExtractionRequest) -> ExtractionSummary`
- Produces: `export_project(bundle, output_root) -> Manifest`
- Produces: `validate_project(project_path: Path) -> ValidationReport`
- Produces: CLI commands `inspect`, `extract`, `review`, `reprocess`, `validate`

- [ ] **Step 1: Write end-to-end synthetic extraction test**

```python
def test_extract_creates_dynamic_station_tree_and_reimportable_dxfs(tmp_path):
    source = make_flower_dxf(tmp_path / "flower.dxf", station_count=8,
                             labels=True, rollers=True)
    summary = extract_project(ExtractionRequest(source, tmp_path / "output"))
    assert summary.station_count == 8
    assert not (summary.project_path / "stations" / "station_09").exists()
    for path in summary.manifest.dxf_files:
        ezdxf.readfile(path)
    assert validate_project(summary.project_path).valid
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_exporters.py tests/test_pipeline.py tests/test_cli.py tests/test_validation.py -q`

Expected: pipeline, CLI, exporter, and validator APIs are absent.

- [ ] **Step 3: Implement exact DXF/JSON/CSV/PNG/HTML exports**

Reconstruct from original primitives, not WKT. Generate the requested dynamic
tree, role files only when roles exist, classification previews, review files,
station summaries, warnings, report, and manifest with artifact hashes.

- [ ] **Step 4: Implement staged orchestration**

Persist inspection before classification. Record stage hashes and statuses.
Support `--stage profiles`, `--stage rollers`, and preview rebuild from the
database. Create new run history on reprocess.

- [ ] **Step 5: Implement validation and CLI exit codes**

Validate source hash, station uniqueness, units, geometry separation, files,
foreign keys, manifest agreement, confidence visibility, and DXF re-import.

- [ ] **Step 6: Verify end-to-end tests**

Run: `pytest tests/test_exporters.py tests/test_pipeline.py tests/test_cli.py tests/test_validation.py -q`

Expected: project extraction and all five initial CLI commands pass.

- [ ] **Step 7: Commit**

```bash
git add src/rollform_extractor tests
git commit -m "feat: export and validate complete project extractions"
```

---

### Task 11: Physical Roller Catalog and Assembly Templates

**Files:**
- Create: `src/rollform_extractor/catalog.py`
- Create: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `RollerOccurrenceRecord`, geometry fingerprints, factory catalog rows
- Produces: `match_occurrence(occurrence, catalog, thresholds) -> CatalogMatch`
- Produces: `detect_assembly_template(assembly, templates) -> TemplateMatch`

- [ ] **Step 1: Write conservative matching tests**

```python
def test_same_factory_id_links_occurrences_across_projects(catalog, occurrences):
    matches = [match_occurrence(item, catalog, thresholds()) for item in occurrences]
    assert matches[0].roller_catalog_id == matches[1].roller_catalog_id

def test_two_similar_catalog_candidates_require_manual_review(catalog_with_tie, occurrence):
    match = match_occurrence(occurrence, catalog_with_tie, thresholds())
    assert match.roller_catalog_id is None
    assert match.manual_review_required
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_catalog.py -q`

Expected: catalog API is absent.

- [ ] **Step 3: Implement identity hierarchy and fingerprint candidates**

Match permanent ID, unique drawing ID mapping, exact fingerprint, then similarity.
Never turn tied candidates into an automatic physical identity.

- [ ] **Step 4: Implement assembly-template signatures**

Hash ordered roles, positions, centres relative to profile, and catalog IDs when
known. Keep occurrence-specific annotations and provenance outside the template.

- [ ] **Step 5: Verify catalog tests**

Run: `pytest tests/test_catalog.py -q`

Expected: reuse, ambiguity, availability, condition, location, usage, and
template deduplication tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/catalog.py tests/test_catalog.py
git commit -m "feat: separate physical roller identity from occurrences"
```

---

### Task 12: Batch Processing, Resume, and Master Database

**Files:**
- Create: `src/rollform_extractor/batch.py`
- Create: `tests/test_batch.py`

**Interfaces:**
- Consumes: per-project pipeline, stage ledgers, project databases
- Produces: `batch_extract(request: BatchRequest) -> BatchSummary`
- Produces: `aggregate_master(output_root: Path) -> Path`
- Produces: CLI commands `batch-extract`, `batch-validate`, `batch-report`

- [ ] **Step 1: Write resume and aggregation tests**

```python
def test_batch_resume_skips_unchanged_successful_project(batch_fixture):
    first = batch_extract(batch_fixture.request)
    second = batch_extract(replace(batch_fixture.request, resume=True,
                                   skip_unchanged=True))
    assert second.projects_skipped == first.total_files
    assert second.projects_reprocessed == 0

def test_master_database_keeps_project_provenance(batch_fixture):
    summary = batch_extract(batch_fixture.request)
    master = sqlite3.connect(summary.master_database)
    rows = master.execute("select source_database, source_project_id from projects").fetchall()
    assert len(rows) == batch_fixture.project_count
    assert all(source and project_id for source, project_id in rows)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_batch.py -q`

Expected: batch APIs are absent.

- [ ] **Step 3: Implement isolated batch runner and incremental ledger**

Discover the CLI pattern, process files independently, persist statuses after
each file, resume failures, skip valid unchanged projects, and summarize exact
conversion/review/failure/station/profile/roller totals.

- [ ] **Step 4: Implement idempotent master aggregation**

Upsert by source hash, drawing ID, source database, run ID, and local key.
Aggregate catalog items, occurrences, usage, fingerprints, templates,
transitions, and duplicate-profile groups without duplicating unchanged runs.

- [ ] **Step 5: Implement batch CLI commands and dashboard**

Generate `master/master_rollform.sqlite`, `projects.csv`, `rollers.csv`, and
`extraction_dashboard.html`.

- [ ] **Step 6: Verify batch tests**

Run: `pytest tests/test_batch.py -q`

Expected: interrupted resume, changed config invalidation, per-project failure
isolation, master idempotency, and batch totals pass.

- [ ] **Step 7: Commit**

```bash
git add src/rollform_extractor/batch.py src/rollform_extractor/cli.py tests/test_batch.py
git commit -m "feat: add resumable batch extraction and master database"
```

---

### Task 13: Production Metadata Import and Project Code Resolution

**Files:**
- Create: `src/rollform_extractor/metadata_import.py`
- Create: `tests/test_metadata_import.py`

**Interfaces:**
- Consumes: CSV/XLSX path, project/master database
- Produces: `resolve_project_codes(filename: str) -> ProjectCodeResolution`
- Produces: `import_metadata(path: Path, engine: Engine) -> MetadataImportSummary`
- Produces: CLI command `import-metadata`

- [ ] **Step 1: Write filename and spreadsheet tests**

```python
def test_compound_drawing_name_resolves_related_project_codes():
    result = resolve_project_codes("D0064-D0065-FlowerSequence.dwg")
    assert result.drawing_id == "D0064-D0065-FlowerSequence"
    assert result.related_project_codes == ("D0064", "D0065")

def test_missing_material_values_remain_unknown_without_blocking_geometry(tmp_path, project_db):
    workbook = write_metadata_xlsx(tmp_path, material_grade=None, steel_thickness=None)
    summary = import_metadata(workbook, project_db)
    assert summary.imported == 1
    assert load_project(project_db).material_grade is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_metadata_import.py -q`

Expected: metadata import APIs are absent.

- [ ] **Step 3: Implement resolver and provenance-aware import**

Support all approved material, machine, production, customer, defect, notes, and
COPRA fields. Resolve explicit drawing IDs before related project codes; send
ambiguous or conflicting rows to review.

- [ ] **Step 4: Verify metadata tests**

Run: `pytest tests/test_metadata_import.py -q`

Expected: CSV, XLSX, missing values, compound code, unmatched row, conflict, and
source-row provenance cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/rollform_extractor/metadata_import.py src/rollform_extractor/cli.py tests/test_metadata_import.py
git commit -m "feat: import production metadata and resolve project codes"
```

---

### Task 14: Quantitative Benchmarking

**Files:**
- Create: `src/rollform_extractor/benchmark.py`
- Create: `tests/test_benchmark.py`
- Create: `benchmarks/README.md`
- Create: `benchmarks/schema.json`

**Interfaces:**
- Consumes: labelled truth JSON and extraction databases
- Produces: `evaluate_benchmark(truth, extraction) -> BenchmarkReport`
- Produces: station, profile, roller, and geometry accuracy metrics

- [ ] **Step 1: Write metric tests with known geometry**

```python
def test_identical_contours_have_zero_distance():
    metrics = contour_metrics([(0, 0), (1, 0)], [(0, 0), (1, 0)])
    assert metrics.hausdorff_mm == 0
    assert metrics.mean_contour_mm == 0

def test_benchmark_reports_false_automatic_claim_rate(labelled_case):
    report = evaluate_benchmark(labelled_case.truth, labelled_case.extraction)
    assert report.incorrect_automatic_claim_rate == pytest.approx(
        labelled_case.expected_false_claim_rate
    )
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_benchmark.py -q`

Expected: benchmark API is absent.

- [ ] **Step 3: Implement classification and geometry metrics**

Calculate station count accuracy, boundary IoU, profile identification,
roller-component recall, roller-role accuracy, false automatic claims,
Hausdorff/mean contour distance, developed-length error, bend position/angle,
and bend-radius error.

- [ ] **Step 4: Implement provisional target reporting**

Report pass/fail against the initial percentages and 0.20 mm, 0.10%, and 0.50 mm
limits, while visibly marking dimensional thresholds as provisional until an
engineer approval flag exists.

- [ ] **Step 5: Verify benchmark tests**

Run: `pytest tests/test_benchmark.py -q`

Expected: exact metric and threshold-status tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rollform_extractor/benchmark.py tests/test_benchmark.py benchmarks
git commit -m "feat: add labelled extraction benchmarks"
```

---

### Task 15: Documentation, Full Regression, and Real DWG Integration

**Files:**
- Create: `README.md`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Test: complete `tests/` suite

**Interfaces:**
- Consumes: all implemented commands
- Produces: reproducible operator instructions and first real extraction report

- [ ] **Step 1: Write CLI smoke test for documented commands**

```python
@pytest.mark.parametrize("command", [
    "inspect", "extract", "review", "reprocess", "validate",
    "batch-extract", "batch-validate", "batch-report", "import-metadata",
])
def test_documented_command_has_help(cli_runner, command):
    result = cli_runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run the complete suite before documentation**

Run: `pytest -q`

Expected: command-help test fails for any undocumented or missing command; all
completed implementation tests pass.

- [ ] **Step 3: Complete README and packaging**

Document installation, converter discovery, direct DXF operation, configuration,
all commands, output tree, database roles, review overrides, resumability,
metadata format, catalog identity rules, benchmark workflow, and exact no-converter
instructions.

- [ ] **Step 4: Run complete automated verification**

Run:

```bash
python -m pip install -e .
pytest -q
python -m rollform_extractor --help
```

Expected: installation succeeds, all tests pass, and CLI help lists every command.

- [ ] **Step 5: Run the supplied DWG through the complete pipeline**

Run:

```bash
python -m rollform_extractor inspect \
  '/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg'
python -m rollform_extractor extract \
  '/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg' \
  --output '/home/pd/rollform-extractor/output'
python -m rollform_extractor validate \
  '/home/pd/rollform-extractor/output/D0064-D0065-FlowerSequence'
```

Expected: ODA conversion creates a readable ASCII DXF, or the integration report
contains the exact converter error and stops without an extraction success claim.

- [ ] **Step 6: Inspect generated previews**

Open the full drawing, station boundary, profile, roller classification, and
unidentified previews. Compare station labels and boxes with the converted DXF.
Record segmentation ambiguities in the review queue and final report.

- [ ] **Step 7: Capture exact real-drawing results**

Query the database and manifest for units, layers, blocks, stations, labels,
profiles, roller occurrences, assemblies, unidentified entities, station
confidences, database path, DXF paths, HTML report, assumptions, and unresolved
ambiguities.

- [ ] **Step 8: Commit**

```bash
git add README.md pyproject.toml requirements.txt
git commit -m "docs: complete extractor operator workflow"
```

---

## Deferred Browser Review Milestone

The local browser editor starts only after Tasks 1-15 establish a stable override
schema and reliable station/profile extraction. It will read project SQLite and
preview tiles, display original and classified geometry, support draggable
station boxes and entity selection, and save the same `manual_overrides.json`
accepted by the CLI. It will not create a second source of classification truth.

## Plan Self-Review Checklist

- Every requirement in the approved design maps to a task above.
- Physical catalog identity is distinct from drawing occurrences and usage.
- Batch processing follows reliable station/profile extraction.
- Exact CAD primitives remain authoritative through export.
- Nested transform matrices are explicit and tested.
- Configuration, provenance, stage hashes, resume, and run history are tested.
- Source paths are arguments, never application constants.
- Browser review is explicitly deferred until the CLI override contract is stable.
- No automatic roller catalog matching occurs before extraction reliability gates.
- Real-DWG success requires conversion, extraction evidence, validation, and visual inspection.

