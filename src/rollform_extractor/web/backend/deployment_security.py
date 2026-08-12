from __future__ import annotations

from typing import Any


_REDACTED = "<redacted-path>"
_PATH_PREFIXES = ("/data/", "/app/", "/home/", "/root/", "/tmp/")


def redact_private_paths(value: Any) -> Any:
    """Return a JSON-compatible structure with hosted filesystem paths redacted."""
    if isinstance(value, dict):
        return {key: redact_private_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_private_paths(item) for item in value]
    if isinstance(value, tuple):
        return [redact_private_paths(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        lowered = normalized.lower()
        if normalized.startswith(_PATH_PREFIXES) or lowered.startswith("c:/users/") or "/rollform-private/" in lowered:
            return _REDACTED
    return value
