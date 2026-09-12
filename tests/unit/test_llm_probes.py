"""Parse + cache helpers for BYOK model-list proxy (no live network)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from internal.llm.probes import (
    cache_get,
    cache_put,
    capability_from_item,
    infer_capability,
    invalidate_model_list_cache,
    models_list_url,
    parse_model_list,
    reset_model_list_cache,
)
from schemas.byok import ByokModelListProxy


def test_infer_capability_image_markers() -> None:
    assert infer_capability("bytedance-seed/seedream-4.5") == ("image", "inferred")
    assert infer_capability("dall-e-3") == ("image", "inferred")
    assert infer_capability("gemini-2.5-flash-image") == ("image", "inferred")
    assert infer_capability("gemini-2.0-flash-preview-image-generation") == ("image", "inferred")
    assert infer_capability("gpt-4o") == ("chat", "inferred")
    assert infer_capability("gemini-2.5-flash") == ("chat", "inferred")


def test_capability_from_openrouter_architecture() -> None:
    chat = capability_from_item(
        {"architecture": {"modality": "text+image->text", "output_modalities": ["text"]}},
        "openai/gpt-4o",
    )
    assert chat == ("chat", "provider_metadata")
    image = capability_from_item(
        {"architecture": {"modality": "text->image", "output_modalities": ["image"]}},
        "bytedance/seedream",
    )
    assert image == ("image", "provider_metadata")


def test_parse_model_list_openai_shape() -> None:
    models = parse_model_list({"data": [{"id": "gpt-4o-mini"}, {"id": "dall-e-3"}]})
    by_id = {m.id: m for m in models}
    assert by_id["gpt-4o-mini"].capability == "chat"
    assert by_id["dall-e-3"].capability == "image"
    assert by_id["dall-e-3"].capability_source == "inferred"


def test_cache_keyed_by_provider_id() -> None:
    reset_model_list_cache()
    a, b = uuid4(), uuid4()
    payload_a = ByokModelListProxy(
        fetchable=True, models=[{"id": "org-a", "capability": "chat", "capability_source": "manual"}]
    )
    payload_b = ByokModelListProxy(
        fetchable=True, models=[{"id": "org-b", "capability": "chat", "capability_source": "manual"}]
    )
    cache_put(a, payload_a)
    cache_put(b, payload_b)
    assert cache_get(a).models[0].id == "org-a"
    assert cache_get(b).models[0].id == "org-b"
    invalidate_model_list_cache(a)
    assert cache_get(a) is None
    assert cache_get(b).models[0].id == "org-b"


def test_models_list_url_defaults() -> None:
    class P:
        provider_type = "openai"
        api_base = None

    assert models_list_url(P()) == "https://api.openai.com/v1/models"  # type: ignore[arg-type]

    class A:
        provider_type = "anthropic"
        api_base = None

    assert models_list_url(A()) == "https://api.anthropic.com/v1/models"  # type: ignore[arg-type]

    class C:
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"

    assert models_list_url(C()) == "https://openrouter.ai/api/v1/models"  # type: ignore[arg-type]

    class G:
        provider_type = "gemini"
        api_base = "https://should-ignore.example"

    assert models_list_url(G()) == (
        "https://generativelanguage.googleapis.com/v1beta/models"
    )  # type: ignore[arg-type]

    class V:
        provider_type = "vertex_ai"
        api_base = "https://should-ignore.example"

    assert models_list_url(V()) == (
        "https://aiplatform.googleapis.com/v1/publishers/google/models"
    )  # type: ignore[arg-type]


def test_images_models_url_compat_only() -> None:
    from internal.llm.probes import images_models_url

    class C:
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"

    assert images_models_url(C()) == (  # type: ignore[arg-type]
        "https://openrouter.ai/api/v1/images/models"
    )

    class Openai:
        provider_type = "openai"
        api_base = None

    assert images_models_url(Openai()) == "https://api.openai.com/v1/images/models"  # type: ignore[arg-type]

    class V:
        provider_type = "vertex_ai"
        api_base = None

    assert images_models_url(V()) is None  # type: ignore[arg-type]


def test_merge_listed_models_image_catalog_wins() -> None:
    from internal.llm.probes import merge_listed_models
    from schemas.byok import ByokListedModel

    chat = [
        ByokListedModel(id="gpt-4o", capability="chat", capability_source="inferred"),
        ByokListedModel(id="seedream", capability="chat", capability_source="inferred"),
    ]
    images = [
        ByokListedModel(
            id="bytedance-seed/seedream-4.5",
            capability="image",
            capability_source="provider_metadata",
        ),
        ByokListedModel(
            id="seedream", capability="image", capability_source="provider_metadata"
        ),
    ]
    merged = merge_listed_models(chat, images)
    by_id = {m.id: m for m in merged}
    assert by_id["gpt-4o"].capability == "chat"
    assert by_id["seedream"].capability == "image"
    assert by_id["bytedance-seed/seedream-4.5"].capability == "image"


def test_parse_model_list_openrouter_image_catalog() -> None:
    models = parse_model_list(
        {
            "data": [
                {
                    "id": "bytedance-seed/seedream-4.5",
                    "architecture": {"output_modalities": ["image"]},
                }
            ]
        }
    )
    assert models[0].id == "bytedance-seed/seedream-4.5"
    assert models[0].capability == "image"
    assert models[0].capability_source == "provider_metadata"


@pytest.mark.asyncio
async def test_probe_model_format_allows_unlisted_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm.probes import probe_model_format
    from schemas.byok import ByokListedModel, ByokModelListProxy

    async def fake_fetch(_provider: object) -> ByokModelListProxy:
        return ByokModelListProxy(
            fetchable=True,
            models=[
                ByokListedModel(id="gpt-4o", capability="chat", capability_source="inferred")
            ],
        )

    monkeypatch.setattr("internal.llm.probes.fetch_provider_models", fake_fetch)

    class P:
        provider_type = "openai_compatible"

    result = await probe_model_format(P(), "bytedance-seed/seedream-4.5")  # type: ignore[arg-type]
    assert result.ok


@pytest.mark.asyncio
async def test_fetch_provider_models_merges_images_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from internal.llm.probes import fetch_provider_models, reset_model_list_cache

    reset_model_list_cache()
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "sk-or")

    async def fake_guarded(method: str, url: str, **_kwargs: object) -> SimpleNamespace:
        if url.endswith("/images/models"):
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "data": [
                        {
                            "id": "bytedance-seed/seedream-4.5",
                            "architecture": {"output_modalities": ["image"]},
                        }
                    ]
                },
            )
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": "gpt-4o"}]},
        )

    monkeypatch.setattr("internal.llm.probes.guarded_request", fake_guarded)

    class P:
        id = uuid4()
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"
        api_key_encrypted = "cipher"

    payload = await fetch_provider_models(P())  # type: ignore[arg-type]
    ids = {m.id: m.capability for m in payload.models}
    assert payload.fetchable
    assert ids["gpt-4o"] == "chat"
    assert ids["bytedance-seed/seedream-4.5"] == "image"


@pytest.mark.asyncio
async def test_fetch_provider_models_keeps_chat_catalog_if_images_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from internal.llm.probes import fetch_provider_models, reset_model_list_cache

    reset_model_list_cache()
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "sk-or")

    async def fake_guarded(_method: str, url: str, **_kwargs: object) -> SimpleNamespace:
        if url.endswith("/images/models"):
            return SimpleNamespace(status_code=404, json=lambda: {"error": "nope"})
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": "gpt-4o"}]},
        )

    monkeypatch.setattr("internal.llm.probes.guarded_request", fake_guarded)

    class P:
        id = uuid4()
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"
        api_key_encrypted = "cipher"

    payload = await fetch_provider_models(P())  # type: ignore[arg-type]
    assert payload.fetchable
    assert [m.id for m in payload.models] == ["gpt-4o"]


@pytest.mark.asyncio
async def test_fetch_vertex_ai_does_not_hit_images_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from internal.llm.probes import fetch_provider_models, reset_model_list_cache

    reset_model_list_cache()
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "AQ.secret")
    urls: list[str] = []

    async def fake_guarded(_method: str, url: str, **_kwargs: object) -> SimpleNamespace:
        urls.append(url)
        return SimpleNamespace(status_code=404, json=lambda: {})

    monkeypatch.setattr("internal.llm.probes.guarded_request", fake_guarded)

    class P:
        id = uuid4()
        provider_type = "vertex_ai"
        api_base = None
        api_key_encrypted = "cipher"

    payload = await fetch_provider_models(P())  # type: ignore[arg-type]
    assert payload.fetchable is False
    assert urls
    assert all("/images/models" not in u for u in urls)


@pytest.mark.asyncio
async def test_probe_model_format_unfetchable_falls_back_to_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.probes import probe_model_format
    from schemas.byok import ByokModelListProxy, ByokProbeResult

    async def fake_fetch(_provider: object) -> ByokModelListProxy:
        return ByokModelListProxy(fetchable=False, models=[])

    async def fake_auth(_provider: object) -> ByokProbeResult:
        return ByokProbeResult(ok=False, error_kind="auth")

    monkeypatch.setattr("internal.llm.probes.fetch_provider_models", fake_fetch)
    monkeypatch.setattr("internal.llm.probes.probe_provider_auth", fake_auth)

    class P:
        provider_type = "vertex_ai"

    result = await probe_model_format(P(), "bytedance-seed/seedream-4.5")  # type: ignore[arg-type]
    assert not result.ok
    assert result.error_kind == "auth"


@pytest.mark.asyncio
async def test_probe_chat_model_live_vertex_skips_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from internal.llm.probes import probe_chat_model_live

    called: dict[str, Any] = {}

    class FakeModels:
        async def generate_content(self, **kwargs: Any) -> object:
            called["generate_content"] = kwargs
            return object()

    class FakeClient:
        aio = SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(
        "internal.llm.probes.express_client",
        lambda *_a, **_k: FakeClient(),
    )
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "AQ.secret")

    async def boom(**_kwargs: object) -> None:
        raise AssertionError("LiteLLM must not run for vertex_ai")

    monkeypatch.setattr("litellm.acompletion", boom)

    class P:
        provider_type = "vertex_ai"
        api_key_encrypted = "cipher"
        api_base = None

    result = await probe_chat_model_live(P(), "gemini-2.5-flash")  # type: ignore[arg-type]
    assert result.ok
    assert called["generate_content"]["model"] == "gemini-2.5-flash"


def test_parse_model_list_gemini_shape() -> None:
    models = parse_model_list(
        {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/imagen-3.0-generate-002",
                    "supportedGenerationMethods": ["predict"],
                },
                {
                    "name": "models/gemini-2.5-flash-image",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        }
    )
    by_id = {m.id: m for m in models}
    assert "models/gemini-2.5-flash" not in by_id
    assert by_id["gemini-2.5-flash"].capability == "chat"
    assert by_id["gemini-2.5-flash"].capability_source == "provider_metadata"
    assert by_id["imagen-3.0-generate-002"].capability == "image"
    assert by_id["imagen-3.0-generate-002"].capability_source == "provider_metadata"
    assert by_id["gemini-2.5-flash-image"].capability == "image"


def test_parse_model_list_vertex_publisher_shape() -> None:
    models = parse_model_list(
        {
            "publisherModels": [
                {"name": "publishers/google/models/gemini-2.5-flash"},
                {"name": "publishers/google/models/gemini-2.5-flash-image"},
            ]
        }
    )
    by_id = {m.id: m for m in models}
    assert "publishers/google/models/gemini-2.5-flash" not in by_id
    assert by_id["gemini-2.5-flash"].capability == "chat"
    assert by_id["gemini-2.5-flash-image"].capability == "image"


def test_probe_headers_gemini() -> None:
    from internal.llm.probes import probe_headers

    class G:
        provider_type = "gemini"

    assert probe_headers(G(), "AIza-x") == {"x-goog-api-key": "AIza-x"}  # type: ignore[arg-type]

    class V:
        provider_type = "vertex_ai"

    assert probe_headers(V(), "AQ.x") == {"x-goog-api-key": "AQ.x"}  # type: ignore[arg-type]


def test_with_google_query_key() -> None:
    from internal.llm.probes import VERTEX_AI_AUTH_PING, with_google_query_key

    url = with_google_query_key(
        "https://aiplatform.googleapis.com/v1/publishers/google/models",
        "AQ.secret",
    )
    assert url.startswith("https://aiplatform.googleapis.com/v1/publishers/google/models?")
    assert "key=AQ.secret" in url
    ping = with_google_query_key(VERTEX_AI_AUTH_PING, "AQ.secret")
    assert ping.endswith("generateContent?key=AQ.secret") or "generateContent?" in ping
    assert "key=AQ.secret" in ping


@pytest.mark.asyncio
async def test_vertex_ai_auth_probe_uses_google_genai_express_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from internal.llm.probes import probe_provider_auth
    from internal.llm.vertex_express import VERTEX_EXPRESS_PROBE_TIMEOUT_MS

    called: dict[str, Any] = {}

    class FakeModels:
        async def generate_content(self, **kwargs: Any) -> object:
            called["generate_content"] = kwargs
            return object()

    class FakeAio:
        models = FakeModels()

    class FakeClient:
        aio = FakeAio()

    def fake_express_client(api_key: str, *, timeout_ms: int) -> FakeClient:
        called["client"] = {"api_key": api_key, "timeout_ms": timeout_ms, "vertexai": True}
        return FakeClient()

    monkeypatch.setattr("internal.llm.probes.express_client", fake_express_client)
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "AQ.secret")

    class P:
        provider_type = "vertex_ai"
        api_key_encrypted = "cipher"
        api_base = None

    result = await probe_provider_auth(P())  # type: ignore[arg-type]
    assert result.ok
    assert called["client"]["vertexai"] is True
    assert called["client"]["api_key"] == "AQ.secret"
    assert called["client"]["timeout_ms"] == VERTEX_EXPRESS_PROBE_TIMEOUT_MS
    assert called["generate_content"]["model"] == "gemini-2.5-flash"
    config = called["generate_content"]["config"]
    assert config.max_output_tokens == 1


def test_express_client_vertexai_true_no_project(monkeypatch: pytest.MonkeyPatch) -> None:
    from internal.llm import vertex_express as VE

    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(VE.genai, "Client", FakeClient)
    client = VE.express_client("AQ.secret", timeout_ms=VE.VERTEX_EXPRESS_PROBE_TIMEOUT_MS)
    assert isinstance(client, FakeClient)
    assert captured["vertexai"] is True
    assert captured["api_key"] == "AQ.secret"
    assert "project" not in captured
    assert "location" not in captured
    assert captured["http_options"].timeout == VE.VERTEX_EXPRESS_PROBE_TIMEOUT_MS
    assert captured["http_options"].retry_options.attempts == 1


@pytest.mark.asyncio
async def test_probe_image_model_live_dedicated_skips_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from internal.llm.image_api import reset_compat_image_api_cache
    from internal.llm.probes import probe_image_model_live

    reset_compat_image_api_cache()
    monkeypatch.setattr("internal.llm.probes.decrypt_key", lambda _: "sk-org")
    monkeypatch.setattr(
        "internal.llm.image_api.resolve_compat_image_api",
        AsyncMock(return_value="dedicated"),
    )

    posted: dict[str, object] = {}

    async def fake_post(**kwargs: object) -> httpx.Response:
        posted.update(kwargs)
        return httpx.Response(
            200,
            json={"data": [{"b64_json": "abc"}]},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/images"),
        )

    monkeypatch.setattr("internal.llm.image_api.post_dedicated_image", fake_post)

    async def boom(**_kwargs: object) -> None:
        raise AssertionError("LiteLLM must not run")

    monkeypatch.setattr("litellm.aimage_generation", boom)

    class P:
        provider_type = "openai_compatible"
        api_base = "https://openrouter.ai/api/v1"
        api_key_encrypted = "cipher"

    result = await probe_image_model_live(P(), "bytedance-seed/seedream-4.5")  # type: ignore[arg-type]
    assert result.ok is True
    assert posted["model"] == "bytedance-seed/seedream-4.5"
