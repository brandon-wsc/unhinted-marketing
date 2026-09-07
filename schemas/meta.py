"""Deployment meta shapes (ADR 0023) — unauthenticated SPA boot info."""

from typing import Literal

from pydantic import BaseModel

DeploymentMode = Literal["cloud", "onprem"]


class MetaResponse(BaseModel):
    deployment_mode: DeploymentMode
    app_env: str
    version: str
