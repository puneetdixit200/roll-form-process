"""Versioned, privacy-aware schemas for the public synthetic corpus factory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


SYNTHETIC_CORPUS_SCHEMA_VERSION = 1
SYNTHETIC_CORPUS_GENERATOR_VERSION = "synthetic_visual_corpus_v1"
SAMPLE_CLASSIFICATIONS = {
    "PRIVATE_REAL_SEED",
    "PRIVATE_SYNTHETIC_DERIVED",
    "PUBLIC_PROCEDURAL_SYNTHETIC",
    "PUBLIC_NEGATIVE_OOD",
    "PUBLIC_TEST_FIXTURE",
}


def stable_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SyntheticSample:
    sample_id: str
    classification: str
    family_id: str
    parent_group_id: str
    target_profile: dict[str, Any]
    station_count: int
    teacher_sequence: list[list[list[float]]]
    baseline_sequence: list[list[list[float]]]
    transform_recipe: dict[str, Any] = field(default_factory=dict)
    progression_schedule: dict[str, Any] = field(default_factory=dict)
    split: str = "TRAIN"
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.classification not in SAMPLE_CLASSIFICATIONS:
            raise ValueError(f"unsupported synthetic sample classification: {self.classification}")
        if not 8 <= int(self.station_count) <= 28:
            raise ValueError("station_count must be between 8 and 28")
        if self.split not in {"TRAIN", "VALIDATION", "TEST", "OOD"}:
            raise ValueError("split must be TRAIN, VALIDATION, TEST, or OOD")

    @property
    def target_hash(self) -> str:
        return stable_hash(self.target_profile)

    @property
    def teacher_hash(self) -> str:
        return stable_hash(self.teacher_sequence)

    @property
    def baseline_hash(self) -> str:
        return stable_hash(self.baseline_sequence)

    def metadata(self) -> dict[str, Any]:
        return {
            "schema_version": SYNTHETIC_CORPUS_SCHEMA_VERSION,
            "sample_id": self.sample_id,
            "classification": self.classification,
            "family_id": self.family_id,
            "parent_group_id": self.parent_group_id,
            "target_profile": self.target_profile,
            "target_profile_hash": self.target_hash,
            "station_count": self.station_count,
            "teacher_sequence_hash": self.teacher_hash,
            "baseline_sequence_hash": self.baseline_hash,
            "transform_recipe": self.transform_recipe,
            "progression_schedule": self.progression_schedule,
            "split": self.split,
            "warnings": list(self.warnings),
        }


@dataclass
class SyntheticCorpusManifest:
    dataset_id: str
    dataset_version: str = "synthetic_visual_v1"
    generator_version: str = SYNTHETIC_CORPUS_GENERATOR_VERSION
    seed: int = 1729
    classification: str = "PUBLIC_TEST_MODEL"
    sample_counts: dict[str, int] = field(default_factory=dict)
    station_distribution: dict[str, int] = field(default_factory=dict)
    family_distribution: dict[str, int] = field(default_factory=dict)
    classification_distribution: dict[str, int] = field(default_factory=dict)
    recipe_hash: str = ""
    content_hash: str = ""
    privacy: dict[str, Any] = field(default_factory=lambda: {"contains_private_derived_geometry": False, "committable": True})

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SYNTHETIC_CORPUS_SCHEMA_VERSION, **asdict(self)}


@dataclass
class SyntheticCorpus:
    manifest: SyntheticCorpusManifest
    samples: list[SyntheticSample]

    def to_index(self) -> dict[str, Any]:
        return {"manifest": self.manifest.to_dict(), "samples": [sample.metadata() for sample in self.samples]}

    @property
    def content_hash(self) -> str:
        return stable_hash({"manifest": {k: v for k, v in self.manifest.to_dict().items() if k not in {"content_hash"}}, "samples": [s.metadata() for s in self.samples]})

    def write(self, root: Path) -> None:
        """Write public metadata plus compressed numeric shards without private paths."""
        import numpy as np

        root.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, Any] = {}
        for sample in self.samples:
            arrays[f"{sample.sample_id}__teacher"] = np.asarray(sample.teacher_sequence, dtype=np.float64)
            arrays[f"{sample.sample_id}__baseline"] = np.asarray(sample.baseline_sequence, dtype=np.float64)
        np.savez_compressed(root / "sequences.npz", **arrays)
        self.manifest.content_hash = self.content_hash
        (root / "manifest.json").write_text(json.dumps(self.manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        (root / "index.json").write_text(json.dumps(self.to_index(), indent=2, sort_keys=True), encoding="utf-8")


def load_corpus(root: Path) -> SyntheticCorpus:
    import numpy as np

    manifest_payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    arrays = np.load(root / "sequences.npz", allow_pickle=False)
    samples: list[SyntheticSample] = []
    for metadata in index["samples"]:
        sample_id = metadata["sample_id"]
        profile = metadata["target_profile"] if "target_profile" in metadata else {}
        samples.append(SyntheticSample(
            sample_id=sample_id,
            classification=metadata["classification"],
            family_id=metadata["family_id"],
            parent_group_id=metadata["parent_group_id"],
            target_profile=profile,
            station_count=metadata["station_count"],
            teacher_sequence=arrays[f"{sample_id}__teacher"].tolist(),
            baseline_sequence=arrays[f"{sample_id}__baseline"].tolist(),
            transform_recipe=metadata.get("transform_recipe", {}),
            progression_schedule=metadata.get("progression_schedule", {}),
            split=metadata.get("split", "TRAIN"),
            warnings=metadata.get("warnings", []),
        ))
    manifest = SyntheticCorpusManifest(**{key: value for key, value in manifest_payload.items() if key != "schema_version"})
    return SyntheticCorpus(manifest, samples)
