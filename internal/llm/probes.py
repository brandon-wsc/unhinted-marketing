"""BYOK provider probes and model-list proxy (ADR 0020).

Decrypt happens here (and in the session resolver) only. Model-list cache is
in-process, keyed by provider row id, never persisted.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from internal.config import settings
from internal.llm.keys import ByokEncryptionError, decrypt_key
from internal.llm.ssrf import UnsafeUrlError, guarded_request
from internal.llm.resolve import VERTEX_AI_EXPRESS_API_BASE, gemini_catalog_id
from internal.llm.vertex_express import (
    VERTEX_EXPRESS_PROBE_MODEL,
    VERTEX_EXPRESS_PROBE_TIMEOUT_MS,
    VERTEX_EXPRESS_PROBE_WAIT_SECONDS,
    express_client,
)
from internal.memory.database import SessionLocal
from internal.memory.models import ByokModel, ByokProvider
from schemas.byok import ByokListedModel, ByokModelListProxy, ByokProbeResult

logger = logging.getLogger(__name__)

MODEL_LIST_CACHE_TTL_SECONDS = 60.0
_IMAGE_ID_MARKERS = (
    "dall-e",
    "dalle",
    "seedream",
    "flux",
    "imagen",
    "flash-image",
    "pro-image",
    "image-preview",
    "image-generation",
)

_cache_lock = threading.Lock()
_model_list_cache: dict[uuid.UUID, tuple[float, ByokModelListProxy]] = {}

OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"
ANTHROPIC_DEFAULT_BASE = "https://api.anthropic.com"
GEMINI_DEFAULT_MODELS = "https://generativelanguage.googleapis.com/v1beta/models"
VERTEX_AI_DEFAULT_MODELS = f"{VERTEX_AI_EXPRESS_API_BASE}/models"
# Express REST has no ListModels; documented ping is generateContent?key= (ADR 0021 §4).
VERTEX_AI_AUTH_PING = (
    f"{VERTEX_AI_EXPRESS_API_BASE}/models/{VERTEX_EXPRESS_PROBE_MODEL}:generateContent"
)


def with_google_query_key(url: str, api_key: str) -> str:
    """GCP console API keys are sent as ``?key=`` (not only ``x-goog-api-key``)."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["key"] = api_key
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def reset_model_list_cache() -> None:
    with _cache_lock:
        _model_list_cache.clear()


def invalidate_model_list_cache(provider_id: uuid.UUID) -> None:
    with _cache_lock:
        _model_list_cache.pop(provider_id, None)


def cache_get(provider_id: uuid.UUID) -> ByokModelListProxy | None:
    now = time.monotonic()
    with _cache_lock:
        hit = _model_list_cache.get(provider_id)
        if hit is None:
            return None
        expires, payload = hit
        if expires <= now:
            _model_list_cache.pop(provider_id, None)
            return None
        return payload


def cache_put(provider_id: uuid.UUID, payload: ByokModelListProxy) -> None:
    with _cache_lock:
        _model_list_cache[provider_id] = (
            time.monotonic() + MODEL_LIST_CACHE_TTL_SECONDS,
            payload,
        )


def infer_capability(model_id: str) -> tuple[str, str]:
    lowered = (model_id or "").lower()
    if any(marker in lowered for marker in _IMAGE_ID_MARKERS):
        return "image", "inferred"
    if "-image" in lowered or lowered.endswith("image"):
        return "image", "inferred"
    return "chat", "inferred"


def _gemini_capability_from_item(item: dict[str, Any], model_id: str) -> tuple[str, str] | None:
    methods = item.get("supportedGenerationMethods")
    lowered = (model_id or "").lower()
    if (
        lowered.startswith("imagen")
        or "-image" in lowered
        or lowered.endswith("image")
        or "image-generation" in lowered
    ):
        return "image", "provider_metadata"
    if isinstance(methods, list):
        names = {str(x).lower() for x in methods}
        if "predict" in names and "generatecontent" not in names:
            return "image", "provider_metadata"
        if methods:
            return "chat", "provider_metadata"
    return None


def capability_from_item(item: dict[str, Any], model_id: str) -> tuple[str, str]:
    gemini = _gemini_capability_from_item(item, model_id) if isinstance(item, dict) else None
    if gemini is not None and item.get("supportedGenerationMethods") is not None:
        return gemini
    arch = item.get("architecture") if isinstance(item, dict) else None
    if isinstance(arch, dict):
        from_meta = _capability_from_architecture(arch)
        if from_meta is not None:
            return from_meta, "provider_metadata"
    if gemini is not None:
        return gemini
    return infer_capability(model_id)


def _capability_from_architecture(arch: dict[str, Any]) -> str | None:
    outputs = arch.get("output_modalities")
    if isinstance(outputs, list) and outputs:
        lowered = {str(x).lower() for x in outputs}
        if "image" in lowered and "text" not in lowered:
            return "image"
        if "text" in lowered or "image" in lowered:
            return "chat"
    modality = str(arch.get("modality") or "").lower().replace(" ", "")
    if not modality:
        return None
    arrow = modality.rfind("->")
    if arrow >= 0:
        out = modality[arrow + 2 :]
        if out == "image" or out.startswith("image+"):
            return "image"
        return "chat"
    return None


def parse_model_list(payload: Any) -> list[ByokListedModel]:
    rows: list[Any]
    if isinstance(payload, dict):
        raw = payload.get("data")
        if not isinstance(raw, list):
            raw = payload.get("models")
        if not isinstance(raw, list):
            raw = payload.get("publisherModels")
        rows = raw if isinstance(raw, list) else []
    elif isinstance(payload, list):
        rows = payload
    else:
        return []
    out: list[ByokListedModel] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, str):
            model_id = item.strip()
            extra: dict[str, Any] = {}
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
            extra = item
        else:
            continue
        if model_id.lower().startswith("publishers/google/models/"):
            model_id = model_id.split("/", 3)[-1]
        elif model_id.lower().startswith("models/"):
            model_id = model_id.split("/", 1)[1]
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        cap, source = capability_from_item(extra, model_id)
        out.append(
            ByokListedModel(id=model_id, capability=cap, capability_source=source)  # type: ignore[arg-type]
        )
    return out


def models_list_url(provider: ByokProvider) -> str:
    ptype = (provider.provider_type or "").strip()
    if ptype == "gemini":
        return GEMINI_DEFAULT_MODELS
    if ptype == "vertex_ai":
        return VERTEX_AI_DEFAULT_MODELS
    base = (provider.api_base or "").strip().rstrip("/")
    if ptype == "anthropic":
        base = base or ANTHROPIC_DEFAULT_BASE
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"
    base = base or OPENAI_DEFAULT_BASE
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def images_models_url(provider: ByokProvider) -> str | None:
    """OpenRouter (and similar) keep image-only slugs on ``/images/models``.

    Seedream 4.5 is not on ``GET /models``. Gemini / Vertex / Anthropic have
    no such path — skip them.
    """
    ptype = (provider.provider_type or "").strip()
    if ptype not in ("openai", "openai_compatible"):
        return None
    models = models_list_url(provider)
    if not models.endswith("/models"):
        return None
    return f"{models[: -len('/models')]}/images/models"


def merge_listed_models(*groups: list[ByokListedModel]) -> list[ByokListedModel]:
    """Deduping concat; an image-catalog row wins over a chat-catalog duplicate."""
    by_id: dict[str, ByokListedModel] = {}
    for group in groups:
        for item in group:
            existing = by_id.get(item.id)
            if existing is None or (
                item.capability == "image" and existing.capability != "image"
            ):
                by_id[item.id] = item
    return list(by_id.values())


def probe_headers(provider: ByokProvider, api_key: str) -> dict[str, str]:
    ptype = (provider.provider_type or "").strip()
    if ptype == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if ptype == "gemini" or ptype == "vertex_ai":
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _kind_from_http(status_code: int) -> str:
    if status_code in (401, 403):
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if status_code == 404:
        return "unsupported"
    if 400 <= status_code < 500:
        return "bad_request"
    return "provider"


def _kind_from_exc(exc: BaseException) -> str:
    if isinstance(exc, UnsafeUrlError):
        return "connection"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection"
    if isinstance(exc, ByokEncryptionError):
        return "auth"
    text = str(exc).lower()
    if "timeout" in text:
        return "timeout"
    if "auth" in text or "unauthorized" in text or "invalid api key" in text:
        return "auth"
    return "provider"


async def fetch_provider_models(provider: ByokProvider) -> ByokModelListProxy:
    try:
        api_key = decrypt_key(provider.api_key_encrypted)
    except ByokEncryptionError:
        return ByokModelListProxy(fetchable=False)
    url = models_list_url(provider)
    if (provider.provider_type or "").strip() == "vertex_ai":
        url = with_google_query_key(url, api_key)
    try:
        response = await guarded_request(
            "GET",
            url,
            headers=probe_headers(provider, api_key),
        )
    except (UnsafeUrlError, httpx.HTTPError):
        logger.info("BYOK model list fetch failed for provider %s", provider.id, exc_info=True)
        return ByokModelListProxy(fetchable=False)
    if response.status_code >= 400:
        return ByokModelListProxy(fetchable=False)
    try:
        payload = response.json()
    except ValueError:
        return ByokModelListProxy(fetchable=False)
    models = parse_model_list(payload)
    if not models and not isinstance(payload, (dict, list)):
        return ByokModelListProxy(fetchable=False)
    extra = await _compat_image_models(provider, api_key)
    if extra:
        models = merge_listed_models(models, extra)
    return ByokModelListProxy(fetchable=True, models=models)


async def _compat_image_models(provider: ByokProvider, api_key: str) -> list[ByokListedModel]:
    url = images_models_url(provider)
    if not url:
        return []
    try:
        response = await guarded_request(
            "GET",
            url,
            headers=probe_headers(provider, api_key),
        )
    except (UnsafeUrlError, httpx.HTTPError):
        return []
    if response.status_code >= 400:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    return parse_model_list(payload)


async def cached_provider_models(provider: ByokProvider) -> ByokModelListProxy:
    hit = cache_get(provider.id)
    if hit is not None:
        return hit
    payload = await fetch_provider_models(provider)
    if payload.fetchable:
        cache_put(provider.id, payload)
    return payload


async def probe_provider_auth(provider: ByokProvider) -> ByokProbeResult:
    try:
        api_key = decrypt_key(provider.api_key_encrypted)
    except ByokEncryptionError:
        return ByokProbeResult(ok=False, error_kind="auth")
    ptype = (provider.provider_type or "").strip()
    if ptype == "vertex_ai":
        return await _probe_vertex_express_auth(api_key)
    url = models_list_url(provider)
    try:
        response = await guarded_request(
            "GET",
            url,
            headers=probe_headers(provider, api_key),
        )
    except (UnsafeUrlError, httpx.HTTPError, TimeoutError, OSError) as exc:
        return ByokProbeResult(ok=False, error_kind=_kind_from_exc(exc))
    if response.status_code >= 400:
        return ByokProbeResult(ok=False, error_kind=_kind_from_http(response.status_code))
    return ByokProbeResult(ok=True)


async def _probe_vertex_express_auth(api_key: str) -> ByokProbeResult:
    """Express auth via google-genai generateContent (not countTokens / raw HTTP)."""
    return await _probe_vertex_express_generate(api_key, VERTEX_EXPRESS_PROBE_MODEL)


async def _probe_vertex_express_generate(
    api_key: str,
    model_id: str,
    *,
    max_output_tokens: int | None = 1,
) -> ByokProbeResult:
    try:
        from google.genai import types
        from google.genai.errors import APIError
    except ImportError:
        return ByokProbeResult(ok=False, error_kind="unsupported")
    catalog = gemini_catalog_id(model_id)
    config_kwargs: dict[str, Any] = {"temperature": 0}
    if max_output_tokens is not None:
        config_kwargs["max_output_tokens"] = max_output_tokens
    try:
        client = express_client(api_key, timeout_ms=VERTEX_EXPRESS_PROBE_TIMEOUT_MS)
        await asyncio.wait_for(
            client.aio.models.generate_content(
                model=catalog,
                contents="ping",
                config=types.GenerateContentConfig(**config_kwargs),
            ),
            timeout=VERTEX_EXPRESS_PROBE_WAIT_SECONDS,
        )
    except APIError as exc:
        return ByokProbeResult(ok=False, error_kind=_kind_from_http(exc.code or 0))
    except (TimeoutError, httpx.TimeoutException):
        return ByokProbeResult(ok=False, error_kind="timeout")
    except Exception as exc:  # noqa: BLE001 — SDK wraps transport in many types
        return ByokProbeResult(ok=False, error_kind=_kind_from_exc(exc))
    return ByokProbeResult(ok=True)


async def probe_model_format(provider: ByokProvider, model_id: str) -> ByokProbeResult:
    """Catalog membership is advisory (ADR 0020 §7) — typed ids may be unlisted."""
    del model_id
    listing = await fetch_provider_models(provider)
    if listing.fetchable:
        return ByokProbeResult(ok=True)
    auth = await probe_provider_auth(provider)
    if not auth.ok:
        return auth
    return ByokProbeResult(ok=True)


async def probe_chat_model_live(provider: ByokProvider, model_id: str) -> ByokProbeResult:
    from internal.llm.resolve import effective_api_base, litellm_model_id
    from internal.llm.router import _wrap_provider_error, configure_litellm

    try:
        api_key = decrypt_key(provider.api_key_encrypted)
    except ByokEncryptionError:
        return ByokProbeResult(ok=False, error_kind="auth")
    ptype = (provider.provider_type or "").strip() or "openai"
    if ptype == "vertex_ai":
        return await _probe_vertex_express_generate(api_key, model_id)
    configure_litellm()
    api_base = effective_api_base(ptype, provider.api_base)
    model = litellm_model_id(model_id, ptype, api_base)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "timeout": settings.llm_timeout_seconds,
        "api_key": api_key,
    }
    if api_base:
        kwargs["api_base"] = api_base
    try:
        import litellm

        await litellm.acompletion(**kwargs)
    except Exception as exc:  # noqa: BLE001 — LiteLLM raises many provider types
        wrapped = _wrap_provider_error(exc, model=model)
        return ByokProbeResult(ok=False, error_kind=wrapped.kind)
    return ByokProbeResult(ok=True)


async def probe_image_model_live(provider: ByokProvider, model_id: str) -> ByokProbeResult:
    from internal.llm.resolve import effective_api_base, litellm_model_id
    from internal.llm.router import _wrap_provider_error, configure_litellm

    try:
        api_key = decrypt_key(provider.api_key_encrypted)
    except ByokEncryptionError:
        return ByokProbeResult(ok=False, error_kind="auth")
    ptype = (provider.provider_type or "").strip() or "openai"
    if ptype == "vertex_ai":
        return await _probe_vertex_express_generate(
            api_key, model_id, max_output_tokens=None
        )
    configure_litellm()
    api_base = effective_api_base(ptype, provider.api_base)
    model = litellm_model_id(model_id, ptype, api_base)
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": "ping",
        "size": "1024x1024",
        "timeout": settings.llm_timeout_seconds,
        "api_key": api_key,
    }
    if api_base:
        kwargs["api_base"] = api_base
    try:
        import litellm

        await litellm.aimage_generation(**kwargs)
    except Exception as exc:  # noqa: BLE001 — LiteLLM raises many provider types
        wrapped = _wrap_provider_error(exc, model=model)
        return ByokProbeResult(ok=False, error_kind=wrapped.kind)
    return ByokProbeResult(ok=True)


def apply_probe_result(row: ByokProvider | ByokModel, result: ByokProbeResult) -> None:
    if result.ok:
        row.last_verified_at = datetime.now(UTC)
        row.last_error_kind = None
    else:
        row.last_error_kind = result.error_kind


async def run_provider_auth_probe(provider_id: uuid.UUID, company_id: uuid.UUID) -> None:
    from internal.memory import repos

    try:
        async with SessionLocal() as db:
            provider = await repos.get_byok_provider(db, company_id, provider_id)
            if provider is None:
                return
            result = await probe_provider_auth(provider)
            apply_probe_result(provider, result)
            await db.commit()
    except Exception:
        logger.warning("BYOK provider auth probe failed (%s)", provider_id, exc_info=True)


async def run_model_format_probe(model_pk: uuid.UUID, company_id: uuid.UUID) -> None:
    from internal.memory import repos

    try:
        async with SessionLocal() as db:
            model = await repos.get_byok_model(db, company_id, model_pk)
            if model is None or model.provider is None:
                return
            result = await probe_model_format(model.provider, model.model_id)
            apply_probe_result(model, result)
            await db.commit()
    except Exception:
        logger.warning("BYOK model format probe failed (%s)", model_pk, exc_info=True)
