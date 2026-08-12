from __future__ import annotations

import json
from pathlib import Path

import pytest

from rollform_extractor.clrsg_inference import infer_learned_candidates
from rollform_extractor.clrsg_model import load_clrsg_model, train_clrsg
from rollform_extractor.synthetic_corpus_schema import load_corpus
from rollform_extractor.synthetic_profile_families import PUBLIC_FAMILIES, make_family
from rollform_extractor.synthetic_sequence_factory import generate_public_corpus


def test_public_family_catalog_is_valid_and_versioned():
    assert len(PUBLIC_FAMILIES) == 10
    for family in PUBLIC_FAMILIES:
        profile = make_family(family)
        assert profile["metadata"]["source"] == "PUBLIC_PROCEDURAL_SYNTHETIC"
        assert profile["schema_version"] == 1
        if profile["topology"] == "CLOSED_CONTOUR":
            assert profile["computational_seam_vertex_id"]


def test_public_corpus_is_deterministic_and_grouped():
    first = generate_public_corpus(samples_per_family=2, seed=1729)
    second = generate_public_corpus(samples_per_family=2, seed=1729)
    assert first.manifest.dataset_id == second.manifest.dataset_id
    assert first.content_hash == second.content_hash
    assert {sample.station_count for sample in first.samples} <= set(range(8, 29))
    groups = {}
    for sample in first.samples:
        groups.setdefault(sample.parent_group_id, sample.split)
        assert groups[sample.parent_group_id] == sample.split


def test_corpus_write_round_trip(tmp_path: Path):
    corpus = generate_public_corpus(samples_per_family=1)
    corpus.write(tmp_path)
    loaded = load_corpus(tmp_path)
    assert loaded.manifest.dataset_id == corpus.manifest.dataset_id
    assert loaded.samples[0].teacher_hash == corpus.samples[0].teacher_hash


def test_clrsg_train_load_and_predict(tmp_path: Path):
    corpus = generate_public_corpus(samples_per_family=3)
    model_dir = tmp_path / "model"
    result = train_clrsg(corpus, model_dir, ensemble_members=5)
    model = load_clrsg_model(model_dir)
    prediction = model.predict(make_family("OPEN_U_CHANNEL"), 16)
    assert result["manifest"]["privacy_classification"] == "PUBLIC_TEST_MODEL"
    assert len(model.members) == 5
    assert prediction["residual"].shape == (28, 128, 2)
    assert prediction["ood_status"] in {"IN_DISTRIBUTION", "NEAR_DISTRIBUTION", "OUT_OF_DISTRIBUTION"}


def test_clrsg_artifact_tampering_is_rejected(tmp_path: Path):
    corpus = generate_public_corpus(samples_per_family=2)
    model_dir = tmp_path / "model"
    train_clrsg(corpus, model_dir)
    (model_dir / "feature_schema.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash"):
        load_clrsg_model(model_dir)


def test_learned_inference_has_explicit_fallback_without_model():
    profile = make_family("OPEN_U_CHANNEL")
    from rollform_extractor.visual_profile_schema import validate_profile
    result = infer_learned_candidates(validate_profile(profile), {"candidates": []}, None)
    assert result["status"] == "MODEL_UNAVAILABLE"
    assert result["warnings"] == ["MODEL_UNAVAILABLE"]
