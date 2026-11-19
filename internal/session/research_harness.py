"""Research inner loop for query_generator — LangChain chat models (ADR 0060).

Narrow agent: ingest via the existing Tavily∪PG adapter, then QueryGenOut.
Publish-class tools are never registered. Graph vertices stay unchanged.
``QueryGenOut`` rides the tool loop as a bound schema — the model finishes
by "calling" it (ADR 0060 §output-as-tool).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, InjectedToolArg, tool

from internal.llm.router import ModelTier
from internal.session import harness as H
from internal.session import ingest as ingest_mod
from internal.session import prompts
from internal.session.context import get_db
from internal.session.io import QueryGenOut
from internal.session.tiers import NODE_MODEL_TIERS
from schemas.tools import QueryMarketTrendsResponse

RESEARCH_TOOL_NAMES = frozenset({"ingest_web_search", "query_market_trends"})

_model_override: BaseChatModel | None = None


@dataclass
class ResearchDeps:
    ingested: list[dict[str, Any]] = field(default_factory=list)
    queries_run: list[str] = field(default_factory=list)


def set_research_model_override(model: BaseChatModel | None) -> None:
    """Test hook: inject a scripted chat model. Pass None to restore live."""
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


async def run_query_generator_agent(
    user_prompt: str,
    deps: ResearchDeps,
) -> QueryGenOut | None:
    """Run the research agent; return QueryGenOut or None on parse miss."""
    if _model_override is not None:
        chat, label = _model_override, H._model_label(_model_override)
    else:
        chat, label = H._live_lc_model(NODE_MODEL_TIERS["query_generator"] or ModelTier.CHEAP)
    return await H.run_typed_lc_agent(
        chat=chat,
        model_label=label,
        tier=NODE_MODEL_TIERS["query_generator"],
        system=prompts.QUERY_GENERATOR,
        user_prompt=user_prompt,
        deps=deps,
        tools=research_tools(),
        out_type=QueryGenOut,
        is_valid=lambda parsed: bool(parsed.atomic_queries()),
        log_tag="query_generator",
    )
