"""Unit tests for GET /api/meta + deployment_mode settings (ADR 0023). No DB."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cmd.api.main import create_app
from internal.config import Settings, settings


@asynccontextmanager
async def _noop_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def test_meta_reports_baked_deployment_mode() -> None:
    app = create_app(lifespan_fn=_noop_lifespan)
    with TestClient(app) as client:
        resp = client.get("/api/meta")
    assert resp.status_code == 200
    body = resp.json()
    # Whatever the process started with is what the endpoint reports — the
    # mode is a startup constant, not recomputed per request.
    assert body == {
        "deployment_mode": settings.deployment_mode,
        "app_env": settings.app_env,
        "version": body["version"],
    }
    assert body["deployment_mode"] in ("cloud", "onprem")
    assert body["version"]


def test_settings_deployment_mode_defaults_to_onprem() -> None:
    assert Settings(_env_file=None).deployment_mode == "onprem"


def test_settings_deployment_mode_accepts_cloud() -> None:
    assert Settings(_env_file=None, deployment_mode="cloud").deployment_mode == "cloud"


def test_settings_deployment_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, deployment_mode="edge")
