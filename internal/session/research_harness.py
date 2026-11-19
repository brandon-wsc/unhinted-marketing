"""Research inner loop for query_generator — LangChain primary, Pydantic AI fallback (ADR 0060).

Narrow agent: ingest via the existing Tavily∪PG adapter, then QueryGenOut.
Publish-class tools are never registered. Graph vertices stay unchanged.
``openai`` / ``openai_compatible`` run the ``bind_tools`` + output-as-tool
loop; ``anthropic`` / ``gemini`` / ``vertex_ai`` keep the Pydantic AI agent
until their langchain packages land — provider coverage is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, InjectedToolArg, tool
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, RunCancelled
from pydantic_ai.models import Model

from internal.llm.recorder import mark_last_call, track
from internal.llm.router import LlmProviderError, ModelTier
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import prompts
from internal.session.context import get_db
from internal.session.io import QueryGenOut, omit_nulls
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import QueryMarketTrendsResponse

logger = logging.getLogger(__name__)

RESEARCH_TOOL_NAMES = frozenset({"ingest_web_search", "query_market_trends"})

_model_override: Model | BaseChatModel | None = None


@dataclass
class ResearchDeps:
    ingested: list[dict[str, Any]] = field(default_factory=list)
    queries_run: list[str] = field(default_factory=list)


def set_research_model_override(model: Model | BaseChatModel | None) -> None:
    """Test hook: inject a fake chat model (LangChain or Pydantic AI). Pass None to restore live."""
    global _model_override
    _model_override = model


async def _run_ingest_web_search(
    deps: ResearchDeps,
    query: str,
    topic: str = "news",
    time_range: str = "week",
) -> list[dict[str, Any]]:
    """Search the web via Tavily and persist hits to PostgreSQL.

    At most 3 queries this turn, 5 hits each. Returns signal slices
    (id, title, excerpt, metrics.query) — never full pages.
    """
    if len(deps.queries_run) >= ingest_mod.MAX_QUERIES:
        return []
    q = (query or "").strip()[:200]
    if not q:
        return []
    key = q.lower()
    if any(existing.lower() == key for existing in deps.queries_run):
        return []
    deps.queries_run.append(q)
    try:
        db = get_db()
    except RuntimeError:
        return []
    items = await ingest_mod.fetch_and_upsert_tavily(
        db,
        [q],
        topic=topic,
        time_range=time_range,
        max_results=ingest_mod.MAX_HITS_PER_QUERY,
    )
    deps.ingested.extend(items)
    return ingest_mod.signal_slices(items)


async def _run_query_market_trends(
    deps: ResearchDeps,
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    del deps
    return await H.lookup_market_trends(region, limit)


@tool
async def ingest_web_search(
    deps: Annotated[ResearchDeps, InjectedToolArg],
    query: str,
    topic: str = "news",
    time_range: str = "week",
) -> str:
    """Search the web via Tavily and persist hits to PostgreSQL.

    At most 3 queries this turn, 5 hits each. Returns signal slices
    (id, title, excerpt, metrics.query) — never full pages.
    """
    slices = await _run_ingest_web_search(deps, query, topic, time_range)
    return json.dumps(slices, ensure_ascii=False, default=str)


@tool
async def query_market_trends(
    deps: Annotated[ResearchDeps, InjectedToolArg],
    region: str = "HK",
    limit: int = 20,
) -> str:
    """Read-only lookup of recent Hong Kong market signals from PostgreSQL."""
    response = await _run_query_market_trends(deps, region, limit)
    return response.model_dump_json()


def research_tools(extra_tools: Sequence[Any] = ()) -> list[Any]:
    """LangChain tools on the research loop — publish-class names never registered."""
    tools: list[Any] = [ingest_web_search, query_market_trends]
    for extra in extra_tools:
        tools.append(extra if isinstance(extra, BaseTool) else tool(extra))
    return tools


async def _pa_ingest_web_search(
    ctx: RunContext[ResearchDeps],
    query: str,
    topic: str = "news",
    time_range: str = "week",
) -> list[dict[str, Any]]:
    return await _run_ingest_web_search(ctx.deps, query, topic, time_range)


async def _pa_query_market_trends(
    ctx: RunContext[ResearchDeps],
    region: str = "HK",
    limit: int = 20,
) -> QueryMarketTrendsResponse:
    return await _run_query_market_trends(ctx.deps, region, limit)


def build_research_agent(
    *,
    model: Model,
    extra_tools: Sequence[Any] = (),
) -> Agent[ResearchDeps, QueryGenOut]:
    """Pydantic AI fallback agent — anthropic/gemini/vertex path (same tool names)."""
    tools: list[Any] = [
        Tool(_pa_ingest_web_search, name="ingest_web_search"),
        Tool(_pa_query_market_trends, name="query_market_trends"),
        *extra_tools,
    ]
    return Agent(
        model,
        deps_type=ResearchDeps,
        output_type=QueryGenOut,
        system_prompt=prompts.QUERY_GENERATOR,
        tools=tools,
        name="session_research",
        end_strategy="exhaustive",
    )


def _usage_of(result: Any) -> Any:
    usage = getattr(result, "usage", None)
    return usage() if callable(usage) else usage


async def _run_query_generator_lc(
    *,
    chat: BaseChatModel,
    model_label: str,
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    return await H.run_typed_lc_agent(
        chat=chat,
        model_label=model_label,
        tier=NODE_MODEL_TIERS["query_generator"],
        system=prompts.QUERY_GENERATOR,
        user_prompt=user_prompt,
        deps=deps,
        tools=research_tools(),
        out_type=QueryGenOut,
        is_valid=lambda parsed: bool(parsed.atomic_queries()),
        log_tag="query_generator",
    )


async def _run_query_generator_pa(
    *,
    model: Model,
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    """Pydantic AI path — anthropic/gemini/vertex until langchain packages land."""
    agent = build_research_agent(model=model)
    parsed: QueryGenOut | None = None
    with track(
        kind="chat_json",
        tier=NODE_MODEL_TIERS["query_generator"],
        model=H._model_label(model),
        system=prompts.QUERY_GENERATOR,
        user=user_prompt,
    ) as rec:
        try:
            result = await agent.run(user_prompt, deps=deps)
            rec.set_usage(_usage_of(result))
            output = result.output
            if isinstance(output, QueryGenOut):
                parsed = QueryGenOut.model_validate(omit_nulls(output.model_dump()))
            elif isinstance(output, dict):
                parsed = QueryGenOut.model_validate(omit_nulls(output))
            else:
                parsed = QueryGenOut.model_validate(omit_nulls({"search_query": str(output)}))
            rec.response_text = parsed.model_dump_json()
        except asyncio.CancelledError:
            raise
        except RunCancelled as exc:
            raise asyncio.CancelledError from exc
        except (ModelHTTPError, ModelAPIError) as exc:
            raise H._wrap_provider_error(exc) from exc
        except LlmProviderError:
            raise
        except Exception:
            mark_last_call(parse_ok=False, fallback_used=True)
            logger.exception("query_generator agent failed")
            return None
        if not parsed.atomic_queries():
            mark_last_call(parse_ok=False, fallback_used=True)
            return None
        mark_last_call(parse_ok=True)
        return parsed


async def run_query_generator_agent(
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    """Run the research agent; return QueryGenOut or None on parse miss."""
    model = _model_override
    if isinstance(model, BaseChatModel):
        return await _run_query_generator_lc(
            chat=model,
            model_label=H._model_label(model),
            user_prompt=user_prompt,
            deps=deps,
        )
    if model is None:
        lc = H._live_lc_model(NODE_MODEL_TIERS["query_generator"] or ModelTier.CHEAP)
        if lc is not None:
            chat, label = lc
            return await _run_query_generator_lc(
                chat=chat,
                model_label=label,
                user_prompt=user_prompt,
                deps=deps,
            )
        model = H.live_harness_model(NODE_MODEL_TIERS["query_generator"] or ModelTier.CHEAP)
    return await _run_query_generator_pa(
        model=model,
        user_prompt=user_prompt,
        deps=deps,
    )
