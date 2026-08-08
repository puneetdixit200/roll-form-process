# MASTER LOCAL EXECUTION PROMPT

## Constant Strip-Length Flower Prediction: Private Runtime Verification, UI Completion, and Final Commit

> Use this entire prompt on the user's laptop.
>
> The repository-side constant strip-length implementation is already committed on `feature/private-clrsg-training-evaluation`. Your job is to validate it against the real local private dataset and active private CLRSG model, finish the small browser presentation layer, fix any genuine defects discovered by execution, and commit only source/test/documentation changes.
>
> Do not commit private CAD, private corpus data, private model weights, private paths, screenshots containing proprietary geometry, or local databases.
>
> Do not merge or tag anything.

---

# 1. Objective

The Visual Flower Generator must treat strip centerline length as a hard visual-geometry invariant.

For every generated station:

```text
centerline_length(stage_i) ≈ centerline_length(final_target)
```

with maximum relative error:

```text
<= 1e-6
```

for the canonical generated geometry.

For open profiles, the implementation goes further: corresponding final-target material-coordinate segment lengths are preserved while the predicted segment directions change through the forming progression.

For closed contours, total perimeter is preserved. Do not pretend a closed contour can begin as an open flat strip without a topology change.

This is still a visual prototype constraint. It does not model:

- neutral-axis movement;
- bend allowance from thickness/material/K-factor;
- plastic strain;
- local stretching/compression;
- thinning;
- springback;
- roll force;
- tooling contact;
- machine settings;
- manufacturing feasibility.

Manufacturing approval remains:

```text
NOT_APPROVED
```

---

# 2. Existing implementation to preserve

Inspect these committed files before changing anything:

```text
src/rollform_extractor/strip_length_constraint.py
src/rollform_extractor/visual_flower_engine.py
src/rollform_extractor/clrsg_inference.py
src/rollform_extractor/visual_profile_schema.py
src/rollform_extractor/visual_flower_service.py
src/rollform_extractor/visual_flower_exports.py
frontend/src/features/visual-flower/types.ts
scripts/verify_constant_strip_length.py
tests/test_strip_length_constraint.py
tests/test_strip_length_exports.py
tests/test_strip_length_cache_version.py
docs/specs/constant-strip-length-constraint.md
docs/audits/constant-strip-length-implementation-audit.md
```

Important architecture already implemented:

```text
DETERMINISTIC CANDIDATE
legacy/intermediate visual prediction
        ↓
constant centerline-length projection
        ↓
visible/exported station
```

For learned inference:

```text
legacy unconstrained baseline used by CLRSG training
        ↓
existing CLRSG residual prediction
        ↓
raw corrected stage
        ↓
constant centerline-length projection
        ↓
visible/exported learned stage
```

This ordering is intentional.

The active private CLRSG model was trained against the old unconstrained baseline. Do not silently replace its residual reference with the new constrained deterministic baseline. The code reconstructs the legacy baseline specifically for residual application and constrains geometry only afterward.

Do not remove:

```text
residual_reference = LEGACY_UNCONSTRAINED_BASELINE_V1
post_prediction_constraint = constant_centerline_length_v1
```

unless a genuinely new model is trained and versioned later.

---

# 3. Known private model state before this change

The previously verified private model is:

```text
Model ID: clrsg-19c816e906b6e1f1
Privacy: PRIVATE_PROTOTYPE_MODEL
Approval: APPROVED_FOR_PRIVATE_PROTOTYPE
Activation: ACTIVE
Historical flowers: 2
Historical passes: 31
Private corpus samples: 200
Train / validation / test: 135 / 33 / 32
Test baseline RMS: 0.4859359
Test learned RMS: 0.1280796
Relative improvement: 73.64%
OOD true-positive rate: 100%
Validation false-rejection rate: 3.03%
Test fallback rate: 6.25%
```

These metrics were generated before the new output geometry constraint.

Do not overwrite them or claim they directly measure the constrained output.

The model weights and thresholds do not need retraining merely to enforce the output length invariant.

---

# 4. Git safety

Start with:

```bash
git status --short
git branch --show-current
git log -12 --oneline --decorate
git fetch origin
git switch feature/private-clrsg-training-evaluation
git pull --ff-only
```

If there are unrelated local changes, preserve them. Do not wipe them.

Forbidden:

```bash
git reset --hard
git clean -fd
git clean -fdx
git push --force
git push --force-with-lease
```

Do not merge or tag.

---

# 5. Confirm private environment

The existing local private environment should provide:

```text
ROLLFORM_FLOWER_PROTOTYPE_DATASET
ROLLFORM_SYNTHETIC_CORPUS_ROOT
ROLLFORM_MODEL_REGISTRY_ROOT
ROLLFORM_ACTIVE_CLRSG_MODEL
```

Check them without printing sensitive absolute values in logs intended for Git.

Useful shell check:

```bash
for name in \
  ROLLFORM_FLOWER_PROTOTYPE_DATASET \
  ROLLFORM_SYNTHETIC_CORPUS_ROOT \
  ROLLFORM_MODEL_REGISTRY_ROOT \
  ROLLFORM_ACTIVE_CLRSG_MODEL; do
  if [ -n "${!name:-}" ]; then
    echo "$name=CONFIGURED"
  else
    echo "$name=MISSING"
  fi
done
```

Do not echo the actual private paths into committed reports.

---

# 6. Install and compile

Run:

```bash
python -m pip install -e ".[backend,test]"
python -m compileall src scripts
```

Any syntax/import failure must be fixed before proceeding.

Do not work around failures with `|| true`.

---

# 7. Focused constant-length tests

Run first:

```bash
pytest -q \
  tests/test_strip_length_constraint.py \
  tests/test_strip_length_exports.py \
  tests/test_strip_length_cache_version.py
```

Required result:

```text
ALL PASS
```

These tests must prove:

1. Open-path centerline length equals final target length.
2. Open-path target segment lengths remain locally preserved.
3. 8-stage deterministic generation satisfies the invariant.
4. 16-stage deterministic generation satisfies the invariant.
5. 28-stage deterministic generation satisfies the invariant.
6. Closed-contour perimeter is constant.
7. Closed progression does not collapse into an identical final profile at every station.
8. Learned candidates are projected after residual application.
9. CLRSG still uses `LEGACY_UNCONSTRAINED_BASELINE_V1` as its residual reference.
10. Export JSON/CSV/HTML/ZIP evidence contains the strip-length invariant.
11. Persisted run cache configuration is versioned by the new algorithm and constraint version.

Do not loosen `1e-6` merely to make a test green.

---

# 8. Full regression suite

Run:

```bash
pytest -q
```

Record the final count.

The previous Phase 21 baseline was:

```text
268 Python tests passed
```

The new count should be higher because new tests were added.

Then run frontend validation:

```bash
cd frontend
npm ci
npm test -- --run
npm run build
cd ..
```

All existing Phase 15–21 behavior must remain intact.

---

# 9. Verify the active private model still loads

Run:

```bash
python scripts/run_phase20_private_clrsg.py status "$ROLLFORM_ACTIVE_CLRSG_MODEL"
```

Required:

```text
model_id = clrsg-19c816e906b6e1f1
approval = APPROVED_FOR_PRIVATE_PROTOTYPE
activation = ACTIVE
artifact health = valid
private paths redacted = true
```

If artifact verification fails, stop and diagnose it.

Do not regenerate hashes merely to hide an unexpected file change.

Do not retrain automatically.

---

# 10. Verify deterministic candidates with the real historical dataset

Use the actual private historical dataset only locally.

Generate supported open-profile targets at:

```text
8 stations
16 stations
28 stations
```

For every deterministic candidate and every pass verify:

```text
generation.strip_length_constraint.enabled == true
generation.strip_length_constraint.satisfied == true
abs(actual_length - target_length) / target_length <= 1e-6
```

At candidate level verify:

```text
geometry_constraints.enabled == true
geometry_constraints.satisfied == true
geometry_constraints.maximum_relative_error <= 1e-6
```

For open paths also verify:

```text
open_path_local_segment_lengths_preserved == true
```

The first station should become a flat strip whose total centerline length equals the final profile centerline length.

Do not confuse horizontal span with strip length. A bent strip can have a smaller projected width while retaining identical centerline length.

---

# 11. Verify learned candidates with the active private CLRSG

Use:

```text
generation_engine = COMPARE_ALL
```

Test at least:

```text
8 stations
16 stations
28 stations
```

For supported profiles verify all of:

```text
DETERMINISTIC_BASELINE exists
CLRSG_LEARNED_MEAN exists where model support allows it
CLRSG_CONSERVATIVE_BLEND exists where model support allows it
```

For every learned pass:

```text
residual_reference == LEGACY_UNCONSTRAINED_BASELINE_V1
post_prediction_constraint == constant_centerline_length_v1
strip_length_constraint.satisfied == true
```

Verify final target geometry remains exact.

Verify there are no NaN or infinite coordinates.

Verify point ordering and topology remain stable.

Verify OOD fallback still works.

Do not interpret a fallback as a failure when the profile is genuinely unsupported.

---

# 12. Private runtime compatibility diagnostic

The existing model quality metrics were measured before the new output projection. Therefore add a local, redacted runtime compatibility diagnostic.

Do not retrain.

Use supported private-derived validation/test targets already available in the local corpus and measure:

```text
projection RMS per station
maximum projection RMS
mean projection RMS
length relative error
fallback state
OOD state
final-target exactness
```

Produce a local-only detailed JSON report outside Git.

Commit only an aggregate redacted summary containing no geometry and no private paths.

Suggested aggregate fields:

```text
sample_count
station_counts_tested
all_length_constraints_satisfied
maximum_length_relative_error
mean_projection_rms
p95_projection_rms
maximum_projection_rms
learned_candidate_available_rate
fallback_rate
final_target_exact_rate
non_finite_count
topology_failure_count
```

Do not call projection RMS a manufacturing error.

---

# 13. Browser UI completion

The backend and TypeScript types already expose constraint metadata, but the browser should visibly show it.

Update the existing Visual Flower Generator without redesigning the entire workspace.

For each candidate card show a compact status such as:

```text
Strip length: LOCKED
Target centerline: 4.2381 visual units
Max error: 0.000003%
```

Use canonical visual units unless confirmed physical units are available.

Do not label the number as millimetres merely because a CAD file happened to come from a drawing. Unit confirmation belongs to the existing engineering review system.

For the currently selected station show:

```text
Current centerline length
Target centerline length
Relative error
Constraint method
```

For open paths optionally show:

```text
Material-coordinate segment lengths: PRESERVED
```

For closed paths show:

```text
Perimeter: PRESERVED
Local segment-length preservation: NOT CLAIMED
```

Add a small explanation:

```text
Centerline strip length is constrained to the final target at every generated stage.
This is a visual geometry constraint, not a neutral-axis, strain, or manufacturing calculation.
```

The constraint should be automatic. Do not add a normal user toggle that disables it.

If a debug/developer bypass is absolutely necessary, keep it backend-test-only and off by default.

---

# 14. Frontend tests

Add/update tests to verify:

1. `Strip length: LOCKED` appears for a constrained candidate.
2. Target length is displayed.
3. Relative error is displayed.
4. Learned candidate displays the same constraint status.
5. Closed candidate does not claim local segment-length preservation.
6. Missing constraint metadata degrades gracefully to `Unknown`, not a crash.
7. Existing generation/import/playback/export controls still work.

Then rerun:

```bash
cd frontend
npm test -- --run
npm run build
cd ..
```

---

# 15. Extend the one-command demo verifier

Update:

```text
scripts/run_visual_flower_demo.py
```

The `verify` command must now check constant strip length on the generated public-safe smoke case.

Required checks:

```text
constant_strip_length_metadata = true
constant_strip_length_all_passes = true
constant_strip_length_max_relative_error <= 1e-6
final_target_anchoring = true
```

Keep existing checks for:

```text
backend health
frontend HTTP 200
active model doctor
model status
16-stage generation
OOD fallback
JSON export
ZIP export
```

Do not expose private paths in output.

---

# 16. Start the real application

Run:

```bash
python scripts/run_visual_flower_demo.py doctor
python scripts/run_visual_flower_demo.py start
python scripts/run_visual_flower_demo.py status
python scripts/run_visual_flower_demo.py verify
```

Open:

```text
http://127.0.0.1:5173/
```

Use the normal Visual Flower Generator.

Test:

1. Public example profile.
2. One browser-drawn open profile.
3. One real/private-supported profile if available without exposing it externally.
4. One OOD/high-frequency profile.

For the supported profile:

```text
COMPARE_ALL
16 stations
```

Visually inspect animation.

The strip should bend while retaining length. It should not visibly shrink toward the center as it forms.

Check the browser console and network panel for errors.

---

# 17. Export and independent verification

Generate a ZIP/JSON export from a 16-station run.

Locate `visual_run.json` from the local export directory and run:

```bash
python scripts/verify_constant_strip_length.py /path/to/visual_run.json
```

Required:

```text
status = PASS
```

For every candidate:

```text
maximum_relative_error <= 1e-6
```

Then inspect:

```text
passes.csv
report.html
manifest.json
```

They must contain strip-length evidence.

DXF/SVG/PNG geometry must use the constrained pass coordinates.

No private source CAD should appear in the export package.

---

# 18. Cache-version regression

This change bumped the visual generation algorithm to:

```text
visual_sketch_history_match_v2_constant_length
```

and the constraint version to:

```text
constant_centerline_length_v1
```

Generate a target/preferences combination that had been generated before the update.

Confirm the service creates/uses a new run key and does not return an old persisted unconstrained result.

Do not delete old runs merely to make this test pass.

Historical runs should remain historical evidence.

---

# 19. Performance regression check

Run the existing benchmark:

```bash
python scripts/benchmark_visual_flower.py
```

Record timings for:

```text
8 stations
16 stations
28 stations
```

The length projection is O(stations × points) and should add modest overhead.

Previous Phase 21 local measurements were approximately:

```text
8-stage:  0.71 s
16-stage: 2.79 s
28-stage: 8.17 s
```

These were already WARN for the preferred 16/28-stage targets.

Do not fail the new feature solely because of small machine-to-machine timing variation, but investigate a major regression such as >20% repeatedly on the same machine.

Optimize only after correctness is proven.

---

# 20. Do not retrain unless genuinely necessary

Default action:

```text
KEEP EXISTING PRIVATE CLRSG MODEL
```

Retraining is not required to impose this output constraint because the implementation preserves the model's legacy residual reference and projects only after prediction.

Only consider a new model version if runtime evidence shows that post-projection geometry systematically destroys useful learned progression.

If that happens:

1. Do not overwrite the existing approved model.
2. Keep `clrsg-19c816e906b6e1f1` available as the historical v1 model.
3. Create a new algorithm/model version.
4. Generate constrained-baseline training data separately.
5. Train to a new artifact directory.
6. Re-run all approval gates.
7. Do not lower OOD thresholds or quality gates merely to activate it.

Do not perform this retraining unless the compatibility diagnostic proves it is needed.

---

# 21. Safety checks

Confirm:

```text
private CAD committed: NO
private corpus committed: NO
private model weights committed: NO
private absolute paths committed: NO
manufacturing approval: NOT_APPROVED
physical roller availability: NOT_DETERMINED
```

The constant centerline length must never be described as proof of material inextensibility in real forming.

Real sheet metal bending can involve neutral-axis effects, longitudinal strain, local stretching, compression, thinning, and springback.

The prototype merely imposes a useful geometry invariant for flower visualization.

---

# 22. Final full verification

Run again after all source/UI fixes:

```bash
python -m compileall src scripts
pytest -q
cd frontend
npm test -- --run
npm run build
cd ..
python scripts/run_visual_flower_demo.py doctor
python scripts/run_visual_flower_demo.py verify
```

Then:

```bash
git status --short
git diff --check
git diff --stat
git diff
```

Review every changed file.

Do not commit generated private data or local runtime files.

---

# 23. Commit policy

If local execution reveals source defects or the UI/demo-verifier work is completed, commit those source changes on:

```text
feature/private-clrsg-training-evaluation
```

Use clear commits, for example:

```text
feat: surface constant strip length in visual flower UI
test: verify constant-length private runtime compatibility
docs: record constant-length local validation
```

Do not merge or tag.

Do not commit the private model artifact after reevaluation.

---

# 24. Required final report

Return exactly enough evidence to judge the change:

```text
Branch
Starting commit
Final commit(s)
Working tree

Focused strip-length tests
Full Python tests
Frontend tests
Frontend build
Demo doctor
Demo verify
Browser verification

Active private model ID
Approval status
Activation status
Artifact health

Deterministic 8-stage invariant
Deterministic 16-stage invariant
Deterministic 28-stage invariant
Learned 8-stage invariant
Learned 16-stage invariant
Learned 28-stage invariant
Maximum relative length error
Final target exactness
Non-finite geometry count
Topology failure count

Private runtime compatibility sample count
Mean projection RMS
P95 projection RMS
Maximum projection RMS
Learned candidate availability rate
Fallback rate
OOD fallback result

Cache-version regression
Export verifier
CSV strip-length evidence
HTML strip-length evidence
DXF/SVG/PNG constrained geometry

Performance 8
Performance 16
Performance 28

Private CAD committed: NO
Private corpus committed: NO
Private weights committed: NO
Private paths committed: NO

CONSTANT STRIP LENGTH:
PASS or FAIL

PRIVATE CLRSG COMPATIBILITY:
PASS or FAIL

CUSTOMER VISUAL PROTOTYPE:
READY or NOT READY

MANUFACTURING APPROVAL:
NOT APPROVED

PHYSICAL ROLLER AVAILABILITY:
NOT DETERMINED

Known limitations
```

Do not merge or tag.

---

# 25. Final success condition

The change is complete when a user can generate a flower such that:

```text
flat/early stage centerline length
    = intermediate stage centerline length
    = final profile centerline length
```

within the committed numerical tolerance, for deterministic and learned candidates, while the active private CLRSG remains operational and OOD fallback remains intact.

The visible geometry may become narrower or taller as it bends. That is expected. The centerline arc length, not horizontal width, is the invariant.

That is the target.
