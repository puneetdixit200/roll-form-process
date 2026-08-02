# Phase 18 operator checklist

1. Create a draft dataset and add project-scoped cases with immutable input hashes.
2. Obtain two independent assertions per case.
3. Adjudicate conflicts and validate the dataset.
4. Lock the dataset before evaluating thresholds or promoting usage.
5. Treat threshold profiles as evidence until explicitly engineer-approved.
6. Promote only adjudicated `MATCH_DESIGN` cases.
7. Run stale checks after re-extraction.
8. Search historical design evidence with synthetic, stale, and unresolved data excluded unless explicitly requested.

A confirmed design usage is historical evidence only. It is not a physical
asset assignment or tooling recommendation.
