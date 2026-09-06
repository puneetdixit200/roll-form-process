from rollform_extractor.local_demo_configuration import apply_saved_demo_environment

# Keep direct ``uvicorn backend.api.main:app`` starts equivalent to the
# supported one-command launcher. Explicit shell variables still take priority.
apply_saved_demo_environment()

from rollform_extractor.web.backend.api.app import app  # noqa: E402

__all__ = ["app"]
