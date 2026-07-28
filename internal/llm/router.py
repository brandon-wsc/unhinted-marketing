"""LiteLLM routing with BYOK from environment (DB-backed keys in Phase 4)."""

from collections.abc import AsyncIterator
from enum import Enum

import litellm

from internal.config import settings


class ModelTier(str, Enum):
    CHEAP = "cheap"
    MEDIUM = "medium"
    STRONG = "strong"


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


def _base_kwargs(tier: ModelTier, temperature: float) -> dict:
    configure_litellm()
    kwargs: dict = {
        "model": resolve_model(tier),
        "temperature": temperature,
        "timeout": settings.llm_timeout_seconds,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
    return kwargs


async def complete_json(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.4,
) -> str:
    kwargs = _base_kwargs(tier, temperature)
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["response_format"] = {"type": "json_object"}
    response = await litellm.acompletion(**kwargs)
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
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    response = await litellm.acompletion(**kwargs)
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
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs["stream"] = True
    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        piece = getattr(choices[0].delta, "content", None)
        if piece:
            yield piece
