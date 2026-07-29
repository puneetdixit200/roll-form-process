# Rollform Extractor

Offline DWG/DXF extraction for roll-forming drawings. The tool stages source
CAD files without modifying them, converts DWG to DXF when a converter is
available, inspects CAD structure, extracts stations/profiles/rollers, writes
review artifacts, and validates the resulting project tree.

## Install

Use Python 3.11 or newer.

```bash
python -m pip install -e .
python -m rollform_extractor --help
rollform-extractor --help
```

Dependencies are declared in `pyproject.toml` and mirrored in
`requirements.txt` for simple environments.

## CAD Input

DXF files run directly and are copied into the project staging folder before
reading. DWG files require a converter:

1. ODA File Converter: discovered as `ODAFileConverter`,
   `ODAFileConverter.exe`, or `odafileconverter`.
2. LibreDWG: discovered as `dwg2dxf`.

ODA conversion is attempted as ASCII DXF `AC1027`, then `AC1021` after a
recorded first failure. If no converter is found, export the source drawing as
AutoCAD 2013 or AutoCAD 2007 ASCII DXF and run the extractor on that DXF file.

The extractor never edits the source DWG/DXF. Validation compares the source
hash in `manifest.json` against the current source file.

## Configuration

Defaults live in `config/default.yaml` and are also packaged under
`rollform_extractor/config/default.yaml`. Load-time overrides reject unknown
keys. Stage hashes are derived from only the configuration sections used by
that stage, so unrelated tolerance edits do not invalidate every stage.

## Commands

```bash
rollform-extractor inspect SOURCE
rollform-extractor extract SOURCE OUTPUT_ROOT
rollform-extractor review PROJECT_DIR
rollform-extractor reprocess PROJECT_DIR
rollform-extractor validate PROJECT_DIR
rollform-extractor batch-extract SOURCE_ROOT OUTPUT_ROOT [--resume] [--skip-unchanged]
rollform-extractor batch-validate OUTPUT_ROOT
rollform-extractor batch-report OUTPUT_ROOT
rollform-extractor import-metadata METADATA.csv [--master master.sqlite]
```

`inspect` prints JSON-safe drawing metadata. `extract` writes a project under
`OUTPUT_ROOT/SOURCE_STEM`. `review` prints the review queue path when one
exists. `reprocess` reruns extraction from the original source recorded in
`project.json`. `validate` checks manifests, hashes, exported DXFs, SQLite
foreign keys, units, and station folders. Batch commands discover `*.dxf` and
`*.dwg`, maintain `batch_ledger.json`, aggregate a master database, and write
an HTML dashboard.

## Output Tree

An extracted project contains:

```text
PROJECT/
  manifest.json
  project.json
  project.sqlite
  report.html
  previews/classification.png
  review/review_queue.json
  review/manual_overrides.json
  summaries/stations.csv
  stations/station_XX/profile.dxf
  stations/station_XX/rollers.csv
  stations/station_XX/top.dxf
  stations/station_XX/bottom.dxf
```

Only files that exist for the detected content are written. The manifest stores
file hashes and exported DXF paths.

## Databases

Each project has `project.sqlite`, the audit record for one drawing. It stores
projects, extraction runs, CAD entities, stations, profiles, roller
occurrences, warnings, stage results, and catalog-related tables.

Batch output has `master/master_rollform.sqlite`, built from successful project
databases. The master separates drawing roller occurrences from physical
catalog identity. Automatic physical roller matching should only be trusted
after station and profile extraction pass the project validation gates.

## Review Overrides

`review/review_queue.json` records warnings and unresolved items. Manual edits
belong in `review/manual_overrides.json` using the same schema:

```json
{
  "schema_version": 1,
  "source_hash": "...",
  "configuration_snapshot": {},
  "stations": [],
  "profile_handles": {},
  "roller_handles": {}
}
```

The CLI review workflow is JSON/CSV/PNG/HTML. A browser editor is intentionally
deferred and must write the same override schema.

## Metadata Import

`import-metadata` accepts CSV or XLSX rows keyed by `drawing_id`. Each extra
column is stored as project metadata in the master database. Missing drawing
IDs are reported as unmatched; conflicting existing values are reported as
conflicts.

Example CSV:

```csv
drawing_id,material_grade,customer
D0064-D0065-FlowerSequence,CR4,Example Customer
```

## Resumability

`batch-extract --resume --skip-unchanged` skips a source only when the previous
ledger entry succeeded, the source hash and configuration hash are unchanged,
and `validate` still passes for that project. Removed successful sources are
marked stale in the ledger.

## Benchmarks

Gold-standard benchmark fixtures are described in `benchmarks/README.md` and
validated against `benchmarks/schema.json`. Use benchmark output as an accuracy
report; provisional dimensional limits require roll-forming engineer approval
before becoming release gates.
