"""Deployment meta route (ADR 0023).

Unauthenticated boot info for the SPA: which deployment mode this backend was
built/started as. The mode is fixed at process start (baked into on-prem
Docker images via build ARG) and never changes while running. Exposes nothing
sensitive — mode, app env, and version only.
"""

from fastapi import APIRouter

from internal.config import settings
from schemas.meta import MetaResponse

router = APIRouter(tags=["meta"])

# Keep in sync with pyproject.toml [project] version / FastAPI app version.
API_VERSION = "0.1.0"


@router.get("/meta", response_model=MetaResponse)
async def get_meta() -> MetaResponse:
    return MetaResponse(
        deployment_mode=settings.deployment_mode,
        app_env=settings.app_env,
        version=API_VERSION,
    )
