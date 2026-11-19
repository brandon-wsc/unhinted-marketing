"""LiteLLM routing — credentials from the per-turn resolver (ADR 0020)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from collections.abc import AsyncIterator, Sequence
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
from internal.llm.recorder import LlmCallRecordBuilder, track
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
        await aclose_stream(stream)


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


async def aclose_stream(stream: Any) -> None:
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
        await aclose_stream(response)


def _lc_model_id(resolved: Any) -> str:
    """API model id for the LangChain path (mirrors ``live_harness_model``)."""
    api_base = effective_api_base(resolved.provider_type, resolved.api_base)
    if resolved.provider_type == "openai_compatible" or api_base:
        return openai_compat_model_id(resolved.model_id)
    return resolved.model_id.split("/")[-1]


def _lc_chat_model(
    resolved: Any, *, temperature: float | None, json_mode: bool = False
) -> tuple[Any, str] | None:
    """``(ChatModel, model_label)`` for the LangChain path, else ``None``.

    Deliberately narrow (ADR 0060 §5): only ``openai``/``openai_compatible``
    (any api_base) run on LangChain here. ``anthropic`` + AI-Studio ``gemini``
    stay on litellm and ``vertex_ai`` keeps the hand-rolled api_key-only path
    (ADR 0021 §4) — the full provider map lives in ``lc_harness_model`` for
    the session harnesses.
    """
    if resolved.provider_type not in ("openai", "openai_compatible"):
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    api_base = effective_api_base(resolved.provider_type, resolved.api_base)
    model = _lc_model_id(resolved)
    chat = ChatOpenAI(
        model=model,
        api_key=resolved.api_key or "not-set",
        base_url=api_base,
        temperature=temperature,
        timeout=settings.llm_timeout_seconds,
        stream_usage=True,
        max_retries=0,
        model_kwargs=({"response_format": {"type": "json_object"}} if json_mode else {}),
    )
    return chat, model


def lc_harness_model(resolved: Any) -> tuple[Any, str]:
    """``(ChatModel, model_label)`` for the session harnesses — full provider coverage.

    Mirrors the retired ``live_harness_model`` branch order: gemini/vertex
    first, compat/api_base second, claude-by-name third, plain openai last.
    ``vertex_ai`` rides the genai SDK's Express mode (``vertexai=True`` +
    api_key — ADR 0021 §4). Raises ``LlmProviderError`` when the matching
    langchain package is absent.
    """
    lowered = resolved.model_id.lower()
    if resolved.provider_type in ("gemini", "vertex_ai"):
        model = gemini_catalog_id(resolved.model_id)
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise LlmProviderError(
                "Gemini / Vertex Express session harness needs "
                "langchain-google-genai (pip install langchain-google-genai).",
                model=model,
                kind="unsupported",
            ) from exc
        chat = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=resolved.api_key or "not-set",
            vertexai=resolved.provider_type == "vertex_ai",
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        return chat, model
    api_base = effective_api_base(resolved.provider_type, resolved.api_base)
    if resolved.provider_type == "openai_compatible" or api_base:
        lc = _lc_chat_model(resolved, temperature=None)
        if lc is None:
            raise LlmProviderError(
                "OpenAI-compatible session harness needs langchain-openai.",
                model=resolved.model_id,
                kind="unsupported",
            )
        return lc
    if (
        resolved.provider_type == "anthropic"
        or "claude" in lowered
        or lowered.startswith("anthropic")
    ):
        model = resolved.model_id.split("/")[-1]
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise LlmProviderError(
                "Anthropic session harness needs langchain-anthropic "
                "(pip install langchain-anthropic).",
                model=model,
                kind="unsupported",
            ) from exc
        chat = ChatAnthropic(
            model=model,
            api_key=resolved.api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        return chat, model
    if not resolved.api_key:
        raise LlmProviderError(
            "No OpenAI-compatible key for the session harness.",
            model=resolved.model_id,
            kind="auth",
        )
    lc = _lc_chat_model(resolved, temperature=None)
    if lc is None:
        raise LlmProviderError(
            "OpenAI session harness needs langchain-openai.",
            model=resolved.model_id,
            kind="unsupported",
        )
    return lc


def wrap_lc_error(exc: BaseException, *, model: str) -> LlmProviderError:
    """Map provider-SDK / LangChain exceptions onto ``LlmProviderError`` kinds."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover — optional provider extra
        anthropic = None  # type: ignore[assignment]
    if anthropic is not None:
        if isinstance(exc, anthropic.APITimeoutError):
            return LlmProviderError(
                f"LLM timed out talking to {model}. Check network and that the model is reachable.",
                model=model,
                kind="timeout",
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return LlmProviderError(
                f"Could not connect to LLM endpoint for {model}. Check LLM_API_BASE / network.",
                model=model,
                kind="connection",
            )
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return LlmProviderError(
                f"LLM authentication failed for {model}. Check the provider API key.",
                model=model,
                kind="auth",
            )
        if isinstance(exc, anthropic.RateLimitError):
            return LlmProviderError(
                f"LLM rate limit hit for {model}. Try again shortly.",
                model=model,
                kind="rate_limit",
            )
        if isinstance(exc, anthropic.NotFoundError):
            return LlmProviderError(
                f"Model {model} was not found. Check the model id.",
                model=model,
                kind="unsupported",
            )
        if isinstance(exc, anthropic.BadRequestError):
            return LlmProviderError(
                f"LLM rejected the request for {model} (bad model id or unsupported params). Check LLM_*_MODEL.",
                model=model,
                kind="bad_request",
            )
    try:
        from google.genai.errors import APIError as GoogleAPIError
    except ImportError:  # pragma: no cover — optional provider extra
        GoogleAPIError = None  # type: ignore[assignment, misc]
    if GoogleAPIError is not None and isinstance(exc, GoogleAPIError):
        return _wrap_google_genai_error(exc, model=model)
    try:
        import openai
    except ImportError:  # pragma: no cover — openai ships with litellm
        return _wrap_provider_error(exc, model=model)
    if isinstance(exc, openai.APITimeoutError):
        return LlmProviderError(
            f"LLM timed out talking to {model}. Check network, LLM_API_BASE, and that the model is reachable.",
            model=model,
            kind="timeout",
        )
    if isinstance(exc, openai.APIConnectionError):
        return LlmProviderError(
            f"Could not connect to LLM endpoint for {model}. Check LLM_API_BASE / network.",
            model=model,
            kind="connection",
        )
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LlmProviderError(
            f"LLM authentication failed for {model}. Check OPENAI_API_KEY (or provider key).",
            model=model,
            kind="auth",
        )
    if isinstance(exc, openai.RateLimitError):
        return LlmProviderError(
            f"LLM rate limit hit for {model}. Try again shortly.",
            model=model,
            kind="rate_limit",
        )
    if isinstance(exc, openai.NotFoundError):
        return LlmProviderError(
            f"Model {model} was not found. Check the model id.",
            model=model,
            kind="unsupported",
        )
    if isinstance(exc, openai.BadRequestError):
        return LlmProviderError(
            f"LLM rejected the request for {model} (bad model id or unsupported params). Check LLM_*_MODEL.",
            model=model,
            kind="bad_request",
        )
    return _wrap_provider_error(exc, model=model)


def map_lc_error(exc: BaseException, *, model: str) -> BaseException:
    """Map a LangChain-seam exception — ADR 0060 §3 error contract.

    Framework cancellation (``concurrent.futures.CancelledError`` from a
    wrapped ``run_in_executor`` call) maps to ``CancelledError``; everything
    else wraps to ``LlmProviderError``.
    """
    if isinstance(exc, concurrent.futures.CancelledError):
        return asyncio.CancelledError()
    return wrap_lc_error(exc, model=model)


def _lc_token_count(
    chat: Any,
    messages: Sequence[Any] = (),
    text: str = "",
) -> int | None:
    """Token count via the model's counters, then a per-content fallback.

    ``get_num_tokens_from_messages`` hard-raises on model ids it does not
    know (any OpenAI-compatible slug like ``deepseek/...``), while plain
    ``get_num_tokens`` maps them to a generic encoding — so a failed message
    count falls back to counting each message's content (and tool-call args).
    """
    try:
        if messages:
            return int(chat.get_num_tokens_from_messages(list(messages)))
        if text:
            return int(chat.get_num_tokens(text))
        return 0
    except Exception:
        logger.debug("lc message token count failed; per-content fallback", exc_info=True)
    try:
        total = 0
        for message in messages:
            content = getattr(message, "content", "")
            if isinstance(content, str) and content:
                total += int(chat.get_num_tokens(content))
            for call in getattr(message, "tool_calls", None) or []:
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
                if args:
                    total += int(chat.get_num_tokens(json.dumps(args, ensure_ascii=False)))
        if text:
            total += int(chat.get_num_tokens(text))
        return total
    except Exception:  # noqa: BLE001 — best-effort estimate
        return None


def estimate_lc_usage(
    chat: Any,
    prompt_messages: Sequence[Any],
    *,
    completion_messages: Sequence[Any] = (),
    completion_text: str = "",
) -> dict[str, int] | None:
    """Client-side usage estimate when a provider returns no usage.

    LiteLLM used to fill usage client-side when a stream carried no usage
    chunk; LangChain only reports what the provider sends, so providers that
    ignore ``include_usage`` record NULL token counts — under-counting
    llm_call_records and under-enforcing the ADR 0041 member cap. Returns
    ``None`` when the model cannot count tokens locally.
    """
    prompt = _lc_token_count(chat, prompt_messages)
    if prompt is None:
        return None
    if completion_messages:
        output = _lc_token_count(chat, completion_messages)
    else:
        output = _lc_token_count(chat, text=completion_text)
    output = output or 0
    return {
        "input_tokens": prompt,
        "output_tokens": output,
        "total_tokens": prompt + output,
    }


async def _lc_astream_text(
    *,
    chat: Any,
    model: str,
    system: str,
    user: str,
    usage_sink: Any = None,
    on_first_token: Any = None,
) -> AsyncIterator[str]:
    """Yield text deltas from a LangChain chat model; aclose on cancel.

    ``_astream_completion`` equivalent on ``BaseChatModel.astream``: usage
    rides trailing chunks (``usage_metadata`` as input_/output_/total_tokens),
    the first non-empty delta marks first token, and closing the generator
    aborts the HTTP stream (``astream`` holds it inside ``async with``).
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    agen: Any = None
    first = True
    saw_chunk = False
    saw_usage = False
    parts: list[str] = []
    try:
        agen = chat.astream(messages)
        async for chunk in agen:
            saw_chunk = True
            usage = getattr(chunk, "usage_metadata", None)
            if usage_sink is not None and usage:
                saw_usage = True
                usage_sink(usage)
            piece = chunk.content if isinstance(chunk.content, str) else ""
            if piece:
                parts.append(piece)
                if first:
                    first = False
                    if on_first_token is not None:
                        on_first_token()
                yield piece
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise map_lc_error(exc, model=model) from exc
    finally:
        await aclose_stream(agen)
        if usage_sink is not None and saw_chunk and not saw_usage:
            estimate = estimate_lc_usage(
                chat, messages, completion_text="".join(parts)
            )
            if estimate is not None:
                usage_sink(estimate)


async def _drain_text_stream(
    stream: AsyncIterator[str],
    rec: LlmCallRecordBuilder,
    *,
    strip: bool = False,
) -> str:
    """Drain a text stream into ``rec``; stash partial text before re-raise.

    ADR 0060 §3 — a cancelled/erroring stream still records what it managed
    to return; an empty completion is an ``empty_response`` failure.
    """
    parts: list[str] = []
    try:
        async for piece in stream:
            parts.append(piece)
    except BaseException:
        rec.response_text = "".join(parts).strip() or None
        raise
    content = "".join(parts)
    if strip:
        content = content.strip()
    if not content:
        rec.fail(
            "empty_response",
            {"kind": "empty_response", "message": "LLM returned empty content"},
        )
        raise RuntimeError("LLM returned empty content")
    rec.response_text = content
    return content


async def complete_json(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.4,
) -> str:
    """JSON completion via streaming so Stop can aclose mid-response."""
    resolved = resolve_llm_model(tier)
    lc = (
        None
        if resolved.provider_type == "vertex_ai"
        else _lc_chat_model(resolved, temperature=temperature, json_mode=True)
    )
    kwargs: dict = {}
    if resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
    elif lc is not None:
        model = lc[1]
    else:
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
        if resolved.provider_type == "vertex_ai":
            stream = _vertex_astream_text(
                resolved=resolved,
                system=system,
                user=user,
                temperature=temperature,
                json_mode=True,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        elif lc is not None:
            stream = _lc_astream_text(
                chat=lc[0],
                model=model,
                system=system,
                user=user,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        else:
            stream = _astream_completion(
                model=model,
                kwargs=kwargs,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        return await _drain_text_stream(stream, rec)


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
    lc = _lc_chat_model(resolved, temperature=temperature)
    if lc is not None:
        chat, model = lc
        with track(
            kind="chat_text", tier=tier, model=model, temperature=temperature,
            system=system, user=user,
        ) as rec:
            return await _drain_text_stream(
                _lc_astream_text(
                    chat=chat,
                    model=model,
                    system=system,
                    user=user,
                    usage_sink=rec.set_usage,
                    on_first_token=rec.mark_first_token,
                ),
                rec,
                strip=True,
            )
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
    lc = (
        None
        if resolved.provider_type == "vertex_ai"
        else _lc_chat_model(resolved, temperature=temperature)
    )
    kwargs: dict = {}
    if resolved.provider_type == "vertex_ai":
        model = gemini_catalog_id(resolved.model_id)
    elif lc is not None:
        model = lc[1]
    else:
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
        if resolved.provider_type == "vertex_ai":
            stream = _vertex_astream_text(
                resolved=resolved,
                system=system,
                user=user,
                temperature=temperature,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        elif lc is not None:
            stream = _lc_astream_text(
                chat=lc[0],
                model=model,
                system=system,
                user=user,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        else:
            stream = _astream_completion(
                model=model,
                kwargs=kwargs,
                usage_sink=rec.set_usage,
                on_first_token=rec.mark_first_token,
            )
        parts: list[str] = []
        try:
            async for piece in stream:
                parts.append(piece)
                yield piece
        except BaseException:
            rec.response_text = "".join(parts).strip() or None
            raise
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
    """Normalize OpenAI Images or Gemini inline-b64 responses to a hostable ref.

    Inline bytes win over a provider ``url`` — they persist without a fetch
    (ADR 0043 §2); the URL path is only for providers that return no bytes.
    """
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if data:
        first = data[0]
        b64 = (
            first.get("b64_json") if isinstance(first, dict) else getattr(first, "b64_json", None)
        )
        if b64:
            return _b64_data_url(str(b64))
        inline = _inline_b64(first)
        if inline:
            return _b64_data_url(inline)
        url = first.get("url") if isinstance(first, dict) else getattr(first, "url", None)
        if url:
            return str(url)
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
            rec.set_usage(getattr(response, "usage_metadata", None))
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
                if isinstance(payload, dict):
                    rec.set_usage(payload.get("usage"))
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

        rec.set_usage(getattr(response, "usage", None))
        url = image_result_to_url(response)
        if url:
            rec.response_text = url
            return rec.response_text
        raise LlmProviderError(
            f"Image model {model} response had neither url nor b64_json.",
            model=model,
            kind="provider",
        )
