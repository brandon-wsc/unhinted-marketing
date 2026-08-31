"""Smoke coverage for BYOK Pydantic shapes (CI schemas gate)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas.byok import (
    ByokDeleteConflict,
    ByokModelCreate,
    ByokProbeResult,
    ByokProviderCreate,
    ByokProviderItem,
    ByokProviderPatch,
    ByokRoutingUpdate,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_provider_create_requires_base_for_compatible() -> None:
    with pytest.raises(ValidationError):
        ByokProviderCreate(
            label="x",
            provider_type="openai_compatible",
            api_key="sk-test",
        )
    body = ByokProviderCreate(
        label="  OpenRouter  ",
        provider_type="openai_compatible",
        api_key="  sk-test  ",
        api_base="https://openrouter.ai/api/v1/",
    )
    assert body.label == "OpenRouter"
    assert body.api_key == "sk-test"
    assert body.api_base == "https://openrouter.ai/api/v1"


def test_provider_create_gemini_without_base() -> None:
    body = ByokProviderCreate(
        label="Gemini",
        provider_type="gemini",
        api_key="AIza-test",
    )
    assert body.api_base is None
    assert body.provider_type == "gemini"

    express = ByokProviderCreate(
        label="Vertex Express",
        provider_type="vertex_ai",
        api_key="AQ-test",
    )
    assert express.api_base is None
    assert express.provider_type == "vertex_ai"

    body = ByokProviderPatch(api_key="  ")
    assert body.api_key is None


def test_provider_item_from_attributes() -> None:
    item = ByokProviderItem(
        id=uuid.uuid4(),
        label="k",
        provider_type="openai",
        key_last4="cret",
        api_base=None,
        last_verified_at=None,
        last_error_kind=None,
        verified=False,
        created_at=_now(),
        updated_at=_now(),
    )
    assert item.key_last4 == "cret"


def test_model_create_and_conflict_and_probe() -> None:
    model = ByokModelCreate(
        provider_id=uuid.uuid4(),
        model_id="  gpt-4o  ",
        capability="chat",
    )
    assert model.model_id == "gpt-4o"
    assert model.capability_source == "manual"
    conflict = ByokDeleteConflict(slots=["cheap"])
    assert conflict.code == "has_dependents"
    assert ByokProbeResult(ok=True).error_kind is None
    routing = ByokRoutingUpdate(cheap_model_id=None)
    assert routing.strong_model_id is None
