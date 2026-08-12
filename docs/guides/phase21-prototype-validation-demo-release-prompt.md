# MASTER IMPLEMENTATION PROMPT

## Phase 21: Golden Validation Suite, One-Click Demo Release, and Engineer Feedback Capture

> Use this entire prompt as the implementation specification.
>
> Work in the existing repository. Preserve all prior phases and the approved private model workflow. Complete the implementation, tests, documentation, evidence, commit, push, and pull request. Do not merge or tag unless explicitly instructed.
>
> This phase does not train a new model by default. The private CLRSG model is already approved and active. The objective is to prove the whole prototype is stable, repeatable, understandable, and easy to demonstrate.

---

# 0. Role

You are the principal engineer responsible for turning an approved private visual flower-sequence prototype into a reliable local demonstration release.

You own:

- Backend reliability
- Frontend workflow quality
- Model integration
- Golden validation data
- Browser end-to-end testing
- Export verification
- Engineer feedback capture
- Performance benchmarking
- Privacy protection
- One-command local startup
- Release evidence
- Git safety

Do not build another model merely to create activity.

Do not alter model approval thresholds unless a reproducible defect is found.

Do not remove deterministic fallback.

Do not claim manufacturing, tooling, production, or physical roller approval.

---

# 1. Repository and current state

Repository:

```text
https://github.com/puneetdixit200/roll-form-process
```

Create Phase 21 from the latest head of:

```text
feature/private-clrsg-training-evaluation
```

Suggested branch:

```text
feature/phase21-prototype-validation-demo-release
```

If the Phase 20 branch is already merged, branch from the latest `main` that contains it.

Inspect before editing:

```bash
git status --short
git branch --show-current
git log -20 --oneline --decorate
git fetch origin
gh pr view 6
gh pr view 7
gh pr view 8
gh pr view 9
```

Known approved private-model evidence:

```text
Model ID: clrsg-19c816e906b6e1f1
Privacy classification: PRIVATE_PROTOTYPE_MODEL
Approval: APPROVED_FOR_PRIVATE_PROTOTYPE
Activation: ACTIVE
Historical seed flowers: 2
Historical passes: 31
Private-derived corpus: 200 accepted samples
Train / validation / test: 135 / 33 / 32
Test baseline RMS: 0.4859359
Test learned RMS: 0.1280796
Relative improvement: 73.64%
OOD true-positive rate: 100%
Validation false-rejection rate: 3.03%
Test fallback rate: 6.25%
```

The model artifact remains local and must not be committed.

---

# 2. Product objective

Build a dependable prototype release that an engineer can start and use without manually coordinating several terminals or interpreting raw JSON.

The completed workflow must support:

1. One-command local startup.
2. Preflight validation of:
   - Python environment
   - Frontend dependencies
   - Private historical dataset
   - Active private model
   - Model approval and artifact hashes
   - Writable local output directories
   - Backend and frontend ports
3. Browser-based drawing or direct DXF/DWG import.
4. Exact, range, and automatic 8–28 station generation.
5. Deterministic, learned-mean, and conservative-blend comparison.
6. OOD fallback and visible reasons.
7. Historical match overlays and confidence explanations.
8. Reliable DXF, SVG, PNG, JSON, CSV, HTML, and ZIP exports.
9. Golden-profile regression tests.
10. Engineer review capture without automatic retraining.
11. A self-contained readiness report.
12. A short repeatable demo script.

---

# 3. Permanent safety boundary

Every relevant screen and report must preserve:

```text
Visual geometry prototype only.
Not manufacturing approval.
Not tooling approval.
Not physical roller selection.
```

The system may be approved for:

```text
PRIVATE VISUAL PROTOTYPE INFERENCE
```

It must never imply:

```text
manufacturing feasibility
successful forming probability
machine compatibility
roller availability
tooling recommendation
production release
```

---

# 4. Git and preservation rules

Do not use:

```bash
git reset --hard
git clean -fd
git clean -fdx
git push --force
git push --force-with-lease
```

Do not:

- Delete old tests
- Drop database tables
- Rewrite migrations
- Remove old APIs
- Remove old CLI commands
- Remove deterministic generation
- Commit private CAD
- Commit private corpus shards
- Commit private model weights
- Commit local absolute paths
- Merge or tag without permission

Create:

```text
docs/audits/pre-phase21-demo-release-audit.md
docs/audits/pre-phase21-demo-release-audit.json
docs/audits/post-phase21-demo-release-audit.md
docs/audits/post-phase21-demo-release-audit.json
```

---

# 5. One-command local launcher

Add:

```text
scripts/run_visual_flower_demo.py
```

or an equivalent repository-consistent launcher.

Supported commands:

```bash
python scripts/run_visual_flower_demo.py doctor
python scripts/run_visual_flower_demo.py start
python scripts/run_visual_flower_demo.py stop
python scripts/run_visual_flower_demo.py status
python scripts/run_visual_flower_demo.py verify
```

## 5.1 Doctor

Check:

```text
repository root
Python version
editable package import
Node and npm
frontend node_modules
private dataset environment
active model environment
model approval
artifact hashes
backend port availability
frontend port availability
output directory writability
privacy path rules
```

Return a redacted JSON summary.

Never print private absolute paths.

Use statuses:

```text
PASS
WARN
FAIL
```

## 5.2 Start

Start backend and frontend in host development mode.

Requirements:

- Export or preserve required environment variables.
- Write PID files outside Git.
- Stream concise logs.
- Wait for backend health.
- Wait for frontend HTTP 200.
- Print:
  ```text
  Frontend: http://127.0.0.1:5173/
  Backend: http://127.0.0.1:8000/
  Active model: <redacted model ID>
  ```
- Fail clearly if startup fails.
- Do not leave orphan processes after partial failure.

Docker may remain optional.

Host development mode must be first-class because captive portals and package mirrors are apparently allowed to participate in software architecture.

## 5.3 Stop

Terminate only processes started by this launcher.

Do not kill unrelated Python, Node, Vite, or Uvicorn processes.

## 5.4 Status

Show:

```text
backend running
frontend running
health endpoint
active model
artifact health
approval status
deterministic fallback
PID state
```

## 5.5 Verify

Run the complete public-safe smoke workflow:

```text
backend health
frontend HTTP 200
model-status endpoint
public example target creation
16-station COMPARE_ALL generation
candidate count
final target anchoring
OOD fallback probe
JSON export
ZIP export
```

---

# 6. Golden profile suite

Create a committed public-safe suite:

```text
tests/fixtures/visual_flower_golden/
```

Use only independent public procedural profiles.

Include at least:

```text
OPEN_U_CHANNEL
OPEN_C_CHANNEL
OPEN_Z_PROFILE
OPEN_HAT_PROFILE
OPEN_STEP_PROFILE
OPEN_ASYMMETRIC_CHANNEL
OPEN_CURVED_WAVE
OPEN_MIXED_LINE_ARC
CLOSED_ROUNDED_RECTANGLE
CLOSED_ASYMMETRIC_LOOP
```

For every family include:

- Small variant
- Medium variant
- Large visual deformation variant
- At least one 8-station case
- At least one 16-station case
- At least one 28-station case

Target at least:

```text
30 supported golden cases
10 negative OOD cases
```

Every fixture must contain:

```text
fixture ID
family
profile JSON
requested station count
expected topology
expected engine availability
expected OOD class or allowed classes
expected fallback behavior
export expectations
```

Do not derive public fixture coordinates from private flowers.

---

# 7. Golden-result policy

Do not snapshot every floating-point coordinate blindly.

Golden assertions should cover stable properties:

```text
candidate types
candidate count
station count
final-target equality
topology
finite coordinates
no unexpected self-intersection
OOD status
fallback behavior
confidence range
historical match presence
export availability
deterministic hashes after rounded canonicalization
```

Use tolerances for geometry.

Use versioned hashes only where determinism is intentionally guaranteed.

When an algorithm version changes, require an explicit fixture migration report rather than silently updating snapshots.

---

# 8. Active model health API

The model-status API must report, without private paths:

```text
model ID
algorithm version
privacy classification
approval status
activation status
artifact health
station range
supported topology
test relative improvement
OOD true-positive rate
validation false-rejection rate
fallback rate
deterministic fallback availability
production approval boundary
```

Add:

```text
GET /api/visual-flower/model/doctor
```

Response:

```json
{
  "status": "READY",
  "checks": {},
  "model": {},
  "deterministic_fallback": true,
  "private_paths_redacted": true,
  "production_approval": "NOT_APPROVED"
}
```

Invalid active model behavior:

- API remains available.
- Deterministic generation remains available.
- Learned generation reports a stable error code.
- No local path or raw exception is returned.

---

# 9. Frontend release status

Improve the Visual Flower Generator status area.

Show:

```text
Private learned model: ACTIVE
Artifact health: VERIFIED
Approval: PRIVATE PROTOTYPE
Deterministic fallback: AVAILABLE
Manufacturing approval: NOT APPROVED
```

Display aggregate evaluation:

```text
73.64% held-out synthetic-derived improvement
100% negative OOD detection
3.03% validation false rejection
6.25% fallback
```

Use wording that makes the evidence boundary obvious.

Do not label the metrics “accuracy.”

When the model is invalid or absent:

```text
Learned model unavailable.
Deterministic generation remains available.
```

---

# 10. Guided demo mode

Add a toggle:

```text
Guided Demo
```

The guided flow should present:

## Step 1: Target

- Load a public example
- Draw a profile
- Import DXF/DWG

## Step 2: Generate

Recommended default:

```text
Generation engine: COMPARE_ALL
Station count: 16
Candidates: 3
```

## Step 3: Review

Show:

- Candidate cards
- Animation
- Historical overlay
- Learned correction
- OOD status
- Confidence breakdown
- Export buttons

Provide a visible reset button.

The normal expert workspace must remain available.

---

# 11. Engineer feedback capture

Add local feedback storage.

Suggested table:

```text
visual_flower_candidate_reviews
```

Fields:

```text
review_id
candidate_id
run_id
candidate_type
decision
reason_codes
reviewer
notes
created_at
model_id
algorithm_version
target_hash
```

Decisions:

```text
ACCEPT_VISUAL_SEQUENCE
REJECT_VISUAL_SEQUENCE
PREFER_DETERMINISTIC
PREFER_LEARNED
NEEDS_MANUAL_EDIT
INSUFFICIENT_SUPPORT
```

Reason codes:

```text
SMOOTH_PROGRESSION
HISTORICAL_MATCH
BAD_INTERMEDIATE_SHAPE
SUDDEN_VISUAL_JUMP
WRONG_TOPOLOGY
OOD_CONCERN
EXPORT_ISSUE
OTHER
```

Rules:

- Review data is evidence only.
- Do not automatically retrain.
- Do not silently change model approval.
- Preserve model and target provenance.
- Support CSV and JSON export.
- Do not store original private CAD in review rows.

---

# 12. Candidate comparison improvements

For each candidate display:

```text
candidate type
station count
combined confidence
historical confidence
model support confidence
OOD status
blend alpha
ensemble disagreement
progression smoothness
minimum pass confidence
fallback status
projection status
```

Add:

```text
Improvement versus deterministic baseline
```

Use actual sequence metrics where available.

Do not fabricate improvement for arbitrary user targets lacking a teacher sequence.

For live targets, label it:

```text
visual correction magnitude
```

rather than “accuracy improvement.”

---

# 13. Export verification

Automate verification for:

```text
combined DXF
individual DXFs
SVG
PNG contact sheet
JSON
CSV
HTML
ZIP
```

Check:

- File exists
- Nonzero size
- Expected MIME type
- Expected ZIP members
- JSON schema
- CSV headers
- HTML self-contained
- SVG parses
- PNG signature
- DXF contains expected layers and station labels
- No private path
- No private filename
- No source CAD embedded
- Model provenance present
- Manufacturing disclaimer present

---

# 14. Performance benchmark

Add:

```text
scripts/benchmark_visual_flower.py
```

Measure:

```text
canonicalization time
deterministic generation time
learned inference time
historical matching time
export time
total request time
peak memory where practical
```

Run golden profiles at:

```text
8 stations
16 stations
28 stations
```

Report:

```text
mean
median
p95
maximum
```

Initial prototype targets:

```text
16-station generation p95 under 2 seconds preferred
28-station generation p95 under 4 seconds preferred
model-status endpoint under 250 ms preferred
```

Do not fail solely because a slow development machine misses a preferred target.

Use:

```text
PASS
WARN
FAIL
```

with documented hard and soft thresholds.

---

# 15. Reliability and caching

Ensure:

- Active model is loaded once and cached safely.
- Artifact hash is checked on initial load.
- Cache is invalidated if configured model path or artifact identity changes.
- Concurrent generation does not mutate model arrays.
- Failed learned inference does not poison subsequent deterministic requests.
- Exports use unique run/candidate paths.
- Temporary files are cleaned.
- Repeated requests produce deterministic results.

Do not add hot reload of model weights unless it can be proven safe.

A restart-based model change is acceptable.

---

# 16. Browser end-to-end testing

Use the repository’s available browser automation.

Required flows:

## Supported profile

1. Start application.
2. Open Visual Flower Generator.
3. Confirm active private model.
4. Load public U-channel example.
5. Select COMPARE_ALL.
6. Generate 16 stations.
7. Confirm deterministic candidate.
8. Confirm learned candidate.
9. Confirm conservative candidate.
10. Play animation.
11. View historical overlay.
12. View learned correction.
13. Submit engineer review.
14. Export ZIP.

## OOD profile

1. Load high-frequency negative fixture.
2. Generate.
3. Confirm learned fallback or abstention.
4. Confirm deterministic candidate remains.
5. Confirm OOD reason is visible.

## Model unavailable

1. Start without active model.
2. Confirm deterministic-only operation.
3. Confirm no fatal UI error.

Check console and network errors.

---

# 17. Backend tests

Add tests for:

```text
model doctor ready
invalid model doctor
path redaction
golden supported cases
golden OOD cases
8 / 16 / 28 stations
final-target anchoring
candidate types
deterministic fallback
review creation
review export
export verification
model cache behavior
concurrent inference
```

Run the entire Python suite.

---

# 18. Frontend tests

Add tests for:

```text
active model badge
approval boundary
evaluation metrics
guided demo
supported generation
OOD fallback message
candidate comparison
review submission
export controls
model-unavailable state
```

Run the complete frontend test suite and production build.

---

# 19. CI

GitHub Actions cannot use the private model.

CI must use a public test model and public fixtures.

CI must verify:

```text
golden fixture validity
public model doctor
supported COMPARE_ALL generation
OOD fallback
review storage
exports
determinism
privacy scanner
Python tests
frontend tests
frontend build
Docker build
smoke tests
```

Do not upload private artifacts.

---

# 20. Privacy scanner

Extend scanning to cover:

```text
golden fixtures
review exports
demo logs
readiness reports
benchmark reports
browser screenshots
ZIP exports
PID files
```

Fail on:

```text
private source filenames
absolute private paths
private model directory
private point arrays
private corpus shards
customer identity
```

Screenshots committed to Git must use public synthetic fixtures only.

---

# 21. Documentation

Create:

```text
docs/guides/visual-flower-demo-user-guide.md
docs/guides/visual-flower-demo-operator-runbook.md
docs/guides/engineer-review-guide.md
docs/specs/phase-21-demo-release.md
docs/reports/phase21-demo-readiness.schema.json
docs/reports/phase21-demo-readiness.json
docs/reports/phase21-demo-readiness.html
```

User guide must explain:

- Starting the app
- Drawing/importing
- Choosing engine
- Understanding candidates
- Understanding OOD
- Reviewing
- Exporting
- Safety limits

Operator runbook must explain:

- Environment variables
- Doctor
- Start
- Stop
- Status
- Verify
- Logs
- Recovery

---

# 22. Demo script

Prepare a repeatable 3–5 minute demonstration:

```text
1. Show active model and safety boundary.
2. Load a public profile.
3. Generate 16 stages with COMPARE_ALL.
4. Play the sequence.
5. Compare deterministic and learned candidates.
6. Show historical match.
7. Show OOD status.
8. Export the result.
9. Load a negative OOD example.
10. Show safe fallback.
```

Do not use private geometry in committed demo screenshots or recordings.

---

# 23. Readiness report

Required statuses:

```text
ONE-COMMAND STARTUP:
PASS / FAIL

MODEL HEALTH:
PASS / FAIL

GOLDEN SUPPORTED SUITE:
PASS / FAIL

GOLDEN OOD SUITE:
PASS / FAIL

BROWSER END-TO-END:
PASS / FAIL

EXPORT VERIFICATION:
PASS / FAIL

ENGINEER REVIEW CAPTURE:
PASS / FAIL

PERFORMANCE:
PASS / WARN / FAIL

PRIVACY:
PASS / FAIL

CUSTOMER VISUAL PROTOTYPE:
READY / NOT READY

MANUFACTURING APPROVAL:
NOT APPROVED

PHYSICAL ROLLER AVAILABILITY:
NOT DETERMINED
```

---

# 24. Acceptance gates

Do not declare Phase 21 complete unless:

- One-command doctor works.
- One-command start works.
- Stop removes only owned processes.
- Status reports active model.
- Verify completes a public end-to-end run.
- At least 30 supported golden cases pass.
- At least 10 negative OOD cases pass.
- 8, 16, and 28 stations pass.
- Final target anchoring passes.
- Model-unavailable fallback passes.
- Engineer review capture works.
- All export types pass validation.
- Browser tests pass.
- Full Python suite passes.
- Full frontend suite passes.
- Frontend build passes.
- Docker and smoke tests pass in CI.
- Privacy scan passes.
- No private artifacts are committed.
- Manufacturing approval remains NOT_APPROVED.

---

# 25. Prohibited shortcuts

Do not:

- Retrain simply because Phase 21 exists.
- Replace the approved model.
- Lower OOD gates.
- Commit private weights.
- Commit private geometry.
- Hardcode a private model path.
- Make Docker the only startup method.
- Kill unrelated processes.
- Fake browser verification.
- Snapshot unstable floats without tolerance.
- Automatically retrain from engineer reviews.
- Call same-seed results independent generalization.
- Call visual confidence manufacturing confidence.
- Remove deterministic fallback.

---

# 26. Final response required

Return:

```text
Repository
Base branch
Base SHA
New branch
Commit SHA
PR URL
PR base
Working tree

Python tests
Frontend tests
Frontend build
Docker
Smoke tests
Browser tests
Privacy scan

Doctor status
Start status
Stop status
Verify status

Golden supported cases
Golden OOD cases
8-station cases
16-station cases
28-station cases
Model-unavailable cases
Export verification

Review table
Review API
Review export
Frontend review controls

Performance mean / median / p95 / maximum
Model status endpoint time
Generation time
Export time

Readiness report path
User guide path
Operator runbook path
Demo script path
Pre-audit path
Post-audit path

CUSTOMER VISUAL PROTOTYPE:
READY or NOT READY

MANUFACTURING APPROVAL:
NOT APPROVED

PHYSICAL ROLLER AVAILABILITY:
NOT DETERMINED

Known limitations
```

Do not merge or tag without explicit instruction.

---

# 27. Final engineering principle

Phase 20 proved the private learned model can improve the deterministic baseline while rejecting unsupported geometry.

Phase 21 must prove the complete application is dependable.

The target is:

```text
one command
    ↓
healthy local application
    ↓
draw or import target
    ↓
compare deterministic and learned sequences
    ↓
explain support and OOD
    ↓
capture engineer review
    ↓
export evidence
    ↓
repeat reliably
```

The next milestone is a trustworthy prototype release, not a manufacturing system wearing a confidence badge.
