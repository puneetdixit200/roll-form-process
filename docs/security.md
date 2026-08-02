# Phase 18 security and data governance

Phase 18 is offline and uses SQLite. Recognition inputs, assertions,
adjudications, approvals, promotions, and stale transitions are hash-linked or
audited. API access is project-scoped and path inputs are not used to access
arbitrary files. Exports must be treated as engineering evidence and must not
contain customer CAD, factory inventory, serial numbers, credentials, or
private paths. TLS verification remains enabled for dependency and CI access.
