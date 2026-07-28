from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib import resources
import json
from pathlib import Path
from typing import Any

import yaml


STAGE_CONFIG_KEYS = {
    "conversion": (),
    "parsing": ("geometry",),
    "station_detection": ("geometry", "stations"),
    "profile_detection": ("geometry", "profiles"),
    "roller_detection": ("geometry", "rollers"),
    "preview": ("geometry.curve_sampling_spacing_mm",),
}


@dataclass(frozen=True)
class UnitsConfig:
    default: str | None


@dataclass(frozen=True)
class GeometryConfig:
    endpoint_join_tolerance_mm: float
    duplicate_tolerance_mm: float
    curve_sampling_spacing_mm: float
    minimum_entity_length_mm: float


@dataclass(frozen=True)
class StationsConfig:
    minimum_confidence: float
    label_search_radius_mm: float
    cluster_gap_factor: float


@dataclass(frozen=True)
class ProfilesConfig:
    minimum_confidence: float
    minimum_score_margin: float


@dataclass(frozen=True)
class RollersConfig:
    minimum_confidence: float


@dataclass(frozen=True)
class ExtractionConfig:
    units: UnitsConfig
    geometry: GeometryConfig
    stations: StationsConfig
    profiles: ProfilesConfig
    rollers: RollersConfig

    @classmethod
    def load(
        cls, path: Path | None = None, overrides: dict[str, Any] | None = None
    ) -> "ExtractionConfig":
        data = _load_packaged_defaults()
        if path is not None:
            data = _merge_strict(data, _load_yaml(path))
        if overrides:
            data = _merge_strict(data, overrides)
        return cls(
            units=UnitsConfig(**data["units"]),
            geometry=GeometryConfig(**data["geometry"]),
            stations=StationsConfig(**data["stations"]),
            profiles=ProfilesConfig(**data["profiles"]),
            rollers=RollersConfig(**data["rollers"]),
        )

    def snapshot(self) -> dict[str, Any]:
        return _sort_mapping(asdict(self))

    def hash_for(self, stage: str) -> str:
        try:
            keys = STAGE_CONFIG_KEYS[stage]
        except KeyError as exc:
            raise KeyError(f"unknown stage: {stage}") from exc

        source = self.snapshot()
        subset = {_path_key(key): _get_path(source, key) for key in keys}
        payload = json.dumps(subset, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


def _load_packaged_defaults() -> dict[str, Any]:
    default_yaml = resources.files("rollform_extractor").joinpath("config/default.yaml")
    with default_yaml.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("default configuration must be a mapping")
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return data


def _merge_strict(
    base: dict[str, Any], override: dict[str, Any], prefix: str = ""
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        name = f"{prefix}.{key}" if prefix else key
        if key not in base:
            raise KeyError(f"unknown configuration key: {name}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise TypeError(f"configuration section must be a mapping: {name}")
            merged[key] = _merge_strict(base[key], value, name)
        else:
            merged[key] = value
    return merged


def _get_path(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        value = value[part]
    return value


def _path_key(path: str) -> str:
    return path.replace(".", "__")


def _sort_mapping(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _sort_mapping(value) if isinstance(value, dict) else value
        for key, value in sorted(data.items())
    }
