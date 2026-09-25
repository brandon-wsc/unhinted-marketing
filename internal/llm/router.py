"""LiteLLM routing — credentials from the per-turn resolver (ADR 0020)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from enum import Enum
from typing import Any

# Import before litellm: some litellm builds hit KeyError on pydantic.root_model
# during RootModel generic construction if that module is not loaded yet.
import pydantic.root_model  # noqa: F401
import litellm
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    Timeout,
    UnsupportedParamsError,
)

import httpx

from internal.config import settings
from internal.llm.image_api import post_dedicated_image, resolve_compat_image_api
from internal.llm.recorder import track
from internal.llm.resolve import (
    bundle_has_credentials,
    effective_api_base,
    env_has_llm_credentials,
    gemini_catalog_id,
    litellm_model_id,
    openai_compat_model_id,
    resolve_image,
    resolve_llm_model,
)
from internal.llm.ssrf import BYOK_PROBE_TIMEOUT_SECONDS, UnsafeUrlError
from internal.llm.vertex_express import express_client

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    CHEAP = "cheap"
    MEDIUM = "medium"
    STRONG = "strong"


class LlmProviderError(Exception):
    """User-facing provider/transport failure (timeout, auth, bad model, etc.)."""

    def __init__(self, message: str, *, model: str | None = None, kind: str = "provider"):
        super().__init__(message)
        self.message = message
        self.model = model
        self.kind = kind

    def to_event_data(self) -> dict:
        data: dict = {"error": self.message, "kind": self.kind}
        if self.model:
            data["model"] = self.model
        return data


def configure_litellm() -> None:
    litellm.drop_params = True


def has_llm_credentials() -> bool:
    return env_has_llm_credentials() or bundle_has_credentials()


def resolve_model(tier: ModelTier) -> str:
    return resolve_llm_model(tier).model_id


def resolve_image_model() -> str | None:
    """Configured image-gen model, or None when unset / blank."""
    resolved = resolve_image()
    if resolved is None:
        return None
    raw = (resolved.model_id or "").strip()
    return raw or None


def _litellm_model(
    model: str,
    api_base: str | None = None,
    provider_type: str = "openai",
) -> str:
    """LiteLLM id: native ``gemini/`` for AI Studio; ``openai/`` when a compat base is set.

    ``vertex_ai`` is not LiteLLM — use ``express_client`` instead.
    """
    return litellm_model_id(model, provider_type, api_base)


def _base_kwargs(tier: ModelTier, temperature: float) -> dict:
    configure_litellm()
    resolved = resolve_llm_model(tier)
    raw = resolve_model(tier)
    api_base = effective_api_base(resolved.provider_type, resolved.api_base)
    model = _litellm_model(raw, api_base, resolved.provider_type)
    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "timeout": settings.llm_timeout_seconds,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if resolved.api_key:
        kwargs["api_key"] = resolved.api_key
    return kwargs


def _vertex_timeout_ms() -> int:
    return max(1, int(settings.llm_timeout_seconds * 1000))


def _wrap_google_genai_error(exc: BaseException, *, model: str) -> LlmProviderError:
    try:
        from google.genai.errors import APIError
    except ImportError:
        APIError = ()  # type: ignore[misc, assignment]
    if isinstance(exc, APIError):
        code = int(getattr(exc, "code", 0) or 0)
        if code in (401, 403):
            return LlmProviderError(
                f"LLM authentication failed for {model}. Check the Vertex Express API key.",
                model=model,
                kind="auth",
            )
        if code == 429:
            return LlmProviderError(
                f"LLM rate limit hit for {model}. Try again shortly.",
                model=model,
                kind="rate_limit",
            )
        if code == 404:
            return LlmProviderError(
                f"Model {model} was not found on Vertex Express. Check the model id.",
                model=model,
                kind="unsupported",
            )
        if 400 <= code < 500:
            return LlmProviderError(
                f"LLM rejected the request for {model} (bad model id or unsupported params).",
                model=model,
                kind="bad_request",
            )
        return LlmProviderError(
            f"LLM call failed for {model}: {str(exc)[:240]}",
            model=model,
            kind="provider",
        )
    if isinstance(exc, TimeoutError):
        return LlmProviderError(
            f"LLM timed out talking to {model}. Check network and that the Express key is valid.",
            model=model,
            kind="timeout",
        )
    return _wrap_provider_error(exc, model=model)


async def _vertex_astream_text(
    *,
    resolved: Any,
    system: str,
    user: str,
    temperature: float,
    json_mode: bool = False,
    usage_sink: Any = None,
    on_first_token: Any = None,
) -> AsyncIterator[str]:
    from google.genai import types
    from google.genai.errors import APIError

    model = gemini_catalog_id(resolved.model_id)
    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if system:
        config_kwargs["system_instruction"] = system
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    stream: Any = None
    try:
        client = express_client(resolved.api_key or "", timeout_ms=_vertex_timeout_ms())
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        first = True
        async for chunk in stream:
            if usage_sink is not None:
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None:
                    usage_sink(usage)
            piece = getattr(chunk, "text", None)
            if piece:
                if first:
                    first = False
                    if on_first_token is not None:
                        on_first_token()
                yield str(piece)
    except asyncio.CancelledError:
        raise
    except APIError as exc:
        raise _wrap_google_genai_error(exc, model=model) from exc
    except Exception as exc:
        if _is_provider_failure(exc) or isinstance(exc, TimeoutError):
            raise _wrap_google_genai_error(exc, model=model) from exc
        raise
    finally:
        await _aclose_stream(stream)


async def _vertex_complete_text(
    *,
    resolved: Any,
    system: str,
    user: str,
    temperature: float,
    usage_sink: Any = None,
) -> str:
    from google.genai import types
    from google.genai.errors import APIError

    model = gemini_catalog_id(resolved.model_id)
    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if system:
        config_kwargs["system_instruction"] = system
    try:
        client = express_client(resolved.api_key or "", timeout_ms=_vertex_timeout_ms())
        response = await client.aio.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except APIError as exc:
        raise _wrap_google_genai_error(exc, model=model) from exc
    except Exception as exc:
        if _is_provider_failure(exc) or isinstance(exc, TimeoutError):
            raise _wrap_google_genai_error(exc, model=model) from exc
        raise
    if usage_sink is not None:
        usage_sink(getattr(response, "usage_metadata", None))
    text = getattr(response, "text", None)
    return str(text).strip() if text else ""


async def _vertex_generate_image(*, resolved: Any, prompt: str) -> Any:
    from google.genai.errors import APIError

    model = gemini_catalog_id(resolved.model_id)
    try:
        client = express_client(resolved.api_key or "", timeout_ms=_vertex_timeout_ms())
        return await client.aio.models.generate_content(
            model=model,
            contents=prompt,
        )
    except APIError as exc:
        raise _wrap_google_genai_error(exc, model=model) from exc
    except Exception as exc:
        if _is_provider_failure(exc) or isinstance(exc, TimeoutError):
            raise _wrap_google_genai_error(exc, model=model) from exc
        raise


def _looks_like_unsupported_image(text: str) -> bool:
    lower = text.lower()
    return any(
        tip in lower
        for tip in (
            "does not support",
            "doesn't support",
            "not support",
            "unsupported",
            "not supported",
            "image_generation not",
            "no endpoint",
            "unknown model for image",
            "not a valid model",
            "is not a valid model",
            "model_not_found",
            "does not exist",
            "invalid model",
            "not available for image",
            "images generations",
            "/images/generations",
        )
    )


def _wrap_provider_error(exc: BaseException, *, model: str) -> LlmProviderError:
    if isinstance(exc, Timeout):
        return LlmProviderError(
            f"LLM timed out talking to {model}. Check network, LLM_API_BASE, and that the model is reachable.",
            model=model,
            kind="timeout",
        )
    if isinstance(exc, APIConnectionError):
        return LlmProviderError(
            f"Could not connect to LLM endpoint for {model}. Check LLM_API_BASE / network.",
            model=model,
            kind="connection",
        )
    if isinstance(exc, AuthenticationError):
        return LlmProviderError(
            f"LLM authentication failed for {model}. Check OPENAI_API_KEY (or provider key).",
            model=model,
            kind="auth",
        )
    if isinstance(exc, RateLimitError):
        return LlmProviderError(
            f"LLM rate limit hit for {model}. Try again shortly.",
            model=model,
            kind="rate_limit",
        )
    text = str(exc)
    if isinstance(exc, (NotFoundError, UnsupportedParamsError)) or _looks_like_unsupported_image(
        text
    ):
        return LlmProviderError(
            f"Model {model} cannot generate images (wrong or chat-only model). "
            "Set LLM_IMAGE_MODEL to an image-capable id (e.g. dall-e-3).",
            model=model,
            kind="unsupported",
        )
    if isinstance(exc, (BadRequestError, InvalidRequestError)):
        if _looks_like_unsupported_image(text):
            return LlmProviderError(
                f"Model {model} cannot generate images (wrong or chat-only model). "
                "Set LLM_IMAGE_MODEL to an image-capable id (e.g. dall-e-3).",
                model=model,
                kind="unsupported",
            )
        return LlmProviderError(
            f"LLM rejected the request for {model} (bad model id or unsupported params). Check LLM_*_MODEL.",
            model=model,
            kind="bad_request",
        )
    # LiteLLM sometimes nests provider names in a generic Exception message.
    lower = text.lower()
    if "timeout" in lower:
        return LlmProviderError(
            f"LLM timed out talking to {model}. Check network, LLM_API_BASE, and that the model is reachable.",
            model=model,
            kind="timeout",
        )
    if "auth" in lower or "unauthorized" in lower or "invalid api key" in lower:
        return LlmProviderError(
            f"LLM authentication failed for {model}. Check API key / LLM_API_BASE.",
            model=model,
            kind="auth",
        )
    return LlmProviderError(
        f"LLM call failed for {model}: {text[:240]}",
        model=model,
        kind="provider",
    )


def _wrap_http_image_error(response: httpx.Response, *, model: str) -> LlmProviderError:
    text = (response.text or "")[:500]
    code = int(response.status_code)
    if code in (401, 403):
        return LlmProviderError(
            f"LLM authentication failed for {model}. Check API key / LLM_API_BASE.",
            model=model,
            kind="auth",
        )
    if code == 429:
        return LlmProviderError(
            f"LLM rate limit hit for {model}. Try again shortly.",
            model=model,
            kind="rate_limit",
        )
    if code == 404 or _looks_like_unsupported_image(text):
        return LlmProviderError(
            f"Model {model} cannot generate images (wrong or chat-only model). "
            "Set LLM_IMAGE_MODEL to an image-capable id (e.g. dall-e-3).",
            model=model,
            kind="unsupported",
        )
    if 400 <= code < 500:
        logger.warning("image HTTP %s for %s: %s", code, model, text[:500])
        return LlmProviderError(
            f"LLM rejected the request for {model} (bad model id or unsupported params). Check LLM_*_MODEL.",
            model=model,
            kind="bad_request",
        )
    return LlmProviderError(
        f"LLM call failed for {model}: {text[:240]}",
        model=model,
        kind="provider",
    )


def _wrap_compat_http_exc(exc: BaseException, *, model: str) -> LlmProviderError:
    if isinstance(exc, UnsafeUrlError):
        return LlmProviderError(
            f"Could not connect to LLM endpoint for {model}. Check LLM_API_BASE / network.",
            model=model,
            kind="connection",
        )
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return LlmProviderError(
            f"LLM timed out talking to {model}. Check network, LLM_API_BASE, and that the model is reachable.",
            model=model,
            kind="timeout",
        )
    if isinstance(exc, httpx.HTTPError):
        return LlmProviderError(
            f"Could not connect to LLM endpoint for {model}. Check LLM_API_BASE / network.",
            model=model,
            kind="connection",
        )
    return _wrap_provider_error(exc, model=model)


def _is_provider_failure(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            Timeout,
            APIConnectionError,
            AuthenticationError,
            RateLimitError,
            BadRequestError,
            InvalidRequestError,
            NotFoundError,
            UnsupportedParamsError,
        ),
    ):
        return True
    text = str(exc).lower()
    return any(
        tip in text
        for tip in (
            "timeout",
            "connection timed out",
            "connection error",
            "authentication",
            "unauthorized",
            "invalid api key",
            "model_not_found",
            "does not exist",
            "invalid model",
            "does not support",
            "doesn't support",
            "not support",
            "unsupported",
            "not supported",
        )
    )


async def _aclose_stream(stream: Any) -> None:
    """Best-effort close of a LiteLLM/httpx streaming response (Stop / cancel)."""
    if stream is None:
        return
    close = getattr(stream, "aclose", None)
    if close is None:
        close = getattr(stream, "close", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.debug("LLM stream aclose failed", exc_info=True)


def _delta_text(chunk: Any) -> str | None:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    piece = getattr(delta, "content", None) if delta is not None else None
    if piece:
        return str(piece)
    return None


async def _astream_completion(
    *,
    model: str,
    kwargs: dict[str, Any],
    usage_sink: Any = None,
    on_first_token: Any = None,
) -> AsyncIterator[str]:
    """Stream chat completion deltas; always aclose on exit (including CancelledError)."""
    response: Any = None
    first = True
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            if usage_sink is not None:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    usage_sink(usage)
            piece = _delta_text(chunk)
            if piece:
                if first:
                    first = False
                    if on_first_token is not None:
                        on_first_token()
                yield piece
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if _is_provider_failure(exc):
            raise _wrap_provider_error(exc, model=model) from exc
        raise
    finally:
        await _aclose_stream(response)


async def complete_json(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.4,
) -> str:
    """JSON completion via streaming so Stop can aclose mid-response."""
    resolved = resolve_llm_model(tier)
    if resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
        with track(
            kind="chat_json", tier=tier, model=model, temperature=temperature,
            system=system, user=user,
        ) as rec:
            parts: list[str] = []
            async for piece in _vertex_astream_text(
                resolved=resolved,
                system=system,
                user=user,
                temperature=temperature,
                json_mode=True,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            ):
                parts.append(piece)
            content = "".join(parts)
            if not content:
                rec.fail(
                    "empty_response",
                    {"kind": "empty_response", "message": "LLM returned empty content"},
                )
                raise RuntimeError("LLM returned empty content")
            rec.response_text = content
            return content
    kwargs = _base_kwargs(tier, temperature)
    model = str(kwargs["model"])
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["response_format"] = {"type": "json_object"}
    kwargs["stream"] = True
    # Ask for a final usage chunk (dropped for providers that don't support it).
    kwargs["stream_options"] = {"include_usage": True}
    with track(
        kind="chat_json", tier=tier, model=model, temperature=temperature,
        system=system, user=user,
    ) as rec:
        parts: list[str] = []
        async for piece in _astream_completion(
            model=model,
            kwargs=kwargs,
            usage_sink=rec.set_usage,
            on_first_token=rec.mark_first_token,
        ):
            parts.append(piece)
        content = "".join(parts)
        if not content:
            rec.fail("empty_response", {"kind": "empty_response", "message": "LLM returned empty content"})
            raise RuntimeError("LLM returned empty content")
        rec.response_text = content
        return content


async def complete_text(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.5,
) -> str:
    resolved = resolve_llm_model(tier)
    if resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
        with track(
            kind="chat_text", tier=tier, model=model, temperature=temperature,
            system=system, user=user,
        ) as rec:
            content = await _vertex_complete_text(
                resolved=resolved,
                system=system,
                user=user,
                temperature=temperature,
                usage_sink=rec.set_usage,
            )
            if not content:
                rec.fail(
                    "empty_response",
                    {"kind": "empty_response", "message": "LLM returned empty content"},
                )
                raise RuntimeError("LLM returned empty content")
            rec.response_text = content
            return rec.response_text
    kwargs = _base_kwargs(tier, temperature)
    model = str(kwargs["model"])
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    with track(
        kind="chat_text", tier=tier, model=model, temperature=temperature,
        system=system, user=user,
    ) as rec:
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            if _is_provider_failure(exc):
                raise _wrap_provider_error(exc, model=model) from exc
            raise
        content = response.choices[0].message.content
        if not content:
            rec.fail("empty_response", {"kind": "empty_response", "message": "LLM returned empty content"})
            raise RuntimeError("LLM returned empty content")
        rec.set_usage(getattr(response, "usage", None))
        rec.response_text = content.strip()
        return rec.response_text


async def astream_text(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.5,
) -> AsyncIterator[str]:
    """Yield assistant text pieces as the model streams them; aclose on cancel."""
    resolved = resolve_llm_model(tier)
    if resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
        with track(
            kind="chat_text", tier=tier, model=model, temperature=temperature,
            system=system, user=user,
        ) as rec:
            parts: list[str] = []
            async for piece in _vertex_astream_text(
                resolved=resolved,
                system=system,
                user=user,
                temperature=temperature,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            ):
                parts.append(piece)
                yield piece
            rec.response_text = "".join(parts)
        return
    kwargs = _base_kwargs(tier, temperature)
    model = str(kwargs["model"])
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["stream"] = True
    kwargs["stream_options"] = {"include_usage": True}
    with track(
        kind="chat_text", tier=tier, model=model, temperature=temperature,
        system=system, user=user,
    ) as rec:
        parts: list[str] = []
        async for piece in _astream_completion(
            model=model,
            kwargs=kwargs,
            usage_sink=rec.set_usage,
            on_first_token=rec.mark_first_token,
        ):
            parts.append(piece)
            yield piece
        rec.response_text = "".join(parts)


def _b64_data_url(raw: str) -> str:
    mime = "image/jpeg" if raw.startswith("/9j/") else "image/png"
    return f"data:{mime};base64,{raw}"


def _inline_b64(part: Any) -> str | None:
    if isinstance(part, dict):
        inline = part.get("inlineData") or part.get("inline_data") or {}
        if isinstance(inline, dict) and inline.get("data"):
            return str(inline["data"])
        for key in ("b64_json", "b64", "bytesBase64Encoded", "data"):
            val = part.get(key)
            if val and key != "data":
                return str(val)
        return None
    for attr in ("b64_json", "b64", "bytesBase64Encoded"):
        val = getattr(part, attr, None)
        if val:
            return str(val)
    inline = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
    if inline is None:
        return None
    data = inline.get("data") if isinstance(inline, dict) else getattr(inline, "data", None)
    return str(data) if data else None


def _gemini_inline_b64(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None)
    if candidates is None and isinstance(response, dict):
        candidates = response.get("candidates")
    if candidates:
        first = candidates[0]
        content = (
            first.get("content") if isinstance(first, dict) else getattr(first, "content", None)
        )
        if content is not None:
            parts = (
                content.get("parts")
                if isinstance(content, dict)
                else getattr(content, "parts", None)
            )
            if parts:
                for part in parts:
                    found = _inline_b64(part)
                    if found:
                        return found
    images = getattr(response, "images", None)
    if images is None and isinstance(response, dict):
        images = response.get("images")
    if images:
        return _inline_b64(images[0])
    return None


def image_result_to_url(response: Any) -> str | None:
    """Normalize OpenAI Images or Gemini inline-b64 responses to a hostable URL."""
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if data:
        first = data[0]
        url = first.get("url") if isinstance(first, dict) else getattr(first, "url", None)
        if url:
            return str(url)
        b64 = (
            first.get("b64_json") if isinstance(first, dict) else getattr(first, "b64_json", None)
        )
        if b64:
            return _b64_data_url(str(b64))
        inline = _inline_b64(first)
        if inline:
            return _b64_data_url(inline)
    gemini = _gemini_inline_b64(response)
    if gemini:
        return _b64_data_url(gemini)
    return None


async def generate_image(*, prompt: str, size: str = "1024x1024") -> str:
    """Call the configured image model; return a hostable URL.

    Raises ``LlmProviderError`` when the model is missing, chat-only, or the
    provider rejects the request — callers must surface this to the UI.
    """
    raw = resolve_image_model()
    if not raw:
        raise LlmProviderError(
            "No image model configured (set LLM_IMAGE_MODEL, e.g. dall-e-3). "
            "Chat-only models cannot generate images.",
            kind="unsupported",
        )
    if raw.lower() == "placeholder":
        raise LlmProviderError(
            "LLM_IMAGE_MODEL=placeholder — mock mode is handled by the session node.",
            model=raw,
            kind="unsupported",
        )

    resolved = resolve_image()
    if resolved is not None and resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
        with track(
            kind="image", tier=None, model=model, temperature=None, system=None, user=prompt
        ) as rec:
            response = await _vertex_generate_image(resolved=resolved, prompt=prompt)
            url = image_result_to_url(response)
            if url:
                rec.response_text = url
                return rec.response_text
            raise LlmProviderError(
                f"Image model {model} response had neither url nor b64_json.",
                model=model,
                kind="provider",
            )

    configure_litellm()
    ptype = resolved.provider_type if resolved is not None else "openai"
    api_base = (
        effective_api_base(ptype, resolved.api_base) if resolved is not None else None
    )
    api_key = resolved.api_key if resolved is not None else None
    source = resolved.source if resolved is not None else "env"
    catalog = openai_compat_model_id(raw)
    timeout = float(settings.llm_timeout_seconds)

    if api_base and ptype in ("openai", "openai_compatible"):
        kind = await resolve_compat_image_api(
            api_base=api_base,
            api_key=api_key,
            source=source,
            timeout=float(BYOK_PROBE_TIMEOUT_SECONDS),
        )
        if kind == "dedicated":
            with track(
                kind="image", tier=None, model=catalog, temperature=None, system=None, user=prompt
            ) as rec:
                try:
                    response = await post_dedicated_image(
                        api_base=api_base,
                        api_key=api_key,
                        source=source,
                        model=catalog,
                        prompt=prompt,
                        timeout=timeout,
                    )
                except Exception as exc:
                    if isinstance(
                        exc, (UnsafeUrlError, httpx.HTTPError, TimeoutError, OSError)
                    ) or _is_provider_failure(exc):
                        raise _wrap_compat_http_exc(exc, model=catalog) from exc
                    raise
                if response.status_code >= 400:
                    raise _wrap_http_image_error(response, model=catalog)
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                url = image_result_to_url(payload)
                if url:
                    rec.response_text = url
                    return rec.response_text
                raise LlmProviderError(
                    f"Image model {catalog} response had neither url nor b64_json.",
                    model=catalog,
                    kind="provider",
                )

    model = _litellm_model(raw, api_base, ptype)
    kwargs: dict = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "timeout": settings.llm_timeout_seconds,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key

    with track(kind="image", tier=None, model=model, temperature=None, system=None, user=prompt) as rec:
        try:
            response = await litellm.aimage_generation(**kwargs)
        except Exception as exc:
            if _is_provider_failure(exc):
                raise _wrap_provider_error(exc, model=model) from exc
            raise

        url = image_result_to_url(response)
        if url:
            rec.response_text = url
            return rec.response_text
        raise LlmProviderError(
            f"Image model {model} response had neither url nor b64_json.",
            model=model,
            kind="provider",
        )
