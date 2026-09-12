"""Compat image path picker — catalog shape, not an OpenRouter type."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from internal.llm import image_api as I


@pytest.fixture(autouse=True)
def _clear_image_api_cache() -> Iterator[None]:
    I.reset_compat_image_api_cache()
    yield
    I.reset_compat_image_api_cache()


def test_compat_image_urls() -> None:
    base = "https://openrouter.ai/api/v1"
    assert I.compat_images_models_url(base) == ("https://openrouter.ai/api/v1/images/models")
    assert I.compat_images_generate_url(base) == "https://openrouter.ai/api/v1/images"
    assert I.compat_images_models_url(f"{base}/models") == (
        "https://openrouter.ai/api/v1/images/models"
    )


@pytest.mark.asyncio
async def test_picker_200_json_is_dedicated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_http(method: str, url: str, **_kwargs: Any) -> httpx.Response:
        calls.append((method, url))
        return httpx.Response(
            200,
            json={"data": []},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(I, "compat_http", fake_http)
    kind = await I.resolve_compat_image_api(
        api_base="https://openrouter.ai/api/v1",
        api_key="sk",
        source="env",
        timeout=8.0,
    )
    assert kind == "dedicated"
    assert calls == [
        ("GET", "https://openrouter.ai/api/v1/images/models"),
    ]
    kind2 = await I.resolve_compat_image_api(
        api_base="https://openrouter.ai/api/v1",
        api_key="sk",
        source="env",
        timeout=8.0,
    )
    assert kind2 == "dedicated"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_picker_404_is_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_http(method: str, url: str, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(404, text="nope", request=httpx.Request(method, url))

    monkeypatch.setattr(I, "compat_http", fake_http)
    kind = await I.resolve_compat_image_api(
        api_base="https://api.deepseek.com",
        api_key="sk",
        source="env",
        timeout=8.0,
    )
    assert kind == "generations"


@pytest.mark.asyncio
async def test_picker_invalid_json_is_generations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_http(method: str, url: str, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(200, text="<html>", request=httpx.Request(method, url))

    monkeypatch.setattr(I, "compat_http", fake_http)
    kind = await I.resolve_compat_image_api(
        api_base="https://example.invalid/v1",
        api_key="sk",
        source="env",
        timeout=8.0,
    )
    assert kind == "generations"


@pytest.mark.asyncio
async def test_org_compat_http_uses_guarded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_guarded(method: str, url: str, **_kwargs: Any) -> httpx.Response:
        calls.append(f"{method}:{url}")
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(I, "guarded_request", fake_guarded)

    class BoomClient:
        def __init__(self, **_kwargs: Any) -> None:
            raise AssertionError("env httpx must not run for org")

    monkeypatch.setattr(I.httpx, "AsyncClient", BoomClient)
    response = await I.compat_http(
        "GET",
        "https://openrouter.ai/api/v1/images/models",
        source="org",
        api_key="sk-org",
        timeout=8.0,
    )
    assert response.status_code == 200
    assert calls == ["GET:https://openrouter.ai/api/v1/images/models"]


@pytest.mark.asyncio
async def test_env_compat_http_skips_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_guarded(*_a: Any, **_k: Any) -> httpx.Response:
        raise AssertionError("org SSRF must not run for env")

    monkeypatch.setattr(I, "guarded_request", fake_guarded)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-env"
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(**kwargs)

    monkeypatch.setattr(I.httpx, "AsyncClient", fake_client)
    response = await I.compat_http(
        "GET",
        "http://127.0.0.1:4000/v1/images/models",
        source="env",
        api_key="sk-env",
        timeout=8.0,
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_dedicated_size_drops_dalle_default() -> None:
    assert I._dedicated_size(None) is None
    assert I._dedicated_size("1024x1024") is None
    assert I._dedicated_size("2K") == "2K"
    assert I._dedicated_size("2048x2048") == "2048x2048"


@pytest.mark.asyncio
async def test_post_dedicated_image_omits_dalle_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bodies: list[dict[str, object]] = []

    async def fake_http(method: str, url: str, **kwargs: Any) -> httpx.Response:
        bodies.append(kwargs.get("json") or {})
        return httpx.Response(200, json={"data": []}, request=httpx.Request(method, url))

    monkeypatch.setattr(I, "compat_http", fake_http)
    await I.post_dedicated_image(
        api_base="https://openrouter.ai/api/v1",
        api_key="sk",
        source="env",
        model="bytedance-seed/seedream-4.5",
        prompt="a rabbit",
        timeout=8.0,
        size="1024x1024",
    )
    assert bodies == [
        {"model": "bytedance-seed/seedream-4.5", "prompt": "a rabbit"},
    ]
    await I.post_dedicated_image(
        api_base="https://openrouter.ai/api/v1",
        api_key="sk",
        source="env",
        model="bytedance-seed/seedream-4.5",
        prompt="a rabbit",
        timeout=8.0,
        size="2K",
    )
    assert bodies[-1]["size"] == "2K"
