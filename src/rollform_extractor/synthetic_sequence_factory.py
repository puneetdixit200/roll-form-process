"""Deterministic public synthetic corpus factory and teacher sequences."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np

from rollform_extractor.synthetic_corpus_schema import (
    SYNTHETIC_CORPUS_GENERATOR_VERSION,
    SyntheticCorpus,
    SyntheticCorpusManifest,
    SyntheticSample,
    stable_hash,
)
from rollform_extractor.synthetic_profile_families import PUBLIC_FAMILIES, make_family
from rollform_extractor.visual_profile_canonicalization import canonicalize_profile
from rollform_extractor.visual_profile_schema import validate_profile


SCHEDULES = ("LINEAR", "SMOOTHSTEP", "EARLY_FORMING", "LATE_FORMING", "S_CURVE")


def _canonical_points(profile: dict[str, Any], count: int = 128) -> np.ndarray:
    return np.asarray(canonicalize_profile(validate_profile(profile), samples=count)["points"], dtype=float)


def progression(name: str, progress: np.ndarray) -> np.ndarray:
    if name == "LINEAR":
        return progress
    if name == "SMOOTHSTEP":
        return 3 * progress**2 - 2 * progress**3
    if name == "EARLY_FORMING":
        return progress**0.70
    if name == "LATE_FORMING":
        return progress**1.40
    if name == "S_CURVE":
        z = 1 / (1 + np.exp(-10 * (progress - .5)))
        return (z - z[0]) / (z[-1] - z[0])
    raise ValueError(f"unsupported schedule: {name}")


def teacher_sequence(profile: dict[str, Any], station_count: int, schedule: str = "SMOOTHSTEP") -> np.ndarray:
    target = _canonical_points(profile)
    if validate_profile(profile).topology == "CLOSED_CONTOUR":
        start = target * 0.82
    else:
        start = np.stack([np.linspace(-1, 1, len(target)), np.zeros(len(target))], axis=1)
    p = np.linspace(0, 1, station_count)
    eased = progression(schedule, p)
    return np.asarray([start * (1 - value) + target * value for value in eased])


def baseline_sequence(profile: dict[str, Any], station_count: int, schedule: str = "LINEAR") -> np.ndarray:
    return teacher_sequence(profile, station_count, schedule)


def _resample_sequence(sequence: np.ndarray, slots: int = 28) -> np.ndarray:
    source = np.linspace(0, 1, len(sequence))
    target = np.linspace(0, 1, slots)
    return np.asarray([[np.interp(target, source, sequence[:, point, axis]) for point in range(sequence.shape[1]) for axis in range(2)] for _ in [0]])[0].reshape(slots, sequence.shape[1], 2)


def _split(parent_group: str) -> str:
    value = int(sha256(parent_group.encode()).hexdigest()[:8], 16) % 100
    return "TRAIN" if value < 70 else "VALIDATION" if value < 85 else "TEST"


def generate_public_corpus(*, samples_per_family: int = 6, seed: int = 1729) -> SyntheticCorpus:
    rng = np.random.default_rng(seed)
    samples: list[SyntheticSample] = []
    for family_index, family in enumerate(PUBLIC_FAMILIES):
        for index in range(samples_per_family):
            profile = make_family(family, index)
            station_count = 8 + ((family_index * 3 + index * 5) % 21)
            schedule = SCHEDULES[(family_index + index) % len(SCHEDULES)]
            teacher = teacher_sequence(profile, station_count, schedule)
            baseline = baseline_sequence(profile, station_count, "LINEAR")
            teacher_28 = _resample_sequence(teacher)
            baseline_28 = _resample_sequence(baseline)
            parent = f"public-{family}-{index:03d}"
            sample_id = "ssample-" + sha256(f"{family}|{index}|{seed}|{station_count}|{schedule}".encode()).hexdigest()[:16]
            samples.append(SyntheticSample(
                sample_id=sample_id,
                classification="PUBLIC_PROCEDURAL_SYNTHETIC",
                family_id=family,
                parent_group_id=parent,
                target_profile=profile,
                station_count=station_count,
                teacher_sequence=teacher_28.tolist(),
                baseline_sequence=baseline_28.tolist(),
                transform_recipe={"family_index": family_index, "sample_index": index, "rng_seed": int(seed)},
                progression_schedule={"name": schedule},
                split=_split(parent),
            ))
    counts: dict[str, int] = {}
    stations: dict[str, int] = {}
    families: dict[str, int] = {}
    classifications: dict[str, int] = {}
    for item in samples:
        counts[item.split] = counts.get(item.split, 0) + 1
        stations[str(item.station_count)] = stations.get(str(item.station_count), 0) + 1
        families[item.family_id] = families.get(item.family_id, 0) + 1
        classifications[item.classification] = classifications.get(item.classification, 0) + 1
    recipe = {"generator": SYNTHETIC_CORPUS_GENERATOR_VERSION, "seed": seed, "samples_per_family": samples_per_family}
    manifest = SyntheticCorpusManifest(
        dataset_id="scorpus-" + stable_hash(recipe)[:16],
        seed=seed,
        classification="PUBLIC_TEST_MODEL",
        sample_counts=counts,
        station_distribution=stations,
        family_distribution=families,
        classification_distribution=classifications,
        recipe_hash=stable_hash(recipe),
        privacy={"contains_private_derived_geometry": False, "committable": True},
    )
    return SyntheticCorpus(manifest, samples)


def generate_public_corpus_to(output: Path, *, samples_per_family: int = 6, seed: int = 1729) -> SyntheticCorpus:
    corpus = generate_public_corpus(samples_per_family=samples_per_family, seed=seed)
    corpus.write(output)
    return corpus
