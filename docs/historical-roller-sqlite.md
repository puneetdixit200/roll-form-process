# Historical rollers for subsequence matches

Build the portable derived SQLite library from an organized evidence folder:

```sh
python scripts/build_historical_roller_library.py EVIDENCE_FOLDER DATASET_FOLDER/rollers.sqlite
```

The application discovers `rollers.sqlite` beside its configured `dataset.json`.
Alternatively set `ROLLFORM_HISTORICAL_ROLLER_SQLITE` to the database path.
The database stays local with the private dataset; it is not a source-code artifact.

Schema version 1 contains metadata, stages, and roller occurrences. Stages are
unique by flower ID and pass ID. Roller identities include the stage, so repeated
occurrence names in different flowers cannot collide. Each occurrence stores its
derived PNG and DXF as bytes, candidate role, source handles and completeness.
The original CAD drawing is not included. Existing inventory tables are unchanged.

The selected stage's **Top three historical matches and score components** shows
only the rollers for each match's exact flower ID and pass ID. The broader
subsequence cards also restrict their roller gallery to the selected generated
stage; a stage outside that interval shows no rollers. Change the station slider
to inspect another stage. Missing evidence never falls back to adjacent stages.
The PNGs and DXF downloads represent exact stored source occurrences, not a claim
that their use is correct for the generated target. Association confirmation is
preserved from extraction. Partial geometry remains explicitly labelled.

Unknown passes, absent rollers and an unavailable database have distinct states.
A different dataset hash blocks lookup. The content hash participates in the
generation cache key, so rebuilding changed evidence produces a new result.
Generate again after installing or updating the database; old runs are snapshots.

Builds use a temporary sibling file and atomic replacement after SQLite integrity
and foreign-key checks. Rebuilding is idempotent in semantic content. Back up the
previous derived database if its snapshot must be retained. Neither this database
nor a subsequence match assigns a physical asset or grants manufacturing approval.
