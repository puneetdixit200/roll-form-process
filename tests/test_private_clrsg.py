from __future__ import annotations

import json

import numpy as np
import pytest

from rollform_extractor.clrsg_model import load_clrsg_model
from rollform_extractor.private_clrsg import (
    PRIVATE_CORPUS_CLASSIFICATION,
    PRIVATE_MODEL_CLASSIFICATION,
    PRIVATE_TEACHER_VERSION,
    PrivateSeed,
    _assert_private_root,
    _profile_payload,
    deterministic_baseline,
    generate_private_corpus,
    historical_progress_schedule,
    historical_warp_teacher,
    train_private_model,
    transform_target,
)


def _seed(name: str = "PRIVATE-FLOWER-001", topology: str = "OPEN_PATH", station_count: int = 14) -> PrivateSeed:
    x = np.linspace(-1.0, 1.0, 128)
    passes = []
    for progress in np.linspace(0.0, 1.0, station_count):
        y = progress * (0.35 * np.cos(np.pi * x) + 0.15 * x * x)
        points = np.column_stack([x, y])
        if topology == "CLOSED_CONTOUR":
            points[-1] = points[0]
        passes.append(points)
    value = np.asarray(passes)
    return PrivateSeed(name, topology, "redacted-source-hash", value, historical_progress_schedule(value))


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


def test_closed_profile_payload_does_not_create_duplicate_seam_vertex():
    seed = _seed(topology="CLOSED_CONTOUR")
    target, _ = transform_target(seed, 2, 1729)
    profile = _profile_payload(target, seed, "closed-target")
    assert profile["closed"] is True
    assert profile["computational_seam_vertex_id"] == "v-001"
    assert len(profile["segments"]) == len(profile["vertices"])
    coordinates = [(item["x"], item["y"]) for item in profile["vertices"]]
    assert coordinates[0] != coordinates[-1]


def test_private_root_rejects_any_git_ancestor(tmp_path):
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside the Git repository"):
        _assert_private_root(repository / "private" / "models")


def test_private_corpus_is_non_committable_and_group_safe(tmp_path, monkeypatch):
    seeds = (_seed("PRIVATE-FLOWER-001", station_count=14), _seed("PRIVATE-FLOWER-002", station_count=17))
    monkeypatch.setattr("rollform_extractor.private_clrsg.load_private_seeds", lambda _: seeds)
    corpus, summary = generate_private_corpus(tmp_path / "unused.json", tmp_path / "private-output", samples_per_seed=10, seed=1729)
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


def test_private_training_writes_validation_derived_ood_thresholds(tmp_path, monkeypatch):
    seeds = (_seed("PRIVATE-FLOWER-001", station_count=14), _seed("PRIVATE-FLOWER-002", station_count=17))
    monkeypatch.setattr("rollform_extractor.private_clrsg.load_private_seeds", lambda _: seeds)
    corpus, _ = generate_private_corpus(tmp_path / "unused.json", tmp_path / "private-corpus", samples_per_seed=20, seed=1729)
    model_root = tmp_path / "private-model"
    result = train_private_model(corpus, model_root, ensemble_members=5, seed=1729, private_seeds=seeds)
    manifest = json.loads((model_root / "manifest.json").read_text(encoding="utf-8"))
    thresholds = json.loads((model_root / "ood_thresholds.json").read_text(encoding="utf-8"))
    model = load_clrsg_model(model_root)
    assert result["privacy_classification"] == PRIVATE_MODEL_CLASSIFICATION
    assert manifest["privacy_classification"] == PRIVATE_MODEL_CLASSIFICATION
    assert manifest["bootstrap_unit"] == "PARENT_GROUP"
    assert manifest["ood_threshold_version"] == "validation_quantile_ood_v1"
    assert thresholds["thresholds"]["near_distribution"] >= thresholds["thresholds"]["in_distribution"]
    assert model.ood_thresholds == thresholds["thresholds"]
    assert (model_root / "evaluation_metrics.json").is_file()
    assert (model_root / "calibration.json").is_file()
