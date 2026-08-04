# Pre-CLRSG Preservation Audit

Base branch: `feature/visual-flower-customer-demo`
Base SHA: `3b9265ae986748d766e82170c969bd7bc6363aa6`

PRs 6, 7, and 8 were inspected and are open. The base had 247 Python tests, 4 frontend tests, a passing frontend build, and a passing clean-runner Docker/smoke workflow. Existing Phase 15–18 tags and the deterministic visual flower workflow are preserved.

Phase 19 adds only additive corpus/model registry tables, optional CLRSG inference, CLI commands, model-status API metadata, public synthetic fixtures/tests, and evidence documentation. Private CAD, private-derived geometry, private corpus shards, and private model weights remain outside Git.
