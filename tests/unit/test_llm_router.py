"""LLM router helpers — provider error wrapping (no live network)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from litellm.exceptions import BadRequestError, NotFoundError

from internal.llm import router as R


def test_wrap_unsupported_image_bad_request() -> None:
    exc = BadRequestError(
        message="model deepseek-v4-flash does not support image generation",
        model="deepseek-v4-flash",
        llm_provider="openai",
    )
    err = R._wrap_provider_error(exc, model="openai/deepseek-v4-flash")
    assert err.kind == "unsupported"
    assert "cannot generate images" in err.message


def test_wrap_not_found_as_unsupported() -> None:
    exc = NotFoundError(
        message="The model `deepseek-v4-flash` does not exist",
        model="deepseek-v4-flash",
        llm_provider="openai",
    )
    err = R._wrap_provider_error(exc, model="deepseek-v4-flash")
    assert err.kind == "unsupported"


@pytest.mark.asyncio
async def test_generate_image_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "resolve_image_model", lambda: None)
    with pytest.raises(R.LlmProviderError) as ei:
        await R.generate_image(prompt="x")
    assert ei.value.kind == "unsupported"


@pytest.mark.asyncio
async def test_generate_image_rejects_chat_only_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(R, "resolve_image_model", lambda: "deepseek-v4-flash")
    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R.settings, "llm_api_base", None)

    async def boom(**_kwargs):
        raise BadRequestError(
            message="This model does not support /images/generations",
            model="deepseek-v4-flash",
            llm_provider="openai",
        )

    monkeypatch.setattr(R.litellm, "aimage_generation", boom)
    with pytest.raises(R.LlmProviderError) as ei:
        await R.generate_image(prompt="HK cafe")
    assert ei.value.kind == "unsupported"
    assert ei.value.model is not None


@pytest.mark.asyncio
async def test_generate_image_returns_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(R, "resolve_image_model", lambda: "dall-e-3")
    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R.settings, "llm_api_base", None)

    item = MagicMock()
    item.url = "https://cdn.example/a.png"
    item.b64_json = None
    response = MagicMock()
    response.data = [item]
    monkeypatch.setattr(
        R.litellm, "aimage_generation", AsyncMock(return_value=response)
    )

    url = await R.generate_image(prompt="x")
    assert url == "https://cdn.example/a.png"
