# Phase 21: Prototype validation and demo release

Phase 21 hardens the local visual flower prototype around the already approved
private CLRSG model. It adds public golden fixtures, a redacted model doctor,
one-command host startup, export checks, and append-only engineer feedback.

The learned model remains private and is loaded only through environment
configuration. Public fixtures are procedural and independent of private flower
coordinates. Review records are evidence only; they never retrain or change
approval state automatically.

## Safety boundary

The product is a visual geometry prototype only. It is not manufacturing
approval, tooling approval, physical roller selection, or production release.
Visual confidence describes geometric support and is not manufacturing
confidence.

## Release workflow

`doctor` checks the local environment and reports redacted PASS/WARN/FAIL
state. `start` owns only the backend and frontend processes recorded in its PID
file. `verify` exercises public target creation, 16-stage comparison, final
target anchoring, model doctor, and safe exports. `stop` terminates only those
owned process groups.

## Golden policy

The committed suite contains 30 supported procedural cases and 10 high-frequency
negative probes. Assertions cover topology, finite geometry, station count,
target anchoring, fallback/OOD state, and export safety. Floating-point points
are not blindly snapshotted; algorithm-version changes require an explicit
fixture review.

## Engineer feedback

Candidate reviews are append-only and store candidate/run identity, decision,
reason codes, reviewer, notes, target hash, model ID, and algorithm version.
Feedback does not retrain the model or approve manufacturing use.
