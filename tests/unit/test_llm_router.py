"""LLM router helpers — provider error wrapping + stream aclose (no live network)."""

from __future__ import annotations

import asyncio
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


class _FakeStream:
    def __init__(self, pieces: list[str], *, fail_after: int | None = None):
        self.pieces = pieces
        self.fail_after = fail_after
        self.aclose_calls = 0
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.fail_after is not None and self._i >= self.fail_after:
            raise asyncio.CancelledError()
        if self._i >= len(self.pieces):
            raise StopAsyncIteration
        text = self.pieces[self._i]
        self._i += 1
        chunk = MagicMock()
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk.choices = [choice]
        return chunk

    async def aclose(self):
        self.aclose_calls += 1


@pytest.mark.asyncio
async def test_astream_text_aclose_on_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(["Hel", "lo"])

    async def fake_acompletion(**_kwargs):
        return stream

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    parts = [
        p
        async for p in R.astream_text(
            tier=R.ModelTier.CHEAP, system="s", user="u"
        )
    ]
    assert "".join(parts) == "Hello"
    assert stream.aclose_calls == 1


@pytest.mark.asyncio
async def test_astream_text_aclose_on_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(["a", "b", "c"], fail_after=1)

    async def fake_acompletion(**_kwargs):
        return stream

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    gen = R.astream_text(tier=R.ModelTier.CHEAP, system="s", user="u")
    first = await gen.__anext__()
    assert first == "a"
    with pytest.raises(asyncio.CancelledError):
        await gen.__anext__()
    # Generator cleanup (aclose finally) runs when the generator is closed.
    await gen.aclose()
    assert stream.aclose_calls >= 1


@pytest.mark.asyncio
async def test_complete_json_streams_and_aclose(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(['{"ok":', " true}"])

    async def fake_acompletion(**kwargs):
        assert kwargs.get("stream") is True
        assert kwargs.get("response_format") == {"type": "json_object"}
        return stream

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    raw = await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert raw == '{"ok": true}'
    assert stream.aclose_calls == 1


@pytest.mark.asyncio
async def test_complete_json_aclose_on_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(['{"a":', "1}"], fail_after=1)

    async def fake_acompletion(**_kwargs):
        return stream

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    with pytest.raises(asyncio.CancelledError):
        await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert stream.aclose_calls == 1
