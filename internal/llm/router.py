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

from internal.config import settings
from internal.llm.recorder import track
from internal.llm.resolve import (
    bundle_has_credentials,
    env_has_llm_credentials,
    prefix_litellm_model,
    resolve_image,
    resolve_llm_model,
)

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


def _litellm_model(model: str, api_base: str | None = None) -> str:
    """When a custom api_base is set, force the OpenAI-compatible provider.

    Bare ids like ``deepseek-chat`` make LiteLLM pick the native Deepseek
    provider and ignore (or mishandle) a custom api_base — which surfaces as
    an instant DeepseekException timeout. Prefix ``openai/`` so the request
    goes through the OpenAI-compatible HTTP client against that base.
    """
    return prefix_litellm_model(model, api_base)


def _base_kwargs(tier: ModelTier, temperature: float) -> dict:
    configure_litellm()
    resolved = resolve_llm_model(tier)
    raw = resolve_model(tier)
    model = _litellm_model(raw, resolved.api_base)
    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "timeout": settings.llm_timeout_seconds,
    }
    if resolved.api_base:
        kwargs["api_base"] = resolved.api_base
    if resolved.api_key:
        kwargs["api_key"] = resolved.api_key
    return kwargs


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
) -> AsyncIterator[str]:
    """Stream chat completion deltas; always aclose on exit (including CancelledError)."""
    response: Any = None
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            if usage_sink is not None:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    usage_sink(usage)
            piece = _delta_text(chunk)
            if piece:
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
        async for piece in _astream_completion(model=model, kwargs=kwargs, usage_sink=rec.set_usage):
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
        async for piece in _astream_completion(model=model, kwargs=kwargs, usage_sink=rec.set_usage):
            parts.append(piece)
            yield piece
        rec.response_text = "".join(parts)


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

    configure_litellm()
    resolved = resolve_image()
    api_base = resolved.api_base if resolved is not None else None
    api_key = resolved.api_key if resolved is not None else None
    model = _litellm_model(raw, api_base)
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

        data = getattr(response, "data", None) or []
        if not data:
            raise LlmProviderError(
                f"Image model {model} returned no image data.",
                model=model,
                kind="provider",
            )
        first = data[0]
        url = getattr(first, "url", None)
        if not url and isinstance(first, dict):
            url = first.get("url")
        # Some providers return b64_json instead of a URL.
        b64 = getattr(first, "b64_json", None)
        if not b64 and isinstance(first, dict):
            b64 = first.get("b64_json")
        if url:
            rec.response_text = str(url)
            return rec.response_text
        if b64:
            # Providers often return JPEG bytes even when labelled loosely; sniff magic.
            raw = str(b64)
            mime = "image/jpeg" if raw.startswith("/9j/") else "image/png"
            # The recorder stores a size marker for data URIs, not megabytes of base64.
            rec.response_text = f"data:{mime};base64,{raw}"
            return rec.response_text
        raise LlmProviderError(
            f"Image model {model} response had neither url nor b64_json.",
            model=model,
            kind="provider",
        )
