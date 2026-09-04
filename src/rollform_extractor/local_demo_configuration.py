"""Load saved local-demo paths before the FastAPI app is constructed.

The normal launcher writes this configuration once.  Loading it in the local
ASGI entry point as well prevents a manually started backend from silently
losing the historical dataset and disabling flower generation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import MutableMapping


CONFIG_ENVIRONMENT_NAMES = {
    "dataset": "ROLLFORM_FLOWER_PROTOTYPE_DATASET",
    "model": "ROLLFORM_ACTIVE_CLRSG_MODEL",
    "registry": "ROLLFORM_MODEL_REGISTRY_ROOT",
}


def saved_demo_environment(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    values = environ if environ is not None else os.environ
    configured = values.get("ROLLFORM_DEMO_CONFIG")
    if configured:
        config_path = Path(configured).expanduser()
    else:
        config_root = Path(
            values.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ).expanduser()
        config_path = config_root / "rollform-extractor" / "visual-flower-demo.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, str] = {}
    for label, environment_name in CONFIG_ENVIRONMENT_NAMES.items():
        path_value = payload.get(label)
        if isinstance(path_value, str):
            path = Path(path_value).expanduser()
            if path.exists():
                result[environment_name] = str(path.resolve())
    return result


def apply_saved_demo_environment(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    values = environ if environ is not None else os.environ
    applied: dict[str, str] = {}
    for name, path in saved_demo_environment(values).items():
        if not values.get(name):
            values[name] = path
            applied[name] = path
    return applied
