"""Pydantic AI inner loop for session nodes (ADR 0019).

Agents are built per call and discarded — never stored on graph state or FastAPI.
Chat tools are read-only; publish-class names are never registered.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, RunCancelled
from pydantic_ai.models import Model

from internal.llm.recorder import LlmCallRecordBuilder, track
from internal.llm.resolve import gemini_catalog_id, openai_compat_model_id, resolve_llm_model
from internal.llm.router import LlmProviderError, ModelTier
from internal.memory.repos import list_top_signals
from internal.session import prompts
from internal.session.context import get_db
from internal.session.events import session_event_bus
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import QueryMarketTrendsResponse, QueryMarketTrendsSignal

logger = logging.getLogger(__name__)

PUBLISH_TOOL_NAMES = frozenset({"publish_social_post"})
CHAT_TOOL_NAMES = frozenset({"query_market_trends"})

# Match nodes._DELTA_FLUSH_CHARS — long replies must not overflow SSE queues.
_DELTA_FLUSH_CHARS = 24

_model_override: Model | None = None


@dataclass
class ChatDeps:
    company_id: uuid.UUID | None = None


def set_chat_model_override(model: Model | None) -> None:
    """Test hook: inject TestModel / FunctionModel. Pass None to restore live."""
    global _model_override
    _model_override = model


def live_harness_model(tier: ModelTier) -> Model:
    """BYOK model from the per-turn resolver (org slot or env fallback)."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    resolved = resolve_llm_model(tier)
    raw = resolved.model_id
    if resolved.provider_type in ("gemini", "vertex_ai"):
        try:
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider
            from pydantic_ai.providers.google_cloud import GoogleCloudProvider
        except ImportError as exc:
            raise LlmProviderError(
                "Gemini / Vertex Express session harness needs the google extra "
                '(pip install "pydantic-ai-slim[google]").',
                model=raw,
                kind="unsupported",
            ) from exc
        # Vertex: api_key only. project/location/credentials would take ADC (ADR 0021 §4).
        provider = (
            GoogleCloudProvider(api_key=resolved.api_key or "not-set")
            if resolved.provider_type == "vertex_ai"
            else GoogleProvider(api_key=resolved.api_key or "not-set")
        )
        return GoogleModel(gemini_catalog_id(raw), provider=provider)
    compat_id = openai_compat_model_id(raw)
    leaf_id = compat_id.split("/")[-1]
    if resolved.provider_type == "openai_compatible" or resolved.api_base:
        return OpenAIChatModel(
            compat_id,
            provider=OpenAIProvider(
                base_url=resolved.api_base,
                api_key=resolved.api_key or "not-set",
            ),
        )
    lowered = raw.lower()
    if resolved.provider_type == "anthropic" or "claude" in lowered or lowered.startswith(
        "anthropic"
    ):
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider
        except ImportError as exc:
            raise LlmProviderError(
                "Anthropic session harness needs the anthropic extra "
                '(pip install "pydantic-ai-slim[anthropic]").',
                model=raw,
                kind="unsupported",
            ) from exc
        return AnthropicModel(
            leaf_id,
            provider=AnthropicProvider(api_key=resolved.api_key),
        )
    if not resolved.api_key:
        raise LlmProviderError(
            "No OpenAI-compatible key for the session harness.",
            model=raw,
            kind="auth",
        )
    return OpenAIChatModel(
        leaf_id,
        provider=OpenAIProvider(api_key=resolved.api_key),
    )


def live_chat_model() -> Model:
    """Chat-tier BYOK model."""
    return live_harness_model(NODE_MODEL_TIERS["chat"] or ModelTier.CHEAP)


async def lookup_market_trends(
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    """Read-only HK signal lookup from PostgreSQL (no second store)."""
    try:
        db = get_db()
    except RuntimeError:
        return QueryMarketTrendsResponse(region=region, notes="no session db")
    capped = max(1, min(int(limit), 50))
    rows = await list_top_signals(db, limit=capped, region=region)
    signals = [
        QueryMarketTrendsSignal(
            signal_id=row.signal_id,
            source=row.source,
            title=row.title,
            url=row.url,
            excerpt=row.excerpt,
            region=row.region,
            metrics=row.metrics or {},
        )
        for row in rows
    ]
    return QueryMarketTrendsResponse(
        region=region,
        signals=signals,
        ranked_signal_ids=[s.signal_id for s in signals],
    )


async def query_market_trends(
    ctx: RunContext[ChatDeps],
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    del ctx  # company_id reserved; corpus is still HK-wide (same as trend_searcher)
    return await lookup_market_trends(region, limit)


async def slow_probe(ctx: RunContext[ChatDeps]) -> str:
    """Test-only: sleep so Stop/cancel can be observed mid-tool. Never register in prod."""
    del ctx
    await asyncio.sleep(10)
    return "slept"


def build_chat_agent(
    *,
    model: Model,
    extra_tools: Sequence[Any] = (),
) -> Agent[ChatDeps, str]:
    tools: list[Any] = [query_market_trends, *extra_tools]
    return Agent(
        model,
        deps_type=ChatDeps,
        output_type=str,
        system_prompt=prompts.CHAT,
        tools=tools,
        name="session_chat",
        end_strategy="exhaustive",
    )


def registered_function_tool_names(agent: Agent[Any, Any]) -> set[str]:
    names: set[str] = set()
    for toolset in agent.toolsets or []:
        tools = getattr(toolset, "tools", None)
        if isinstance(tools, dict):
            names.update(str(name) for name in tools)
    return names


async def _publish_deltas(
    session_id: uuid.UUID, pending: list[str], *, force: bool = False
) -> None:
    text = "".join(pending)
    if not text or (not force and len(text) < _DELTA_FLUSH_CHARS):
        return
    pending.clear()
    try:
        await session_event_bus.publish(session_id, "message.delta", {"content": text})
    except Exception:
        logger.exception("failed to publish message.delta")


def _wrap_provider_error(exc: BaseException) -> LlmProviderError:
    if isinstance(exc, LlmProviderError):
        return exc
    kind = "provider"
    if isinstance(exc, ModelHTTPError):
        kind = "provider"
    return LlmProviderError(str(exc) or exc.__class__.__name__, kind=kind)


def _model_label(model: Model) -> str:
    name = getattr(model, "model_name", None)
    return str(name) if name else "pydantic-ai"


def _stash_partial(rec: LlmCallRecordBuilder, parts: list[str]) -> None:
    rec.response_text = "".join(parts).strip() or None


async def stream_chat_reply(
    *,
    user_prompt: str,
    session_id: uuid.UUID | None,
    deps: ChatDeps,
    extra_tools: Sequence[Any] = (),
) -> str | None:
    """Run the chat agent, fan out message.delta, return the final text."""
    model = _model_override or live_chat_model()
    agent = build_chat_agent(model=model, extra_tools=extra_tools)
    parts: list[str] = []
    pending: list[str] = []
    output: str | None = None
    with track(
        kind="chat_text",
        tier=NODE_MODEL_TIERS["chat"],
        model=_model_label(model),
        system=prompts.CHAT,
        user=user_prompt,
    ) as rec:
        try:
            async with agent.run_stream(user_prompt, deps=deps) as result:
                async for chunk in result.stream_text(delta=True):
                    rec.mark_first_token()
                    parts.append(chunk)
                    pending.append(chunk)
                    if session_id:
                        await _publish_deltas(session_id, pending)
                if session_id:
                    await _publish_deltas(session_id, pending, force=True)
                output = await result.get_output()
                rec.set_usage(result.usage)
        except asyncio.CancelledError:
            _stash_partial(rec, parts)
            raise
        except RunCancelled as exc:
            _stash_partial(rec, parts)
            raise asyncio.CancelledError from exc
        except (ModelHTTPError, ModelAPIError) as exc:
            _stash_partial(rec, parts)
            raise _wrap_provider_error(exc) from exc
        except LlmProviderError:
            _stash_partial(rec, parts)
            raise
        except Exception as exc:
            _stash_partial(rec, parts)
            raise _wrap_provider_error(exc) from exc
        text = (output if isinstance(output, str) else "".join(parts)).strip()
        rec.response_text = text or None
    return text or None
