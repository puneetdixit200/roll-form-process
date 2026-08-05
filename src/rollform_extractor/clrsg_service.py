"""Registry and public synthetic corpus operations."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from rollform_extractor.clrsg_model import CLRSG_ALGORITHM_VERSION, load_clrsg_model, train_clrsg
from rollform_extractor.database import CLRSGModelActivationRow, CLRSGModelRow, CLRSGTrainingRunRow, SyntheticCorpusDatasetRow, SyntheticCorpusSampleRow
from rollform_extractor.synthetic_corpus_schema import SyntheticCorpus, load_corpus


def inspect_corpus(root: Path) -> dict[str, Any]:
    corpus = load_corpus(root)
    return {"dataset_id": corpus.manifest.dataset_id, "dataset_hash": corpus.manifest.content_hash, "sample_count": len(corpus.samples), "manifest": corpus.manifest.to_dict(), "privacy": corpus.manifest.privacy}


def validate_corpus(root: Path) -> dict[str, Any]:
    corpus = load_corpus(root)
    issues: list[str] = []
    groups: dict[str, str] = {}
    for sample in corpus.samples:
        previous = groups.setdefault(sample.parent_group_id, sample.split)
        if previous != sample.split:
            issues.append(f"parent group leakage: {sample.parent_group_id}")
        if sample.classification.startswith("PRIVATE") and corpus.manifest.privacy.get("committable", True):
            issues.append("private sample in committable corpus")
        if len(sample.teacher_sequence) != 28 or len(sample.baseline_sequence) != 28:
            issues.append(f"invalid normalized sequence shape: {sample.sample_id}")
    return {"valid": not issues, "issues": sorted(set(issues)), "dataset_id": corpus.manifest.dataset_id, "sample_count": len(corpus.samples), "deterministic_content_hash": corpus.content_hash}


def train_and_register(engine, dataset_root: Path, output_root: Path, *, ensemble_members: int = 5, seed: int = 1729) -> dict[str, Any]:
    corpus = load_corpus(dataset_root)
    result = train_clrsg(corpus, output_root, ensemble_members=ensemble_members, seed=seed)
    manifest = result["manifest"]
    run_id = "clrsg-run-" + sha256(f"{manifest['model_id']}|{corpus.manifest.dataset_id}".encode()).hexdigest()[:16]
    with Session(engine) as session:
        model = session.scalar(select(CLRSGModelRow).where(CLRSGModelRow.model_id == manifest["model_id"]))
        if model is None:
            model = CLRSGModelRow(model_id=manifest["model_id"], algorithm_version=CLRSG_ALGORITHM_VERSION, dataset_id=corpus.manifest.dataset_id, dataset_hash=corpus.manifest.content_hash, privacy_classification=manifest["privacy_classification"], status="TRAINED", manifest_json=manifest, model_path=str(output_root))
            session.add(model)
        if session.scalar(select(CLRSGTrainingRunRow).where(CLRSGTrainingRunRow.run_id == run_id)) is None:
            session.add(CLRSGTrainingRunRow(run_id=run_id, dataset_id=corpus.manifest.dataset_id, model_id=manifest["model_id"], status="TRAINED", metrics_json=result["metrics"]))
        session.commit()
    return result | {"run_id": run_id}


def list_models(engine) -> list[dict[str, Any]]:
    with Session(engine) as session:
        active = {row.model_id for row in session.scalars(select(CLRSGModelActivationRow).where(CLRSGModelActivationRow.active.is_(True)))}
        return [{"model_id": row.model_id, "algorithm_version": row.algorithm_version, "dataset_id": row.dataset_id, "privacy_classification": row.privacy_classification, "status": "ACTIVE" if row.model_id in active else row.status, "manifest": row.manifest_json, "model_path_configured": Path(row.model_path).is_dir()} for row in session.scalars(select(CLRSGModelRow).order_by(CLRSGModelRow.model_id))]


def model_status(engine) -> dict[str, Any]:
    models = list_models(engine)
    active = [item for item in models if item["status"] == "ACTIVE"]
    configured = os.environ.get("ROLLFORM_ACTIVE_CLRSG_MODEL")
    if configured:
        try:
            local_model = load_clrsg_model(Path(configured).expanduser().resolve())
            local_entry = {"model_id": local_model.model_id, "algorithm_version": local_model.manifest.get("algorithm_version", CLRSG_ALGORITHM_VERSION), "dataset_id": local_model.manifest.get("dataset_id"), "privacy_classification": local_model.manifest.get("privacy_classification"), "status": "ACTIVE", "manifest": {"model_id": local_model.model_id, "algorithm_version": local_model.manifest.get("algorithm_version"), "privacy_classification": local_model.manifest.get("privacy_classification"), "station_range": local_model.manifest.get("station_range"), "supported_topology": local_model.manifest.get("supported_topology")}, "model_path_configured": True}
            active = [item for item in active if item.get("model_id") != local_model.model_id] + [local_entry]
            models = [item for item in models if item.get("model_id") != local_model.model_id] + [local_entry]
        except (OSError, ValueError, KeyError):
            pass
    return {"algorithm_version": CLRSG_ALGORITHM_VERSION, "active_models": active, "models": models, "deterministic_fallback": True, "production_approval": "NOT_APPROVED"}


def register_dataset(engine, corpus: SyntheticCorpus) -> dict[str, Any]:
    with Session(engine) as session:
        row = session.scalar(select(SyntheticCorpusDatasetRow).where(SyntheticCorpusDatasetRow.dataset_id == corpus.manifest.dataset_id))
        if row is None:
            row = SyntheticCorpusDatasetRow(dataset_id=corpus.manifest.dataset_id, dataset_hash=corpus.manifest.content_hash, classification=corpus.manifest.classification, generator_version=corpus.manifest.generator_version, manifest_json=corpus.manifest.to_dict())
            session.add(row); session.flush()
            for sample in corpus.samples:
                session.add(SyntheticCorpusSampleRow(dataset_id=row.id, sample_id=sample.sample_id, parent_group_id=sample.parent_group_id, classification=sample.classification, split=sample.split, metadata_json=sample.metadata()))
            session.commit()
    return {"dataset_id": corpus.manifest.dataset_id, "dataset_hash": corpus.manifest.content_hash, "sample_count": len(corpus.samples)}


def activate_model(engine, model_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        model = session.scalar(select(CLRSGModelRow).where(CLRSGModelRow.model_id == model_id))
        if model is None:
            raise LookupError("CLRSG model not registered")
        load_clrsg_model(Path(model.model_path))
        session.execute(update(CLRSGModelActivationRow).where(CLRSGModelActivationRow.topology_scope == "ALL").values(active=False))
        session.add(CLRSGModelActivationRow(model_id=model_id, topology_scope="ALL", active=True))
        model.status = "ACTIVE"
        session.commit()
    return {"model_id": model_id, "status": "ACTIVE", "production_approval": "NOT_APPROVED"}
