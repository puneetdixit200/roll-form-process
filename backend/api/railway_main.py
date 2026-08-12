from __future__ import annotations

import os
from pathlib import Path

from rollform_extractor.web.backend.api.app import create_app
from rollform_extractor.web.backend.demo_auth import configuration_errors


def _validate_railway_environment() -> None:
    errors = configuration_errors()
    workspace = Path(os.environ.get("ROLLFORM_WEB_WORKSPACE", "/data/web-workspace"))
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"ROLLFORM_WEB_WORKSPACE is not writable: {type(exc).__name__}")
    if errors:
        raise RuntimeError("Railway deployment configuration is invalid: " + "; ".join(errors))


_validate_railway_environment()
app = create_app()

__all__ = ["app"]
