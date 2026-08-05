from __future__ import annotations

import numpy as np

from rollform_extractor.private_clrsg import (
    PRIVATE_CORPUS_CLASSIFICATION,
    PRIVATE_TEACHER_VERSION,
    PrivateSeed,
    deterministic_baseline,
    generate_private_corpus,
    historical_progress_schedule,
    historical_warp_teacher,
    transform_target,
)


def _seed(name: str = "PRIVATE-FLOWER-001") -> PrivateSeed:
    x = np.linspace(-1.0, 1.0, 128)
    passes = []
    for progress in np.linspace(0.0, 1.0, 14):
        y = progress * (0.35 * np.cos(np.pi * x) + 0.15 * x * x)
        passes.append(np.column_stack([x, y]))
    value = np.asarray(passes)
    return PrivateSeed(name, "OPEN_PATH", "redacted-source-hash", value, historical_progress_schedule(value))


def test_historical_schedule_is_monotonic_and_anchored():
    schedule = _seed().schedule
    assert schedule[0] == 0.0
    assert schedule[-1] == 1.0
    assert np.all(np.diff(schedule) >= 0.0)


def test_private_transform_is_deterministic_and_changes_target():
    seed = _seed()
    first, recipe_a = transform_target(seed, 4, 1729)
    second, recipe_b = transform_target(seed, 4, 1729)
    assert np.allclose(first, second)
    assert recipe_a == recipe_b
    assert not np.allclose(first, seed.final)


def test_historical_teacher_uses_complete_source_sequence():
    seed = _seed()
    target, _ = transform_target(seed, 2, 1729)
    teacher = historical_warp_teacher(seed, target, 16)
    baseline = deterministic_baseline(target, 16, seed.topology)
    assert teacher.shape == (16, 128, 2)
    assert np.allclose(teacher[-1], target)
    assert not np.allclose(teacher, baseline)


def test_private_corpus_is_non_committable_and_group_safe(tmp_path, monkeypatch):
    seeds = (_seed("PRIVATE-FLOWER-001"), _seed("PRIVATE-FLOWER-002"))
    monkeypatch.setattr("rollform_extractor.private_clrsg.load_private_seeds", lambda _: seeds)
    corpus, summary = generate_private_corpus(
        tmp_path / "unused.json",
        tmp_path / "private-output",
        samples_per_seed=10,
        seed=1729,
    )
    assert corpus.manifest.classification == PRIVATE_CORPUS_CLASSIFICATION
    assert corpus.manifest.privacy == {"contains_private_derived_geometry": True, "committable": False}
    assert summary.seed_count == 2
    assert summary.accepted == len(corpus.samples)
    group_splits = {}
    for sample in corpus.samples:
        assert sample.classification == "PRIVATE_SYNTHETIC_DERIVED"
        assert sample.progression_schedule["teacher_version"] == PRIVATE_TEACHER_VERSION
        previous = group_splits.setdefault(sample.parent_group_id, sample.split)
        assert previous == sample.split
