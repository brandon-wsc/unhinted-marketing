"""Compat image HTTP shape — catalog ``/images`` vs OpenAI ``/images/generations``.

``openai_compatible`` clones are not a brand. When ``GET {api_base}/images/models``
returns JSON, image generation uses ``POST {api_base}/images`` with the catalog
id. Otherwise LiteLLM keeps OpenAI ``/images/generations``. In-process cache is
keyed by normalized ``api_base`` (shape only, not a model list). Org bases go
through the SSRF helper; env ``LLM_API_BASE`` is operator-trusted.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

import httpx

from internal.llm.resolve import Source
from internal.llm.ssrf import UnsafeUrlError, guarded_request

logger = logging.getLogger(__name__)

CompatImageApi = Literal["dedicated", "generations"]

IMAGE_API_CACHE_TTL_SECONDS = 60.0

_cache_lock = threading.Lock()
_image_api_cache: dict[str, tuple[float, CompatImageApi]] = {}


def normalize_api_base(api_base: str) -> str:
    return (api_base or "").strip().rstrip("/")


def _cache_key(api_base: str) -> str:
    return normalize_api_base(api_base).lower()


def reset_compat_image_api_cache() -> None:
    with _cache_lock:
        _image_api_cache.clear()


def cache_get_image_api(api_base: str) -> CompatImageApi | None:
    key = _cache_key(api_base)
    now = time.monotonic()
    with _cache_lock:
        hit = _image_api_cache.get(key)
        if hit is None:
            return None
        expires, kind = hit
        if expires <= now:
            _image_api_cache.pop(key, None)
            return None
        return kind


def cache_put_image_api(api_base: str, kind: CompatImageApi) -> None:
    with _cache_lock:
        _image_api_cache[_cache_key(api_base)] = (
            time.monotonic() + IMAGE_API_CACHE_TTL_SECONDS,
            kind,
        )


def compat_images_models_url(api_base: str) -> str:
    base = normalize_api_base(api_base)
    if base.endswith("/models"):
        base = base[: -len("/models")]
    return f"{base}/images/models"


def compat_images_generate_url(api_base: str) -> str:
    base = normalize_api_base(api_base)
    if base.endswith("/models"):
        base = base[: -len("/models")]
    return f"{base}/images"


def bearer_headers(api_key: str | None) -> dict[str, str]:
    if not (api_key or "").strip():
        return {}
    return {"Authorization": f"Bearer {api_key.strip()}"}


async def compat_http(
    method: str,
    url: str,
    *,
    source: Source,
    api_key: str | None,
    json: Any = None,
    timeout: float,
) -> httpx.Response:
    """GET/POST a compat base. Org URLs are SSRF-pinned; env is trusted."""
    headers = bearer_headers(api_key)
    if source == "org":
        return await guarded_request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = await client.request(method.upper(), url, headers=headers, json=json)
        await response.aread()
        return response


def _json_body(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


async def resolve_compat_image_api(
    *,
    api_base: str,
    api_key: str | None,
    source: Source,
    timeout: float,
) -> CompatImageApi:
    """``dedicated`` when ``GET {base}/images/models`` returns JSON; else generations."""
    cached = cache_get_image_api(api_base)
    if cached is not None:
        return cached
    url = compat_images_models_url(api_base)
    kind: CompatImageApi = "generations"
    try:
        response = await compat_http(
            "GET",
            url,
            source=source,
            api_key=api_key,
            timeout=timeout,
        )
    except (UnsafeUrlError, httpx.HTTPError, TimeoutError, OSError):
        logger.info("compat images catalog probe failed for %s", url, exc_info=True)
        cache_put_image_api(api_base, kind)
        return kind
    if response.status_code < 400 and _json_body(response) is not None:
        kind = "dedicated"
    cache_put_image_api(api_base, kind)
    return kind


async def post_dedicated_image(
    *,
    api_base: str,
    api_key: str | None,
    source: Source,
    model: str,
    prompt: str,
    timeout: float,
    size: str | None = None,
) -> httpx.Response:
    """POST ``{base}/images``. Drop the DALL·E default ``1024x1024``.

    Catalog clones (Seedream) take ``1K`` / ``2K`` / ``4K`` or omit size.
    """
    body: dict[str, Any] = {"model": model, "prompt": prompt}
    sized = _dedicated_size(size)
    if sized:
        body["size"] = sized
    return await compat_http(
        "POST",
        compat_images_generate_url(api_base),
        source=source,
        api_key=api_key,
        json=body,
        timeout=timeout,
    )


def _dedicated_size(size: str | None) -> str | None:
    raw = (size or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in {"512", "1K", "2K", "4K"}:
        return upper
    if raw.lower() == "1024x1024":
        return None
    return raw
