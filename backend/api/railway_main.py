from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response

from rollform_extractor.web.backend.api.app import create_app
from rollform_extractor.web.backend.demo_auth import configuration_errors
from rollform_extractor.web.backend.deployment_security import redact_private_paths


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


@app.middleware("http")
async def redact_hosted_json_paths(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if not request.url.path.startswith("/api/") or "application/json" not in content_type:
        return response

    body = b"".join([chunk async for chunk in response.body_iterator])
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Response(content=body, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)

    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(
        content=json.dumps(redact_private_paths(payload), separators=(",", ":")),
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
    )


__all__ = ["app"]
