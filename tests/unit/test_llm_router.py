"""LLM router helpers — provider error wrapping + stream aclose (no live network)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from litellm.exceptions import BadRequestError, NotFoundError

from internal.llm import recorder
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


@pytest.mark.asyncio
async def test_generate_image_normalizes_gemini_inline_b64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(R, "resolve_image_model", lambda: "imagen-3.0-generate-002")
    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R.settings, "llm_api_base", None)

    response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo"}},
                    ]
                }
            }
        ]
    }
    monkeypatch.setattr(
        R.litellm, "aimage_generation", AsyncMock(return_value=response)
    )
    url = await R.generate_image(prompt="x")
    assert url == "data:image/png;base64,iVBORw0KGgo"


def test_image_result_to_url_openai_and_gemini() -> None:
    item = MagicMock()
    item.url = "https://cdn.example/a.png"
    item.b64_json = None
    response = MagicMock()
    response.data = [item]
    response.candidates = None
    response.images = None
    assert R.image_result_to_url(response) == "https://cdn.example/a.png"
    assert R.image_result_to_url({"data": [{"b64_json": "/9j/xxxx"}]}) == (
        "data:image/jpeg;base64,/9j/xxxx"
    )
    assert R.image_result_to_url(
        {"candidates": [{"content": {"parts": [{"inline_data": {"data": "abc"}}]}}]}
    ) == "data:image/png;base64,abc"


class _FakeStream:
    def __init__(
        self,
        pieces: list[str],
        *,
        fail_after: int | None = None,
        usage: object | None = None,
    ):
        self.pieces = pieces
        self.fail_after = fail_after
        self.usage = usage
        self._usage_emitted = False
        self.aclose_calls = 0
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.fail_after is not None and self._i >= self.fail_after:
            raise asyncio.CancelledError()
        if self._i >= len(self.pieces):
            if self.usage is not None and not self._usage_emitted:
                self._usage_emitted = True
                chunk = MagicMock()
                chunk.choices = []
                chunk.usage = self.usage
                return chunk
            raise StopAsyncIteration
        text = self.pieces[self._i]
        self._i += 1
        chunk = MagicMock()
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk.choices = [choice]
        chunk.usage = None
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


# --- ADR 0005: call recording -----------------------------------------------


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list:
    sent: list = []
    monkeypatch.setattr(recorder, "submit", sent.append)
    return sent


def _stub_chat_provider(monkeypatch: pytest.MonkeyPatch, stream_or_response) -> None:
    async def fake_acompletion(**_kwargs):
        return stream_or_response

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)


@pytest.mark.asyncio
async def test_complete_json_records_ok_with_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8)
    stream = _FakeStream(['{"ok": true}'], usage=usage)
    _stub_chat_provider(monkeypatch, stream)

    raw = await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")

    assert raw == '{"ok": true}'
    assert len(recorded) == 1
    rec = recorded[0]
    assert rec.kind == "chat_json"
    assert rec.status == "ok"
    assert rec.model == "gpt-test"
    assert rec.response_text == '{"ok": true}'
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (3, 5, 8)
    assert rec.latency_ms is not None


@pytest.mark.asyncio
async def test_complete_json_requests_usage_chunk(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeStream(['{"ok": true}'])

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert captured.get("stream_options") == {"include_usage": True}


@pytest.mark.asyncio
async def test_complete_json_records_cancel(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    _stub_chat_provider(monkeypatch, _FakeStream(['{"a":'], fail_after=1))
    with pytest.raises(asyncio.CancelledError):
        await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert recorded[0].status == "cancelled"


@pytest.mark.asyncio
async def test_complete_text_records_ok_with_usage(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  hi  "))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )

    async def fake_acompletion(**_kwargs):
        return response

    monkeypatch.setattr(R, "configure_litellm", lambda: None)
    monkeypatch.setattr(R, "resolve_model", lambda _tier: "gpt-test")
    monkeypatch.setattr(R.settings, "llm_api_base", None)
    monkeypatch.setattr(R.litellm, "acompletion", fake_acompletion)

    text = await R.complete_text(tier=R.ModelTier.CHEAP, system="s", user="u")

    assert text == "hi"
    rec = recorded[0]
    assert rec.kind == "chat_text"
    assert rec.status == "ok"
    assert rec.response_text == "hi"
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (1, 2, 3)


@pytest.mark.asyncio
async def test_astream_text_records_cancel(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    _stub_chat_provider(monkeypatch, _FakeStream(["a", "b"], fail_after=1))

    gen = R.astream_text(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert await gen.__anext__() == "a"
    with pytest.raises(asyncio.CancelledError):
        await gen.__anext__()
    await gen.aclose()

    assert len(recorded) == 1
    assert recorded[0].status == "cancelled"


@pytest.mark.asyncio
async def test_record_picks_up_call_context(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    sid = uuid.uuid4()
    _stub_chat_provider(monkeypatch, _FakeStream(['{"ok": true}']))

    with recorder.call_context(
        caller="node:route_intent", node="route_intent", session_id=str(sid)
    ):
        await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")

    rec = recorded[0]
    assert rec.caller == "node:route_intent"
    assert rec.node == "route_intent"
    assert rec.session_id == sid


@pytest.mark.asyncio
async def test_generate_image_records_provider_error(
    monkeypatch: pytest.MonkeyPatch, recorded: list
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
    with pytest.raises(R.LlmProviderError):
        await R.generate_image(prompt="HK cafe")

    rec = recorded[0]
    assert rec.kind == "image"
    assert rec.status == "provider_error"
    assert rec.error["kind"] == "unsupported"
    assert rec.user_prompt == "HK cafe"


@pytest.mark.asyncio
async def test_complete_json_vertex_express_skips_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope

    vertex = ResolvedModel(
        model_id="gemini-2.5-flash",
        api_key="AQ.test",
        api_base=None,
        provider_type="vertex_ai",
        source="org",
        key_last4="test",
    )
    called: dict[str, object] = {}

    class FakeModels:
        async def generate_content_stream(self, **kwargs):
            called["stream"] = kwargs

            async def gen():
                yield SimpleNamespace(text='{"ok": true}', usage_metadata=None)

            return gen()

    class FakeClient:
        aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(R, "express_client", lambda *_a, **_k: FakeClient())

    async def boom(**_kwargs):
        raise AssertionError("LiteLLM must not run for vertex_ai")

    monkeypatch.setattr(R.litellm, "acompletion", boom)

    with llm_bundle_scope(CompanyLlmBundle(cheap=vertex)):
        raw = await R.complete_json(tier=R.ModelTier.CHEAP, system="s", user="u")
    assert raw == '{"ok": true}'
    assert called["stream"]["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_image_vertex_express_skips_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.resolve import CompanyLlmBundle, ResolvedModel, llm_bundle_scope

    vertex = ResolvedModel(
        model_id="gemini-2.5-flash-image",
        api_key="AQ.test",
        api_base=None,
        provider_type="vertex_ai",
        source="org",
        key_last4="test",
    )
    response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo"}},
                    ]
                }
            }
        ]
    }

    class FakeModels:
        async def generate_content(self, **_kwargs):
            return response

    class FakeClient:
        aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(R, "express_client", lambda *_a, **_k: FakeClient())

    async def boom(**_kwargs):
        raise AssertionError("LiteLLM must not run for vertex_ai")

    monkeypatch.setattr(R.litellm, "aimage_generation", boom)

    with llm_bundle_scope(CompanyLlmBundle(image=vertex)):
        url = await R.generate_image(prompt="HK cafe")
    assert url == "data:image/png;base64,iVBORw0KGgo"


@pytest.mark.asyncio
async def test_generate_image_config_error_not_recorded(
    monkeypatch: pytest.MonkeyPatch, recorded: list
) -> None:
    # No provider call happens when the image model is unset — nothing to record.
    monkeypatch.setattr(R, "resolve_image_model", lambda: None)
    with pytest.raises(R.LlmProviderError):
        await R.generate_image(prompt="x")
    assert recorded == []
