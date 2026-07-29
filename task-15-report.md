# Task 15 Report

## Automated Verification

Commands run from `/home/pd/rollform-extractor/.worktrees/implementation`:

```text
python -m pip install -e .
```

Result: exit 0. Editable install succeeded. Pip warned that
`/home/pd/.local/share/mise/installs/python/3.12.13/bin` is not on `PATH`.

```text
pytest -q
```

Final result after CLI fixes: `171 passed in 41.75s`.

```text
python -m rollform_extractor --help
```

Result: exit 0. Help listed:
`inspect`, `extract`, `review`, `reprocess`, `validate`, `batch-extract`,
`batch-validate`, `batch-report`, and `import-metadata`.

## Real DWG Input

Source:
`/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg`

Source SHA-256:
`dfc0f5fca3c95fecc879ef378be62f32a7b69f68861a598e34646382a71eabae`

Converter discovery:

```text
which ODAFileConverter
/usr/local/bin/ODAFileConverter

which dwg2dxf
which: no dwg2dxf in (...)
```

## Real DWG Commands

```text
python -m rollform_extractor inspect '/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg'
```

Result: exit 2.

```text
No DWG converter found. Export the drawing as AutoCAD 2013 or AutoCAD 2007 ASCII DXF, then run the extractor on that DXF file. Converter detail: Authorization required, but no authorization protocol specified

/usr/local/bin/ODAFileConverter: line 2: 2719640 Aborted                    (core dumped) LD_LIBRARY_PATH=/opt/oda-file-converter /opt/oda-file-converter/oda-file-converter $@; Authorization required, but no authorization protocol specified

/usr/local/bin/ODAFileConverter: line 2: 2719940 Aborted                    (core dumped) LD_LIBRARY_PATH=/opt/oda-file-converter /opt/oda-file-converter/oda-file-converter $@
```

```text
python -m rollform_extractor extract '/home/pd/Downloads/D0064-D0065-FlowerSequence.dwg' --output '/home/pd/rollform-extractor/output'
```

Result: exit 2.

```text
No DWG converter found. Export the drawing as AutoCAD 2013 or AutoCAD 2007 ASCII DXF, then run the extractor on that DXF file. Converter detail: Authorization required, but no authorization protocol specified

/usr/local/bin/ODAFileConverter: line 2: 2832460 Aborted                    (core dumped) LD_LIBRARY_PATH=/opt/oda-file-converter /opt/oda-file-converter/oda-file-converter $@; Authorization required, but no authorization protocol specified

/usr/local/bin/ODAFileConverter: line 2: 2832660 Aborted                    (core dumped) LD_LIBRARY_PATH=/opt/oda-file-converter /opt/oda-file-converter/oda-file-converter $@
```

```text
python -m rollform_extractor validate '/home/pd/rollform-extractor/output/D0064-D0065-FlowerSequence'
```

Result: exit 1.

```text
missing_manifest: manifest.json is missing
```

## Real DWG Extraction Results

No extraction success is claimed. ODA File Converter is present, but in this
non-graphical session it aborts before producing DXF output. LibreDWG `dwg2dxf`
is not installed.

Because conversion failed, there is no readable converted DXF, manifest,
project JSON, project SQLite database, HTML report, station CSV, exported
station DXF, preview PNG, review queue, station count, profile count, roller
occurrence count, assembly count, unidentified entity count, station confidence,
or segmentation ambiguity to inspect.

The only output paths created by the failed extraction were empty directories:

```text
/home/pd/rollform-extractor/output
/home/pd/rollform-extractor/output/D0064-D0065-FlowerSequence
/home/pd/rollform-extractor/output/D0064-D0065-FlowerSequence/source
```

## Fixes Made During Task 15

- `inspect` now stages/converts input before calling the DXF reader, so DWG
  inspection reaches the converter path instead of crashing in `ezdxf`.
- `extract` accepts the documented `--output` option while preserving the
  existing positional output argument.
- `extract` reports converter/runtime failures with exit code 2 and stderr
  instead of a traceback.
- CLI smoke tests now cover documented command help, DWG staging for `inspect`,
  documented `--output`, and conversion failure reporting.

## Review Fix

Review issue: missing source files on `extract` raised an `OSError` traceback.

Regression command:

```text
python -m rollform_extractor extract /tmp/no-such.dwg --output /tmp/out
```

Result after fix: exit 2.

```text
[Errno 2] No such file or directory: '/tmp/no-such.dwg'
```

Additional verification:

```text
pytest tests/test_cli.py -q
9 passed in 4.45s

pytest -q
172 passed in 45.95s
```
