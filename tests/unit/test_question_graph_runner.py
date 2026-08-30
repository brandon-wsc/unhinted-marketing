"""Question-run LLM scope is per-company and must not leak across concurrent tasks."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from internal.llm.resolve import (
    CompanyLlmBundle,
    ResolvedModel,
    company_llm_scope,
    llm_bundle_scope,
    resolve_llm_model,
)
from internal.llm.router import ModelTier


def _org(model_id: str) -> ResolvedModel:
    return ResolvedModel(
        model_id=model_id,
        api_key="sk-org",
        api_base="https://openrouter.ai/api/v1",
        provider_type="openai_compatible",
        source="org",
        key_last4="org1",
    )


@pytest.mark.asyncio
async def test_concurrent_bundle_scopes_do_not_leak() -> None:
    seen: dict[str, str] = {}

    async def use(name: str, bundle: CompanyLlmBundle) -> None:
        with llm_bundle_scope(bundle):
            await asyncio.sleep(0)
            seen[name] = resolve_llm_model(ModelTier.CHEAP).model_id

    await asyncio.gather(
        use("a", CompanyLlmBundle(cheap=_org("model-a"))),
        use("b", CompanyLlmBundle(cheap=_org("model-b"))),
    )
    assert seen == {"a": "model-a", "b": "model-b"}


@pytest.mark.asyncio
async def test_concurrent_company_scopes_load_own_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    cid_a = uuid4()
    cid_b = uuid4()
    bundles = {
        cid_a: CompanyLlmBundle(cheap=_org("org-a")),
        cid_b: CompanyLlmBundle(cheap=_org("org-b")),
    }

    async def fake_load(_db: object, company_id: object) -> CompanyLlmBundle:
        return bundles[company_id]  # type: ignore[index]

    monkeypatch.setattr(
        "internal.llm.resolve.load_company_llm_bundle",
        fake_load,
    )
    seen: dict[str, str] = {}

    async def use(label: str, company_id: object) -> None:
        async with company_llm_scope(MagicMock(), company_id):  # type: ignore[arg-type]
            await asyncio.sleep(0)
            seen[label] = resolve_llm_model(ModelTier.CHEAP).model_id

    await asyncio.gather(use("a", cid_a), use("b", cid_b))
    assert seen == {"a": "org-a", "b": "org-b"}
