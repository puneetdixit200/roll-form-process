# Operating the Phase 19 CLRSG prototype

## Public CI corpus

```bash
rollform-extractor synthetic-corpus-plan
rollform-extractor synthetic-corpus-generate --output /tmp/public-corpus --samples-per-family 6 --seed 1729
rollform-extractor synthetic-corpus-validate /tmp/public-corpus
rollform-extractor clrsg-train /tmp/public-corpus --output /tmp/public-clrsg-model --ensemble-members 5
```

The generated corpus is procedural synthetic data. It is not historical evidence and is not a manufacturing dataset. Model artifacts are hash-verified NPZ/JSON files; no pickle or remote service is used.

## Private prototype

Set `ROLLFORM_PRIVATE_DATA_ROOT`, `ROLLFORM_SYNTHETIC_CORPUS_ROOT`, `ROLLFORM_MODEL_REGISTRY_ROOT`, and `ROLLFORM_ACTIVE_CLRSG_MODEL` only in the local environment. Private derived geometry and `PRIVATE_PROTOTYPE_MODEL` artifacts must remain outside Git and CI. The existing deterministic visual generator remains available when the model is missing, invalid, or out of distribution.

## UI/API behavior

The visual flower generation request accepts `generation_engine`: `AUTO`, `DETERMINISTIC_ONLY`, `LEARNED_HYBRID`, or `COMPARE_ALL`. `/api/visual-flower/model/status` reports model availability and approval boundary. `AUTO` never removes the deterministic candidate. Learned scores are visual prototype support only; production, tooling, and physical-roller decisions remain out of scope.
