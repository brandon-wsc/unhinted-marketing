"""LiteLLM routing with BYOK from environment (DB-backed keys in Phase 4)."""

from collections.abc import AsyncIterator
from enum import Enum

import litellm
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from internal.config import settings


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
    if settings.openai_api_key:
        litellm.openai_key = settings.openai_api_key
    if settings.anthropic_api_key:
        litellm.anthropic_key = settings.anthropic_api_key


def has_llm_credentials() -> bool:
    return bool(settings.openai_api_key or settings.anthropic_api_key)


def resolve_model(tier: ModelTier) -> str:
    mapping = {
        ModelTier.CHEAP: settings.llm_cheap_model,
        ModelTier.MEDIUM: settings.llm_medium_model,
        ModelTier.STRONG: settings.llm_strong_model,
    }
    return mapping[tier]


def _litellm_model(model: str) -> str:
    """When LLM_API_BASE is set, force the OpenAI-compatible provider.

    Bare ids like ``deepseek-chat`` make LiteLLM pick the native Deepseek
    provider and ignore (or mishandle) a custom api_base — which surfaces as
    an instant DeepseekException timeout. Prefix ``openai/`` so the request
    goes through the OpenAI-compatible HTTP client against LLM_API_BASE.
    """
    if not settings.llm_api_base:
        return model
    if "/" in model:
        return model
    return f"openai/{model}"


def _base_kwargs(tier: ModelTier, temperature: float) -> dict:
    configure_litellm()
    model = _litellm_model(resolve_model(tier))
    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "timeout": settings.llm_timeout_seconds,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
    return kwargs


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
    if isinstance(exc, BadRequestError):
        return LlmProviderError(
            f"LLM rejected the request for {model} (bad model id or unsupported params). Check LLM_*_MODEL.",
            model=model,
            kind="bad_request",
        )
    # LiteLLM sometimes nests provider names in a generic Exception message.
    text = str(exc)
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
        (Timeout, APIConnectionError, AuthenticationError, RateLimitError, BadRequestError),
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
        )
    )


async def complete_json(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.4,
) -> str:
    kwargs = _base_kwargs(tier, temperature)
    model = str(kwargs["model"])
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["response_format"] = {"type": "json_object"}
    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as exc:
        if _is_provider_failure(exc):
            raise _wrap_provider_error(exc, model=model) from exc
        raise
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty content")
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
    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as exc:
        if _is_provider_failure(exc):
            raise _wrap_provider_error(exc, model=model) from exc
        raise
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty content")
    return content.strip()


async def astream_text(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.5,
) -> AsyncIterator[str]:
    """Yield assistant text pieces as the model streams them."""
    kwargs = _base_kwargs(tier, temperature)
    model = str(kwargs["model"])
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["stream"] = True
    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            piece = getattr(choices[0].delta, "content", None)
            if piece:
                yield piece
    except Exception as exc:
        if _is_provider_failure(exc):
            raise _wrap_provider_error(exc, model=model) from exc
        raise
