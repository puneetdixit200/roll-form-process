# History-Constrained Flower Sequence Generation Prototype

This prototype is an offline, deterministic engineering aid. It extracts two
private historical flower drawings into redacted dataset identifiers, compares
a target final profile with historical final passes, aligns variable-length
pass sequences monotonically, interpolates in normalized developed-coordinate
space, and validates the generated candidate forward.

The result is always a **historically grounded flower-sequence candidate for
engineer review**. It is not production approval, a tooling recommendation,
physical roller assignment, or a manufacturability claim.

## Evidence boundary

The complete source drawings are private prototype evidence. Their hashes are
recorded locally, while public artifacts contain only redacted identifiers and
aggregate metrics. Partial roller drawings are optional supporting evidence;
they do not establish physical asset identity, availability, condition, or
approval.

## Pipeline

`source CAD -> canonical pass records -> historical dataset -> explainable final
profile retrieval -> monotonic alignment -> backward/template adaptation ->
forward validation -> engineer review`.

Only open or clearly compatible closed topology is eligible for generation. A
target with insufficient historical support or incompatible topology must
abstain. Synthetic-derived targets retain their parent flower and transform.

## Representation and generation

Each historical pass retains source handle, original geometry, translation and
scale-normalized shape samples, dimensions, developed-length proxy, bends,
topology, quality flags, and source hash. Retrieval uses available weighted
components and reports evidence coverage; missing fields are unavailable, not
zero similarity. Candidate passes reference source pass IDs and record the
interpolation progress and transformation.

The current prototype uses a transparent interpolation baseline and a bounded
8–28 station count. It is intentionally not a learned model. The generated
shape vector is an engineering preview representation and does not replace the
Phase 15 canonical neutral-line/outline model.

## Benchmark and review

Hidden-pass reconstruction masks intermediate passes and interpolates only from
visible adjacent anchors. Width, height, developed-length, shape, topology and
bend-count errors are reported per case; metrics are not replaced with zero.
All outputs require engineering review before any later use.

## Phase boundary

This phase does not implement retrieval services, generative AI, physical roller
selection, tooling recommendation, forming-sequence approval, or
manufacturability prediction. Additional anonymized complete flowers are
needed before generalization claims can be made.
