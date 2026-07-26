"""LiteLLM routing with BYOK from environment (DB-backed keys in Phase 4)."""

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


def resolve_model(tier: ModelTier) -> str:
    mapping = {
        ModelTier.CHEAP: settings.llm_cheap_model,
        ModelTier.MEDIUM: settings.llm_medium_model,
        ModelTier.STRONG: settings.llm_strong_model,
    }
    return mapping[tier]


async def complete_json(
    *,
    tier: ModelTier,
    system: str,
    user: str,
    temperature: float = 0.4,
) -> str:
    configure_litellm()
    model = resolve_model(tier)
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
    response = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty content")
    return content
